"""Version 1 domain models; no filesystem or model SDK dependencies."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

from .base import Contract, identifier, relative_ref, text, utc_now
from .errors import ValidationError

RunStatus = Literal["pending", "running", "succeeded", "failed", "needs_attention"]
NodeStatus = Literal["pending", "running", "completed", "failed", "skipped"]
Role = Literal["coder", "reviewer", "fixer"]


def positive(value: int, name: str):
    if value < 1:
        raise ValidationError(f"{name}: must be positive")


@dataclass(frozen=True, kw_only=True)
class Task(Contract):
    task_id: str
    description: str
    language: Literal["python"] = "python"

    def validate(self):
        identifier(self.task_id, "task_id")
        text(self.description, "description")
        if len(self.description) > 10000:
            raise ValidationError("description: maximum 10000 characters")


@dataclass(frozen=True, kw_only=True)
class CodeArtifact(Contract):
    artifact_id: str
    version: int
    source: str
    explanation: str
    language: Literal["python"] = "python"
    parent_version: int | None = None

    def validate(self):
        identifier(self.artifact_id, "artifact_id")
        positive(self.version, "version")
        text(self.source, "source")
        text(self.explanation, "explanation")
        if self.parent_version != (self.version - 1 if self.version > 1 else None):
            raise ValidationError("parent_version: must refer to the preceding version; v1 has no parent")


@dataclass(frozen=True, kw_only=True)
class ReviewIssue(Contract):
    issue_id: str
    severity: Literal["blocker", "major", "minor"]
    description: str
    suggestion: str

    def validate(self):
        identifier(self.issue_id, "issue_id")
        text(self.description, "description")
        text(self.suggestion, "suggestion")


@dataclass(frozen=True, kw_only=True)
class ReviewReport(Contract):
    artifact_version: int
    verdict: Literal["pass", "fail"]
    issues: tuple[ReviewIssue, ...]
    summary: str

    def validate(self):
        positive(self.artifact_version, "artifact_version")
        text(self.summary, "summary")
        ids = [i.issue_id for i in self.issues]
        if len(ids) != len(set(ids)):
            raise ValidationError("issues: duplicate issue IDs")
        if self.verdict == "fail" and not self.issues:
            raise ValidationError("fail verdict requires at least one issue")
        if self.verdict == "pass" and any(i.severity in ("blocker", "major") for i in self.issues):
            raise ValidationError("pass verdict cannot contain blocker/major issues")

    def validate_for(self, artifact: CodeArtifact) -> None:
        if self.artifact_version != artifact.version:
            raise ValidationError("review does not refer to the supplied code version")


@dataclass(frozen=True, kw_only=True)
class FixResult(Contract):
    code_artifact: CodeArtifact
    changes: Mapping[str, str]

    def validate(self):
        for key, value in self.changes.items():
            identifier(key, "issue_id")
            text(value, "change description")

    def validate_for(self, previous: CodeArtifact, report: ReviewReport) -> None:
        report.validate_for(previous)
        if report.verdict != "fail":
            raise ValidationError("repair requires a failed review")
        if self.code_artifact.version != previous.version + 1 or self.code_artifact.parent_version != previous.version:
            raise ValidationError("repair must create the next code version")
        if set(self.changes) != {i.issue_id for i in report.issues}:
            raise ValidationError("changes must describe every review issue exactly once")


@dataclass(frozen=True, kw_only=True)
class Message(Contract):
    message_id: str
    run_id: str
    sender: str
    receiver: str
    kind: Literal["task", "code", "review", "fix", "error"]
    payload_ref: str
    created_at: datetime = field(default_factory=utc_now)
    schema_version: Literal[1] = 1

    def validate(self):
        for key in ("message_id", "run_id", "sender", "receiver"):
            identifier(getattr(self, key), key)
        relative_ref(self.payload_ref)


@dataclass(frozen=True, kw_only=True)
class RunState(Contract):
    run_id: str
    status: RunStatus = "pending"
    current_node: str | None = None
    repair_count: int = 0
    artifact_refs: tuple[str, ...] = ()
    message_refs: tuple[str, ...] = ()
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None
    schema_version: Literal[1] = 1

    def validate(self):
        identifier(self.run_id, "run_id")
        if self.current_node is not None:
            identifier(self.current_node, "current_node")
        if not 0 <= self.repair_count <= 2:
            raise ValidationError("repair_count: must be between 0 and 2")
        for ref in self.artifact_refs + self.message_refs:
            relative_ref(ref)
        if self.status == "pending" and (self.started_at is not None or self.ended_at is not None):
            raise ValidationError("pending run cannot have execution timestamps")
        if self.status == "running" and (self.started_at is None or self.ended_at is not None):
            raise ValidationError("running run requires start time and no end time")
        if self.status in ("succeeded", "failed", "needs_attention") and self.ended_at is None:
            raise ValidationError("terminal run requires end time")
        if self.status in ("succeeded", "needs_attention") and self.started_at is None:
            raise ValidationError("completed run requires start time")
        if self.ended_at is not None and self.started_at is not None and self.ended_at < self.started_at:
            raise ValidationError("end time cannot precede start time")
        if self.status == "failed":
            if self.error is None:
                raise ValidationError("failed run requires an error")
            text(self.error, "error")
        elif self.error is not None:
            raise ValidationError("error is only allowed on failed runs")

    def transition(self, status: RunStatus, *, at: datetime | None = None,
                   current_node: str | None = None, error: str | None = None):
        allowed = {"pending": {"running", "failed"},
                   "running": {"succeeded", "failed", "needs_attention"}}
        if status not in allowed.get(self.status, set()):
            raise ValidationError(f"illegal run transition: {self.status} -> {status}")
        at = utc_now() if at is None else at
        return replace(self, status=status, current_node=current_node, error=error,
                       started_at=at if status == "running" else self.started_at,
                       ended_at=None if status == "running" else at)


@dataclass(frozen=True, kw_only=True)
class ExecutionEvent(Contract):
    run_id: str
    node: str
    status: NodeStatus
    attempt: int = 1
    artifact_version: int | None = None
    elapsed_ms: float | None = None
    detail: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    schema_version: Literal[1] = 1

    def validate(self):
        identifier(self.run_id, "run_id")
        identifier(self.node, "node")
        positive(self.attempt, "attempt")
        if self.artifact_version is not None:
            positive(self.artifact_version, "artifact_version")
        if self.elapsed_ms is not None and self.elapsed_ms < 0:
            raise ValidationError("elapsed_ms cannot be negative")
        if self.detail is not None:
            text(self.detail, "detail")
