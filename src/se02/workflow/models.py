"""Configuration and terminal result of one workflow invocation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from se02.domain import RunState, ValidationError
from se02.domain.base import Contract, relative_ref


@dataclass(frozen=True, kw_only=True)
class WorkflowConfig(Contract):
    max_repairs: Literal[0, 1, 2] = 2


@dataclass(frozen=True, kw_only=True)
class RunResult(Contract):
    state: RunState
    run_dir: str
    final_code_ref: str | None = None
    final_review_ref: str | None = None
    persistence_errors: tuple[str, ...] = ()

    def validate(self):
        if self.state.status not in ("succeeded", "failed", "needs_attention"):
            raise ValidationError("RunResult requires a terminal state")
        if not Path(self.run_dir).is_absolute():
            raise ValidationError("run_dir must be absolute")
        for ref in (self.final_code_ref, self.final_review_ref):
            if ref is not None:
                relative_ref(ref)

    @property
    def exit_code(self) -> int:
        return {"succeeded": 0, "failed": 1, "needs_attention": 3}[self.state.status]
