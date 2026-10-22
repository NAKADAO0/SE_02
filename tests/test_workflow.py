import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from se02.agents import ReviewAgent
from se02.domain import ReviewReport, StorageError, Task, ValidationError
from se02.providers import MockProvider
from se02.storage import ArtifactStore
from se02.workflow import Workflow, WorkflowConfig


TASK = Task(task_id="sum", description="实现 total(values)，空列表返回 0")


class TraceProvider:
    def __init__(self, scenario="direct_pass", *, delay_pass=False):
        self.delegate = MockProvider(scenario)
        self.requests = []
        self.delay_pass = delay_pass

    def complete(self, request):
        self.requests.append(request)
        if self.delay_pass and request.role == "reviewer" and request.code.version == 2:
            return MockProvider("always_reject").complete(request)
        return self.delegate.complete(request)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_scenario(self, scenario="direct_pass", config=None, **kwargs):
        provider = TraceProvider(scenario, **kwargs)
        result = Workflow(provider, root=self.root).run(TASK, config)
        return provider, result

    def events(self, result):
        return [json.loads(line) for line in (Path(result.run_dir) / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def assert_persisted(self, result):
        root = Path(result.run_dir)
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state, result.state.to_dict())
        for ref in state["artifact_refs"] + state["message_refs"]:
            self.assertTrue((root / ref).is_file(), ref)
        self.assertIsNotNone(state["ended_at"])

    def test_direct_pass_skips_repair_and_persists_terminal_after_outputs(self):
        p, result = self.run_scenario()
        self.assertEqual([r.role for r in p.requests], ["coder", "reviewer"])
        self.assertEqual(result.state.status, "succeeded")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.state.repair_count, 0)
        self.assertEqual(result.final_code_ref, "code/v1.py")
        self.assertEqual(result.final_review_ref, "reviews/review_0.json")
        self.assertTrue(any(e["node"] == "repair_1" and e["status"] == "skipped" for e in self.events(result)))
        self.assert_persisted(result)

    def test_failed_review_drives_fix_and_reviewer_consumes_v2(self):
        p, result = self.run_scenario("repair_pass")
        self.assertEqual([r.role for r in p.requests], ["coder", "reviewer", "fixer", "reviewer"])
        self.assertEqual(p.requests[2].review.verdict, "fail")
        self.assertEqual(p.requests[3].code.version, 2)
        self.assertEqual(result.state.repair_count, 1)
        self.assertEqual(result.state.status, "succeeded")
        self.assertEqual(result.final_code_ref, "code/v2.py")
        self.assertIn("fixes/fix_v2.json", result.state.artifact_refs)
        completed = [e["node"] for e in self.events(result) if e["status"] == "completed"]
        self.assertEqual(completed, ["coder", "review_0", "repair_1", "review_1"])
        self.assert_persisted(result)

    def test_second_repair_can_still_succeed(self):
        _, result = self.run_scenario("repair_pass", delay_pass=True)
        self.assertEqual(result.state.status, "succeeded")
        self.assertEqual(result.state.repair_count, 2)
        self.assertEqual(result.final_code_ref, "code/v3.py")
        self.assertEqual(result.final_review_ref, "reviews/review_2.json")
        self.assert_persisted(result)

    def test_persistent_rejection_stops_at_exactly_two_repairs(self):
        p, result = self.run_scenario("always_reject")
        self.assertEqual([r.role for r in p.requests], ["coder", "reviewer", "fixer", "reviewer", "fixer", "reviewer"])
        self.assertEqual(result.state.status, "needs_attention")
        self.assertEqual(result.exit_code, 3)
        self.assertEqual(result.state.repair_count, 2)
        self.assertFalse((Path(result.run_dir) / "code/v4.py").exists())
        self.assert_persisted(result)

    def test_lower_repair_limits_and_invalid_configuration(self):
        for limit in (0, 1):
            with self.subTest(limit=limit):
                p, result = self.run_scenario("always_reject", WorkflowConfig(max_repairs=limit))
                self.assertEqual(result.state.status, "needs_attention")
                self.assertEqual(result.state.repair_count, limit)
                self.assertEqual(len(p.requests), 2 + 2 * limit)
        for value in (-1, 3, True, "2"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                WorkflowConfig(max_repairs=value)

    def test_provider_failure_is_terminal_and_stops_downstream_calls(self):
        p, result = self.run_scenario("call_failure")
        self.assertEqual(len(p.requests), 1)
        self.assertEqual(result.state.status, "failed")
        self.assertEqual(result.exit_code, 1)
        self.assertIsNone(result.final_code_ref)
        self.assertIn("ProviderError", result.state.error)
        self.assertTrue(any(e["node"] == "coder" and e["status"] == "failed" for e in self.events(result)))
        self.assert_persisted(result)

    def test_malformed_or_mismatched_review_does_not_start_repair(self):
        for response in ("{}", json.dumps(dict(artifact_version=99, verdict="pass", issues=[], summary="wrong version"))):
            class BadReview(TraceProvider):
                def complete(inner, request):
                    if request.role == "reviewer":
                        inner.requests.append(request)
                        return response
                    return super().complete(request)

            p = BadReview()
            result = Workflow(p, root=self.root).run(TASK)
            self.assertEqual(result.state.status, "failed")
            self.assertEqual([r.role for r in p.requests], ["coder", "reviewer"])
            self.assertIsNone(result.final_review_ref)
            self.assert_persisted(result)

    def test_registered_agent_is_used_but_cannot_bypass_output_validation(self):
        class RejectingReviewer:
            role = "reviewer"

            def run(self, context):
                return ReviewAgent(MockProvider("always_reject")).run(context)

        result = Workflow(MockProvider(), root=self.root, agents={"reviewer": RejectingReviewer()}).run(TASK)
        self.assertEqual(result.state.status, "needs_attention")

        class InvalidReviewer:
            role = "reviewer"

            def run(self, context):
                return ReviewReport(artifact_version=99, verdict="pass", issues=(), summary="invalid")

        result = Workflow(MockProvider(), root=self.root, agents={"reviewer": InvalidReviewer()}).run(TASK)
        self.assertEqual(result.state.status, "failed")
        with self.assertRaises(ValidationError):
            Workflow(MockProvider(), root=self.root, agents={"coder": RejectingReviewer()})

    def test_same_workflow_runs_are_isolated(self):
        workflow = Workflow(MockProvider("repair_pass"), root=self.root)
        one, two = workflow.run(TASK), workflow.run(TASK)
        self.assertNotEqual(one.state.run_id, two.state.run_id)
        self.assertEqual(one.state.repair_count, two.state.repair_count)
        for result in (one, two):
            self.assert_persisted(result)
            messages = [json.loads(line) for line in (Path(result.run_dir) / "messages.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(m["run_id"] == result.state.run_id for m in messages))
            roles = {(m["receiver"], m["kind"]) for m in messages}
            self.assertTrue({("fixer", "code"), ("fixer", "review"), ("reviewer", "code")}.issubset(roles))

    def test_unexpected_agent_exception_is_recorded_not_misreported(self):
        class BrokenProvider:
            def complete(self, request):
                raise RuntimeError("unexpected provider bug")

        result = Workflow(BrokenProvider(), root=self.root).run(TASK)
        self.assertEqual(result.state.status, "failed")
        self.assertIn("RuntimeError", result.state.error)
        self.assert_persisted(result)

    def test_code_write_failure_never_reports_success(self):
        with patch.object(ArtifactStore, "save_code", side_effect=StorageError("disk full")):
            _, result = self.run_scenario()
        self.assertEqual(result.state.status, "failed")
        self.assertIsNone(result.final_code_ref)
        self.assert_persisted(result)

    def test_completion_log_failure_never_reports_success(self):
        original = ArtifactStore.append_event

        def fail_completed(store, event):
            if event.node == "review_0" and event.status == "completed":
                raise StorageError("event disk failure")
            return original(store, event)

        with patch.object(ArtifactStore, "append_event", new=fail_completed):
            _, result = self.run_scenario()
        self.assertEqual(result.state.status, "failed")
        self.assert_persisted(result)

    def test_terminal_snapshot_failure_is_recovered_as_failed(self):
        original = ArtifactStore.save_state

        def reject_success(store, state):
            if state.status == "succeeded":
                raise StorageError("terminal write failure")
            return original(store, state)

        with patch.object(ArtifactStore, "save_state", new=reject_success):
            _, result = self.run_scenario()
        self.assertEqual(result.state.status, "failed")
        self.assertEqual(result.persistence_errors, ())
        self.assert_persisted(result)

    def test_failure_to_save_failure_is_exposed_in_result(self):
        with patch.object(ArtifactStore, "save_state", side_effect=StorageError("unwritable state")):
            _, result = self.run_scenario()
        self.assertEqual(result.state.status, "failed")
        self.assertTrue(result.persistence_errors)
        self.assertFalse((Path(result.run_dir) / "state.json").exists())

    def test_directory_creation_failure_and_invalid_task_are_explicit(self):
        occupied = self.root / "file"
        occupied.write_text("not a directory")
        with self.assertRaises(StorageError):
            Workflow(MockProvider(), root=occupied).run(TASK)
        with self.assertRaises(ValidationError):
            Workflow(MockProvider(), root=self.root).run("not a Task")

    def test_review_failure_after_repair_does_not_reuse_previous_report_as_final(self):
        class FailsSecondReview(TraceProvider):
            def complete(self, request):
                if request.role == "reviewer" and request.code.version == 2:
                    raise RuntimeError("second review failed")
                return super().complete(request)

        result = Workflow(FailsSecondReview("repair_pass"), root=self.root).run(TASK)
        self.assertEqual(result.state.status, "failed")
        self.assertEqual(result.state.repair_count, 1)
        self.assertEqual(result.final_code_ref, "code/v2.py")
        self.assertIsNone(result.final_review_ref)
        self.assertIn("reviews/review_0.json", result.state.artifact_refs)
        self.assert_persisted(result)

    def test_failed_event_error_is_reported_even_when_failed_snapshot_saves(self):
        original = ArtifactStore.append_event

        def fail_failure_event(store, event):
            if event.status == "failed":
                raise StorageError("failed log unavailable")
            return original(store, event)

        with patch.object(ArtifactStore, "append_event", new=fail_failure_event):
            _, result = self.run_scenario("call_failure")
        self.assertEqual(result.state.status, "failed")
        self.assertEqual(len(result.persistence_errors), 1)
        self.assertIn("failed event", result.persistence_errors[0])
        self.assert_persisted(result)


if __name__ == "__main__":
    unittest.main()
