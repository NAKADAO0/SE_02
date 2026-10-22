"""Agent input, extension protocol, and validation shared with the scheduler."""

from dataclasses import dataclass
from typing import Protocol

from se02.domain import CodeArtifact, FixResult, ReviewReport, Role, Task, ValidationError
from se02.domain.base import Contract
from se02.providers import ProviderRequest


@dataclass(frozen=True, kw_only=True)
class AgentInput(Contract):
    task: Task
    code: CodeArtifact | None = None
    review: ReviewReport | None = None


AgentOutput = CodeArtifact | ReviewReport | FixResult


class Agent(Protocol):
    role: Role

    def run(self, agent_input: AgentInput) -> AgentOutput:
        ...


def validate_output(role: Role, output: AgentOutput, context: AgentInput) -> None:
    """Enforce the boundary even for a custom Agent registered with Workflow."""
    ProviderRequest(role=role, task=context.task, code=context.code, review=context.review)
    expected = {"coder": CodeArtifact, "reviewer": ReviewReport, "fixer": FixResult}[role]
    if not isinstance(output, expected):
        raise ValidationError(f"{role}: expected {expected.__name__}")
    if role == "coder" and output.version != 1:
        raise ValidationError("coder: initial artifact must be version 1")
    if role == "reviewer":
        output.validate_for(context.code)
    if role == "fixer":
        output.validate_for(context.code, context.review)
