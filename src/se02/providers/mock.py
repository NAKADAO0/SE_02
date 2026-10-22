"""Deterministic sum-task fixtures, not a general code generator/reviewer."""

import json
from typing import Literal

from se02.domain import CodeArtifact, FixResult, ProviderError, ReviewIssue, ReviewReport, ValidationError
from .base import ProviderRequest

Scenario = Literal["direct_pass", "repair_pass", "always_reject", "call_failure"]
GOOD_CODE = "def total(values):\n    return sum(values)\n"
BAD_CODE = "def total(values):\n    return sum(values) if values else None\n"


class MockProvider:
    """Pure request-based fixtures: no global counters, network calls or retries."""

    def __init__(self, scenario: Scenario = "direct_pass"):
        if scenario not in ("direct_pass", "repair_pass", "always_reject", "call_failure"):
            raise ValidationError("unknown mock scenario")
        self.scenario = scenario

    def complete(self, request: ProviderRequest) -> str:
        if not isinstance(request, ProviderRequest):
            raise ValidationError("expected ProviderRequest")
        if self.scenario == "call_failure":
            raise ProviderError("Injected offline mock call failure", retryable=False)
        if request.role == "coder":
            result = CodeArtifact(
                artifact_id="mock-v1", version=1,
                source=GOOD_CODE if self.scenario == "direct_pass" else BAD_CODE,
                explanation=f"Mock sum fixture for task {request.task.task_id}; not general task generation",
            )
        elif request.role == "reviewer":
            rejected = self.scenario == "always_reject" or request.code.source != GOOD_CODE
            issues = (ReviewIssue(issue_id="EMPTY_SUM", severity="major",
                                  description="Mock fixture: empty input must return 0",
                                  suggestion="Use sum(values) for the sum fixture"),) if rejected else ()
            result = ReviewReport(artifact_version=request.code.version,
                                  verdict="fail" if rejected else "pass", issues=issues,
                                  summary="Mock fixture rejected" if rejected else "Mock fixture accepted")
        else:
            next_version = request.code.version + 1
            result = FixResult(
                code_artifact=CodeArtifact(
                    artifact_id=f"mock-v{next_version}", version=next_version,
                    parent_version=request.code.version,
                    source=BAD_CODE if self.scenario == "always_reject" else GOOD_CODE,
                    explanation="Mock sum fixture repair, not general issue resolution",
                ),
                changes={i.issue_id: f"Mock fixture response for: {i.description}" for i in request.review.issues},
            )
            result.validate_for(request.code, request.review)
        return json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False)
