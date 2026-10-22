import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from se02.domain import (CodeArtifact, ExecutionEvent, FixResult, Message, ProviderError,
                         ReviewIssue, ReviewReport, RunState, StorageError, Task, ValidationError)
from se02.providers import MockProvider, ProviderRequest
from se02.storage import ArtifactStore


TASK = Task(task_id="sum", description="实现 total(values)，空列表返回 0")


def initial(provider):
    return CodeArtifact.from_dict(json.loads(provider.complete(ProviderRequest(role="coder", task=TASK))))


def review(provider, artifact):
    return ReviewReport.from_dict(json.loads(provider.complete(
        ProviderRequest(role="reviewer", task=TASK, code=artifact))))


class MockProviderTests(unittest.TestCase):
    def test_direct_pass_uses_request_version_and_is_repeatable(self):
        provider = MockProvider("direct_pass")
        a = initial(provider)
        self.assertEqual(a.source, "def total(values):\n    return sum(values)\n")
        self.assertEqual(review(provider, a).verdict, "pass")
        self.assertEqual(initial(provider).to_dict(), a.to_dict())
        newer = replace(a, artifact_id="a2", version=2, parent_version=1)
        self.assertEqual(review(provider, newer).artifact_version, 2)

    def test_repair_pass_consumes_report_and_creates_next_version(self):
        provider = MockProvider("repair_pass")
        a = initial(provider)
        report = review(provider, a)
        self.assertEqual(report.verdict, "fail")
        fixed = FixResult.from_dict(json.loads(provider.complete(
            ProviderRequest(role="fixer", task=TASK, code=a, review=report))))
        fixed.validate_for(a, report)
        self.assertEqual(fixed.code_artifact.version, 2)
        self.assertEqual(set(fixed.changes), {"EMPTY_SUM"})
        self.assertEqual(review(provider, fixed.code_artifact).verdict, "pass")

    def test_always_reject_does_not_count_calls_or_silently_pass(self):
        provider = MockProvider("always_reject")
        artifact = initial(provider)
        for _ in range(3):
            report = review(provider, artifact)
            self.assertEqual(report.verdict, "fail")
            artifact = FixResult.from_dict(json.loads(provider.complete(
                ProviderRequest(role="fixer", task=TASK, code=artifact, review=report)))).code_artifact

    def test_call_failure_is_explicit_and_nonretryable(self):
        with self.assertRaises(ProviderError) as caught:
            initial(MockProvider("call_failure"))
        self.assertFalse(caught.exception.retryable)

    def test_request_rejects_missing_context_wrong_versions_and_unknown_scenario(self):
        artifact = initial(MockProvider())
        wrong = ReviewReport(artifact_version=2, verdict="fail", issues=(ReviewIssue(
            issue_id="I1", severity="major", description="问题", suggestion="修复"),), summary="拒绝")
        cases = [dict(role="reviewer"), dict(role="fixer", code=artifact),
                 dict(role="fixer", code=artifact, review=wrong), dict(role="coder", code=artifact),
                 dict(role="other")]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ProviderRequest(task=TASK, **values)
        with self.assertRaises(ValidationError):
            MockProvider("unknown")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ArtifactStore.create(self.root, run_id="run1")

    def test_separate_runs_and_duplicate_run_are_not_overwritten(self):
        other = ArtifactStore.create(self.root)
        self.assertNotEqual(self.store.run_id, other.run_id)
        with self.assertRaises(StorageError):
            ArtifactStore.create(self.root, run_id="run1")
        task_ref = self.store.save_task(TASK)
        self.assertEqual(task_ref, "task.json")
        self.assertEqual(json.loads(self.store.resolve_ref(task_ref).read_text(encoding="utf-8"))["description"], TASK.description)
        with self.assertRaises(StorageError):
            self.store.save_task(TASK)

    def test_code_history_and_review_links_are_preserved(self):
        artifact = initial(MockProvider())
        self.assertEqual(self.store.save_code(artifact), "code/v1.py")
        with self.assertRaises(StorageError):
            self.store.save_code(replace(artifact, source="OVERRIDE"))
        self.assertEqual(self.store.resolve_ref("code/v1.py").read_text(encoding="utf-8"), artifact.source)
        self.assertEqual(json.loads(self.store.resolve_ref("code/v1.json").read_text(encoding="utf-8"))["artifact_id"], artifact.artifact_id)
        report = review(MockProvider(), artifact)
        self.assertEqual(self.store.save_review(report, artifact, review_index=0), "reviews/review_0.json")
        with self.assertRaises(ValidationError):
            self.store.save_review(replace(report, artifact_version=2), artifact, review_index=1)
        with self.assertRaises(StorageError):
            self.store.save_review(report, artifact, review_index=0)

    def test_fix_persists_mapping_and_rejects_missing_previous_artifacts(self):
        p = MockProvider("repair_pass")
        artifact = initial(p)
        report = review(p, artifact)
        fixed = FixResult.from_dict(json.loads(p.complete(ProviderRequest(
            role="fixer", task=TASK, code=artifact, review=report))))
        with self.assertRaises(StorageError):
            self.store.save_fix(fixed, artifact, report)
        self.store.save_code(artifact)
        self.store.save_review(report, artifact, review_index=0)
        self.assertEqual(self.store.save_fix(fixed, artifact, report), "fixes/fix_v2.json")
        self.assertTrue(self.store.resolve_ref("code/v2.py").is_file())

    def test_state_can_advance_but_not_revert_terminal_or_mix_runs(self):
        state = RunState(run_id="run1")
        self.store.save_state(state)
        active = state.transition("running", current_node="coder")
        self.store.save_state(active)
        done = active.transition("failed", error="服务失败")
        self.store.save_state(done)
        self.assertEqual(json.loads(self.store.resolve_ref("state.json").read_text(encoding="utf-8"))["status"], "failed")
        for bad in (active, RunState(run_id="other")):
            with self.assertRaises(ValidationError):
                self.store.save_state(bad)

    def test_message_reference_ids_and_jsonl_events(self):
        message = Message(message_id="m1", run_id="run1", sender="user", receiver="coder",
                          kind="task", payload_ref="task.json")
        with self.assertRaises(StorageError):
            self.store.append_message(message)
        self.store.save_task(TASK)
        self.assertEqual(self.store.append_message(message), "messages/m1.json")
        with self.assertRaises(StorageError):
            self.store.append_message(message)
        for i in (1, 2):
            self.store.append_event(ExecutionEvent(run_id="run1", node="coder", status="running", attempt=i))
        events = [json.loads(line) for line in self.store.resolve_ref("events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["attempt"] for e in events], [1, 2])
        messages = self.store.resolve_ref("messages.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(messages), 1)
        self.assertEqual(json.loads(messages[0])["message_id"], "m1")
        with self.assertRaises(ValidationError):
            self.store.append_event(ExecutionEvent(run_id="other", node="coder", status="failed"))

    def test_portable_path_checks_block_traversal_and_windows_aliases(self):
        for ref in ("../outside", "/absolute", "a/../../b", "C:/secret", "a\\b", "a//b", "NUL.txt", "a./b"):
            with self.subTest(ref=ref), self.assertRaises(ValidationError):
                self.store.resolve_ref(ref)

    def test_symlink_escape_is_rejected_if_supported(self):
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.store.run_dir / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Windows account lacks symlink privilege")
        with self.assertRaises(ValidationError):
            self.store.resolve_ref("link/out.json")

    def test_atomic_state_failure_preserves_previous_snapshot_and_cleans_temp(self):
        state = RunState(run_id="run1")
        self.store.save_state(state)
        with patch("se02.storage.filesystem.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(StorageError):
                self.store.save_state(state.transition("running"))
        self.assertEqual(json.loads(self.store.resolve_ref("state.json").read_text(encoding="utf-8"))["status"], "pending")
        self.assertEqual(list(self.store.run_dir.rglob("*.tmp")), [])

    def test_public_path_and_run_id_inputs_have_domain_errors(self):
        for ref in (None, 123, ""):
            with self.subTest(ref=ref), self.assertRaises(ValidationError):
                self.store.resolve_ref(ref)
        with self.assertRaises(ValidationError):
            ArtifactStore.create(self.root, run_id=123)

    def test_metadata_failure_keeps_partial_history_and_reports_failure(self):
        artifact = initial(MockProvider())
        real_link = __import__("os").link

        def fail_metadata(source, target):
            if str(target).endswith(".json"):
                raise OSError("metadata write failed")
            return real_link(source, target)

        with patch("se02.storage.filesystem.os.link", side_effect=fail_metadata):
            with self.assertRaises(StorageError):
                self.store.save_code(artifact)
        self.assertTrue(self.store.resolve_ref("code/v1.py").is_file())
        self.assertFalse(self.store.resolve_ref("code/v1.json").exists())
        with self.assertRaises(StorageError):
            self.store.save_code(artifact)
        with self.assertRaises(StorageError):
            self.store.save_review(review(MockProvider(), artifact), artifact, review_index=0)

    def test_changed_content_cannot_reuse_a_persisted_code_version(self):
        artifact = initial(MockProvider())
        self.store.save_code(artifact)
        modified = replace(artifact, source="def total(values):\n    return 999\n")
        with self.assertRaises(ValidationError):
            self.store.save_review(review(MockProvider(), modified), modified, review_index=0)

    def test_crlf_source_preserves_exact_review_binding(self):
        artifact = replace(initial(MockProvider()), source="def total(values):\r\n    return sum(values)\r\n")
        self.store.save_code(artifact)
        report = ReviewReport(artifact_version=1, verdict="pass", issues=(), summary="通过")
        self.assertEqual(self.store.save_review(report, artifact, review_index=0), "reviews/review_0.json")
        self.assertEqual(self.store.resolve_ref("code/v1.py").read_bytes(), artifact.source.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
