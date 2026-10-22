import dataclasses
import json
import unittest
from datetime import datetime, timezone

from se02.domain import (
    CodeArtifact, ExecutionEvent, FixResult, Message, ReviewIssue, ReviewReport,
    RunState, Task, ValidationError,
)


NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def code(version=1):
    return CodeArtifact(artifact_id=f"a{version}", version=version, source="def total(xs):\n    return sum(xs)\n",
                        explanation="求和", parent_version=version - 1 if version > 1 else None)


def issue(severity="major"):
    return ReviewIssue(issue_id="I1", severity=severity, description="空列表错误", suggestion="返回 0")


class DomainTests(unittest.TestCase):
    def test_task_input_boundaries_and_strict_types(self):
        self.assertEqual(len(Task(task_id="t1", description="中" * 10000).description), 10000)
        for kwargs in ({"description": " "}, {"description": "a" * 10001},
                       {"description": 123}, {"description": "ok", "language": "js"},
                       {"description": "ok", "task_id": "../bad"}):
            with self.subTest(kwargs=str(kwargs)[:80]), self.assertRaises(ValidationError):
                Task(**({"task_id": "t1"} | kwargs))

    def test_code_version_lineage_and_nonempty_source(self):
        for values in ({"version": True}, {"version": 0}, {"version": 2},
                       {"parent_version": 1}, {"source": " "}, {"language": "bash"}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                CodeArtifact(**({"artifact_id": "a1", "version": 1, "source": "x=1", "explanation": "demo"} | values))

    def test_review_rejects_contradictory_verdict_and_duplicate_ids(self):
        cases = [("pass", (issue(),)), ("fail", ()), ("fail", (issue(), issue())), ("unknown", ())]
        for verdict, issues in cases:
            with self.subTest(verdict=verdict, issues=issues), self.assertRaises(ValidationError):
                ReviewReport(artifact_version=1, verdict=verdict, issues=issues, summary="review")
        ReviewReport(artifact_version=1, verdict="pass", issues=(issue("minor"),), summary="提示")

    def test_report_must_match_reviewed_code(self):
        report = ReviewReport(artifact_version=1, verdict="fail", issues=(issue(),), summary="失败")
        report.validate_for(code())
        with self.assertRaises(ValidationError):
            report.validate_for(code(2))

    def test_fix_requires_next_version_and_exact_issue_mapping(self):
        report = ReviewReport(artifact_version=1, verdict="fail", issues=(issue(),), summary="失败")
        FixResult(code_artifact=code(2), changes={"I1": "使用 sum"}).validate_for(code(), report)
        for fixed, changes in ((code(), {"I1": "x"}), (code(3), {"I1": "x"}),
                               (code(2), {"I2": "x"}), (code(2), {})):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                FixResult(code_artifact=fixed, changes=changes).validate_for(code(), report)
        passed = ReviewReport(artifact_version=1, verdict="pass", issues=(), summary="通过")
        with self.assertRaises(ValidationError):
            FixResult(code_artifact=code(2), changes={"I1": "x"}).validate_for(code(), passed)

    def test_json_roundtrip_restores_nested_types_and_rejects_unknown_fields(self):
        fix = FixResult(code_artifact=code(2), changes={"I1": "修复"})
        decoded = FixResult.from_dict(json.loads(json.dumps(fix.to_dict(), ensure_ascii=False)))
        self.assertEqual(decoded.code_artifact.version, 2)
        self.assertIsInstance(decoded.code_artifact, CodeArtifact)
        self.assertEqual(decoded.changes["I1"], "修复")
        for payload in ({"task_id": "t1", "description": "ok", "secret": "bad"},
                        {"description": "ok"}, {"task_id": "t1", "description": "ok", "language": None}):
            with self.assertRaises(ValidationError):
                Task.from_dict(payload)

    def test_snapshots_are_immutable_including_nested_collections(self):
        changes = {"I1": "修改"}
        fix = FixResult(code_artifact=code(2), changes=changes)
        changes["I1"] = "外部改写"
        self.assertEqual(fix.changes["I1"], "修改")
        with self.assertRaises(TypeError):
            fix.changes["I1"] = "改写"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            fix.code_artifact.version = 3

    def test_message_rejects_unsafe_refs_naive_time_and_schema(self):
        base = dict(message_id="m1", run_id="r1", sender="coder", receiver="reviewer",
                    kind="code", payload_ref="code/v1.py", created_at=NOW)
        self.assertEqual(Message.from_dict(Message(**base).to_dict()).created_at, NOW)
        for values in ({"payload_ref": "../secret"}, {"payload_ref": "C:\\secret"},
                       {"payload_ref": "/tmp/a"}, {"payload_ref": "code\\v1.py"},
                       {"created_at": datetime(2026, 10, 22)}, {"schema_version": 2}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Message(**(base | values))

    def test_run_transitions_enforce_terminal_state_and_repair_bounds(self):
        pending = RunState(run_id="r1")
        active = pending.transition("running", current_node="coder", at=NOW)
        self.assertEqual(pending.status, "pending")
        self.assertEqual(active.started_at, NOW)
        for status in ("succeeded", "needs_attention", "failed"):
            done = active.transition(status, at=NOW, error="boom" if status == "failed" else None)
            self.assertEqual(done.ended_at, NOW)
            with self.assertRaises(ValidationError):
                done.transition("running", at=NOW)
        with self.assertRaises(ValidationError):
            active.transition("pending", at=NOW)
        with self.assertRaises(ValidationError):
            pending.transition("succeeded", at=NOW)
        for values in ({"repair_count": -1}, {"repair_count": 3}, {"status": "succeeded"},
                       {"status": "running"}, {"status": "failed", "ended_at": NOW}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                RunState(run_id="r1", **values)

    def test_event_requires_positive_attempt_valid_status_and_elapsed(self):
        base = dict(run_id="r1", node="review_0", status="completed", created_at=NOW, elapsed_ms=2.5)
        self.assertEqual(ExecutionEvent(**base).to_dict()["node"], "review_0")
        for values in ({"attempt": 0}, {"elapsed_ms": -1}, {"elapsed_ms": float("nan")},
                       {"status": "typo"}, {"created_at": "yesterday"}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ExecutionEvent(**(base | values))


if __name__ == "__main__":
    unittest.main()
