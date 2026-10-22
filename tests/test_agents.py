import json
import unittest
from dataclasses import replace

from se02.agents import AgentInput, CodingAgent, ReviewAgent, RepairAgent
from se02.domain import CodeArtifact, FixResult, ProviderError, ReviewReport, Task, ValidationError
from se02.providers import MockProvider


TASK = Task(task_id="sum", description="实现 total(values)，空列表返回 0")


class ResponseProvider:
    """Capture a real role request and substitute only the external response."""

    def __init__(self, response):
        self.response = response
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.response


class AgentTests(unittest.TestCase):
    def test_three_roles_pass_current_context_with_distinct_prompts(self):
        mock = MockProvider("repair_pass")

        class Capture:
            def __init__(self):
                self.requests = []

            def complete(self, request):
                self.requests.append(request)
                return mock.complete(request)

        provider = Capture()
        artifact = CodingAgent(provider).run(AgentInput(task=TASK))
        report = ReviewAgent(provider).run(AgentInput(task=TASK, code=artifact))
        fixed = RepairAgent(provider).run(AgentInput(task=TASK, code=artifact, review=report))
        self.assertIsInstance(fixed, FixResult)
        self.assertEqual([r.role for r in provider.requests], ["coder", "reviewer", "fixer"])
        self.assertEqual(len({r.system_prompt for r in provider.requests}), 3)
        self.assertTrue(all(r.system_prompt.strip() for r in provider.requests))
        self.assertEqual(provider.requests[1].code, artifact)
        self.assertEqual(provider.requests[2].review, report)
        self.assertTrue(all(r.task == TASK for r in provider.requests))
        self.assertEqual(fixed.code_artifact.version, 2)

    def test_coder_rejects_non_initial_code(self):
        artifact = CodingAgent(MockProvider()).run(AgentInput(task=TASK))
        response = replace(artifact, artifact_id="v2", version=2, parent_version=1).to_dict()
        with self.assertRaises(ValidationError):
            CodingAgent(ResponseProvider(json.dumps(response))).run(AgentInput(task=TASK))

    def test_strict_response_rejects_fences_duplicate_keys_constants_and_bad_types(self):
        for response in ('not json', '```json\n{}\n```', '[]', 'null', 1,
                         '{"version":1,"version":2}', '{"version":NaN}',
                         '{"task_id":"unexpected"}', '{"version":Infinity}'):
            with self.subTest(response=response), self.assertRaises(ValidationError):
                CodingAgent(ResponseProvider(response)).run(AgentInput(task=TASK))

    def test_reviewer_rejects_report_bound_to_other_version(self):
        artifact = CodingAgent(MockProvider()).run(AgentInput(task=TASK))
        report = ReviewReport(artifact_version=2, verdict="pass", issues=(), summary="通过")
        with self.assertRaises(ValidationError):
            ReviewAgent(ResponseProvider(json.dumps(report.to_dict()))).run(AgentInput(task=TASK, code=artifact))

    def test_repair_rejects_incomplete_issue_mapping(self):
        p = MockProvider("repair_pass")
        artifact = CodingAgent(p).run(AgentInput(task=TASK))
        report = ReviewAgent(p).run(AgentInput(task=TASK, code=artifact))
        fixed = RepairAgent(p).run(AgentInput(task=TASK, code=artifact, review=report))
        response = fixed.to_dict() | {"changes": {}}
        with self.assertRaises(ValidationError):
            RepairAgent(ResponseProvider(json.dumps(response))).run(AgentInput(task=TASK, code=artifact, review=report))

    def test_invalid_context_never_calls_provider(self):
        p = ResponseProvider("{}")
        with self.assertRaises(ValidationError):
            ReviewAgent(p).run(AgentInput(task=TASK))
        with self.assertRaises(ValidationError):
            RepairAgent(p).run(AgentInput(task=TASK))
        self.assertEqual(p.requests, [])

    def test_provider_failure_remains_a_provider_error(self):
        with self.assertRaises(ProviderError):
            CodingAgent(MockProvider("call_failure")).run(AgentInput(task=TASK))


if __name__ == "__main__":
    unittest.main()
