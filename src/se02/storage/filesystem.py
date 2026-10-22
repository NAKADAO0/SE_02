"""Single-writer local repository with atomic per-file publication."""

import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from se02.domain import (
    CodeArtifact, ExecutionEvent, FixResult, Message, ReviewReport, RunState,
    StorageError, Task, ValidationError,
)
from se02.domain.base import identifier, relative_ref


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


class ArtifactStore:
    """Use create() once per run; this repository is not a concurrent database."""

    def __init__(self, run_dir: Path, run_id: str):
        identifier(run_id, "run_id")
        self.run_id = run_id
        self.run_dir = run_dir.resolve()

    @classmethod
    def create(cls, root: str | Path, *, run_id: str | None = None):
        run_id = uuid4().hex if run_id is None else run_id
        identifier(run_id, "run_id")
        try:
            root = Path(root).resolve()
            root.mkdir(parents=True, exist_ok=True)
            run_dir = root / run_id
            run_dir.mkdir(exist_ok=False)
            return cls(run_dir, run_id)
        except OSError as exc:
            raise StorageError(f"cannot create run directory: {exc}") from exc

    def resolve_ref(self, ref: str) -> Path:
        relative_ref(ref)
        candidate = (self.run_dir / ref).resolve()
        if not candidate.is_relative_to(self.run_dir):
            raise ValidationError("reference escapes the run directory")
        return candidate

    def _atomic_write(self, ref: str, body: str, *, replace_existing: bool = False) -> str:
        target = self.resolve_ref(ref)
        temp_path = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                             dir=target.parent, suffix=".tmp", delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            if replace_existing:
                os.replace(temp_path, target)
            else:
                # Unlike replace(), hard-link publication fails if history already exists.
                os.link(temp_path, target)
            return ref
        except OSError as exc:
            raise StorageError(f"cannot save {ref}: {exc}") from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass  # Never mask the original publication failure.

    def _append(self, ref: str, data: dict) -> str:
        target = self.resolve_ref(ref)
        try:
            with target.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return ref
        except OSError as exc:
            raise StorageError(f"cannot append {ref}: {exc}") from exc

    def _read(self, ref: str) -> dict:
        try:
            return json.loads(self.resolve_ref(ref).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StorageError(f"cannot read {ref}: {exc}") from exc

    def _match_code(self, artifact: CodeArtifact):
        stored = CodeArtifact.from_dict(self._read(f"code/v{artifact.version}.json"))
        try:
            source = self.resolve_ref(f"code/v{artifact.version}.py").read_bytes()
        except OSError as exc:
            raise StorageError("referenced code source is missing") from exc
        if stored != artifact or source != artifact.source.encode("utf-8"):
            raise ValidationError("supplied code does not match persisted artifact")

    def _same_run(self, run_id: str):
        if run_id != self.run_id:
            raise ValidationError("object belongs to a different run")

    def save_task(self, task: Task) -> str:
        return self._atomic_write("task.json", _json(task.to_dict()))

    def save_code(self, artifact: CodeArtifact) -> str:
        if artifact.parent_version is not None:
            self._read(f"code/v{artifact.parent_version}.json")
        # Preflight both paths; publication is atomic per file, not a multi-file transaction.
        refs = (f"code/v{artifact.version}.py", f"code/v{artifact.version}.json")
        if any(self.resolve_ref(ref).exists() for ref in refs):
            raise StorageError("code version already exists")
        self._atomic_write(refs[0], artifact.source)
        self._atomic_write(refs[1], _json(artifact.to_dict()))
        return refs[0]

    def save_review(self, report: ReviewReport, artifact: CodeArtifact, *, review_index: int) -> str:
        if type(review_index) is not int or review_index < 0:
            raise ValidationError("review_index must be a non-negative integer")
        report.validate_for(artifact)
        self._match_code(artifact)
        return self._atomic_write(f"reviews/review_{review_index}.json", _json(report.to_dict()))

    def save_fix(self, result: FixResult, previous: CodeArtifact, report: ReviewReport) -> str:
        result.validate_for(previous, report)
        self._match_code(previous)
        try:
            matching = any(self._read(p.relative_to(self.run_dir).as_posix()) == report.to_dict()
                           for p in self.run_dir.glob("reviews/review_*.json"))
        except OSError as exc:
            raise StorageError("cannot read persisted reviews") from exc
        if not matching:
            raise StorageError("repair requires a persisted matching review")
        self.save_code(result.code_artifact)
        return self._atomic_write(f"fixes/fix_v{result.code_artifact.version}.json", _json(result.to_dict()))

    def save_state(self, state: RunState) -> str:
        self._same_run(state.run_id)
        for ref in state.artifact_refs + state.message_refs:
            if not self.resolve_ref(ref).is_file():
                raise StorageError(f"state references missing artifact: {ref}")
        if self.resolve_ref("state.json").exists():
            previous = RunState.from_dict(self._read("state.json"))
            if previous.status != state.status:
                previous.transition(state.status, at=state.ended_at or state.started_at, error=state.error)
            elif previous.status in ("succeeded", "failed", "needs_attention") and previous != state:
                raise ValidationError("terminal snapshot cannot change")
            if state.repair_count < previous.repair_count:
                raise ValidationError("repair count cannot decrease")
            if previous.started_at is not None and state.started_at != previous.started_at:
                raise ValidationError("start time cannot change")
        return self._atomic_write("state.json", _json(state.to_dict()), replace_existing=True)

    def append_message(self, message: Message) -> str:
        self._same_run(message.run_id)
        if not self.resolve_ref(message.payload_ref).is_file():
            raise StorageError("message payload does not exist")
        ref = f"messages/{message.message_id}.json"
        self._atomic_write(ref, _json(message.to_dict()))
        self._append("messages.jsonl", message.to_dict())
        return ref

    def append_event(self, event: ExecutionEvent) -> str:
        self._same_run(event.run_id)
        return self._append("events.jsonl", event.to_dict())
