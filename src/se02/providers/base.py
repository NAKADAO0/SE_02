"""Provider boundary; responses are JSON text parsed by the consuming role."""

from dataclasses import dataclass
from typing import Protocol

from se02.domain import CodeArtifact, ReviewReport, Role, Task, ValidationError
from se02.domain.base import Contract


@dataclass(frozen=True, kw_only=True)
class ProviderRequest(Contract):
    role: Role
    task: Task
    code: CodeArtifact | None = None
    review: ReviewReport | None = None
    system_prompt: str = ""
    output_format: str = "json"

    def validate(self):
        if self.output_format != "json":
            raise ValidationError("only JSON output is supported")
        if self.role == "coder" and (self.code is not None or self.review is not None):
            raise ValidationError("coder accepts task context only")
        if self.role in ("reviewer", "fixer") and self.code is None:
            raise ValidationError("reviewer/fixer requires current code")
        if self.role == "reviewer" and self.review is not None:
            raise ValidationError("reviewer does not accept a prior verdict")
        if self.role == "fixer":
            if self.review is None or self.review.verdict != "fail":
                raise ValidationError("fixer requires a failed review")
            self.review.validate_for(self.code)


class Provider(Protocol):
    def complete(self, request: ProviderRequest) -> str:
        """Return a response or raise ProviderError; never execute generated code."""
        ...
