"""Sequential orchestration with explicit persistence and bounded repair rounds."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from se02.agents import Agent, AgentInput, CodingAgent, RepairAgent, ReviewAgent
from se02.agents.base import validate_output
from se02.domain import CodeArtifact, ExecutionEvent, Message, RunState, Task, ValidationError
from se02.providers import Provider
from se02.providers.telemetry import attempt_scope
from se02.storage import ArtifactStore
from .models import RunResult, WorkflowConfig


class Workflow:
    """Reusable composition root; mutable state belongs to each run, not this object."""

    def __init__(self, provider: Provider, *, root: str | Path = "runs", agents: Mapping[str, Agent] | None = None, on_event=None):
        if not callable(getattr(provider, "complete", None)):
            raise ValidationError("provider must implement complete(request)")
        if on_event is not None and not callable(on_event):
            raise ValidationError("on_event must be callable")
        self.on_event = on_event
        self.root = Path(root)
        self.agents = {"coder": CodingAgent(provider), "reviewer": ReviewAgent(provider), "fixer": RepairAgent(provider)}
        if agents is not None:
            if not isinstance(agents, Mapping):
                raise ValidationError("agents must be a role-to-agent mapping")
            for role, agent in agents.items():
                if role not in self.agents or getattr(agent, "role", None) != role or not callable(getattr(agent, "run", None)):
                    raise ValidationError("registered agent must implement run and match a known role")
                self.agents[role] = agent

    def run(self, task: Task, config: WorkflowConfig | None = None, *, initial_code: CodeArtifact | None = None) -> RunResult:
        if not isinstance(task, Task):
            raise ValidationError("task must be a Task")
        config = WorkflowConfig() if config is None else config
        if not isinstance(config, WorkflowConfig):
            raise ValidationError("config must be WorkflowConfig")
        if initial_code is not None and (not isinstance(initial_code, CodeArtifact) or initial_code.version != 1):
            raise ValidationError("initial_code must be a version 1 CodeArtifact")
        # Creation errors propagate: no run exists in which to record a failure.
        store = ArtifactStore.create(self.root)
        return _Execution(store, dict(self.agents), config, self.on_event).run(task, initial_code)


class _Execution:
    def __init__(self, store: ArtifactStore, agents: Mapping[str, Agent], config: WorkflowConfig, on_event=None):
        self.on_event = on_event
        self.store, self.agents, self.config = store, agents, config
        self.state = RunState(run_id=store.run_id)
        self.artifacts = []
        self.messages = []
        self.final_code_ref = None
        self.final_review_ref = None
        self.node = "setup"
        self.node_started = perf_counter()

    def _save_state(self, candidate: RunState):
        candidate = replace(candidate, artifact_refs=tuple(self.artifacts), message_refs=tuple(self.messages))
        self.store.save_state(candidate)
        # Keep the last known persisted state if the write raises.
        self.state = candidate

    def _message(self, sender: str, receiver: str, kind: str, ref: str):
        message = Message(message_id=uuid4().hex, run_id=self.store.run_id, sender=sender,
                          receiver=receiver, kind=kind, payload_ref=ref)
        self.messages.append(self.store.append_message(message))

    def _append_event(self, event):
        self.store.append_event(event)
        if self.on_event is not None:
            self.on_event(event)

    def _provider_event(self, event):
        self._append_event(ExecutionEvent(run_id=self.store.run_id, node=self.node,
            status=event.status, phase="provider", attempt=event.attempt,
            elapsed_ms=event.elapsed_ms, detail=event.detail))

    def _event(self, status: str, *, version=None, detail=None):
        self._append_event(ExecutionEvent(
            run_id=self.store.run_id, node=self.node, status=status,
            artifact_version=version, elapsed_ms=(perf_counter() - self.node_started) * 1000,
            detail=detail,
        ))

    def _node(self, node, role, context, save, *, repair_count=None):
        self.node, self.node_started = node, perf_counter()
        candidate = replace(self.state, current_node=node)
        if repair_count is not None:
            candidate = replace(candidate, repair_count=repair_count)
        self._save_state(candidate)
        self._event("running", version=context.code.version if context.code is not None else None)
        with attempt_scope(self._provider_event):
            output = self.agents[role].run(context)
        validate_output(role, output, context)
        ref, version = save(output)
        detail = None
        if role == "reviewer":
            verdict_text = "审查通过" if output.verdict == "pass" else f"审查未通过（发现 {len(output.issues)} 项问题）"
            detail = f"本次审查结论【{verdict_text}】：{output.summary}"
        elif role == "fixer":
            detail = f"已完成代码修复（生成版本 v{version}）：{output.code_artifact.explanation}"
        elif role == "coder":
            detail = f"已生成初始代码（版本 v{version}）：{output.explanation}"
        self._event("completed", version=version, detail=detail)
        self._save_state(self.state)
        return output, ref

    def _save_code(self, artifact):
        ref = self.store.save_code(artifact)
        self.artifacts.extend((ref, f"code/v{artifact.version}.json"))
        self.final_code_ref = ref
        return ref, artifact.version

    def _save_review(self, report, artifact, index):
        ref = self.store.save_review(report, artifact, review_index=index)
        self.artifacts.append(ref)
        self.final_review_ref = ref
        return ref, artifact.version

    def _save_fix(self, fixed, previous, report):
        ref = self.store.save_fix(fixed, previous, report)
        version = fixed.code_artifact.version
        self.artifacts.extend((f"code/v{version}.py", f"code/v{version}.json", ref))
        self.final_code_ref = f"code/v{version}.py"
        self.final_review_ref = None  # A report for the old version is not the new version's review.
        return ref, version

    def _result(self, *, persistence_errors=()):
        return RunResult(state=self.state, run_dir=str(self.store.run_dir),
                         final_code_ref=self.final_code_ref, final_review_ref=self.final_review_ref,
                         persistence_errors=tuple(persistence_errors))

    def _finish(self, status):
        self._save_state(self.state.transition(status, current_node=self.node))
        return self._result()

    def _failed(self, exc: Exception):
        error = f"{type(exc).__name__}: {exc}"
        persistence_errors = []
        try:
            self._event("failed", detail=error)
        except Exception as log_error:
            persistence_errors.append(f"failed event: {type(log_error).__name__}: {log_error}")
        failed = self.state.transition("failed", current_node=self.node, error=error)
        failed = replace(failed, artifact_refs=tuple(self.artifacts), message_refs=tuple(self.messages))
        try:
            self.store.save_state(failed)
        except Exception as state_error:
            persistence_errors.append(f"failed snapshot: {type(state_error).__name__}: {state_error}")
        self.state = failed  # Return the failure even if disk persistence was impossible.
        return self._result(persistence_errors=persistence_errors)

    def run(self, task: Task, initial_code: CodeArtifact | None = None) -> RunResult:
        try:
            task_ref = self.store.save_task(task)
            self.artifacts.append(task_ref)
            self._save_state(self.state)
            self.node = "upload" if initial_code is not None else "coder"
            self._save_state(self.state.transition("running", current_node=self.node))
            if initial_code is not None:
                self._event("running", version=1)
                artifact = initial_code
                code_ref, _ = self._save_code(artifact)
                self._event("completed", version=1, detail="已保存上传的源码为初始版本（v1）")
                self._save_state(self.state)
                code_sender = "user"
            else:
                self._message("user", "coder", "task", task_ref)
                artifact, code_ref = self._node("coder", "coder", AgentInput(task=task), self._save_code)
                code_sender = "coder"

            for index in range(self.config.max_repairs + 1):
                self.node = f"review_{index}"
                self._message("workflow", "reviewer", "task", task_ref)
                self._message(code_sender, "reviewer", "code", code_ref)
                report, report_ref = self._node(
                    self.node, "reviewer", AgentInput(task=task, code=artifact),
                    lambda output: self._save_review(output, artifact, index),
                )
                self._message("reviewer", "workflow", "review", report_ref)
                if report.verdict == "pass":
                    if index < self.config.max_repairs:
                        self._append_event(ExecutionEvent(
                            run_id=self.store.run_id, node=f"repair_{index + 1}", status="skipped",
                            artifact_version=artifact.version, detail="本次审查已通过，无需继续修复",
                        ))
                    return self._finish("succeeded")
                if index == self.config.max_repairs:
                    return self._finish("needs_attention")

                self.node = f"repair_{index + 1}"
                self._message("workflow", "fixer", "task", task_ref)
                self._message(code_sender, "fixer", "code", code_ref)
                self._message("reviewer", "fixer", "review", report_ref)
                fixed, fix_ref = self._node(
                    self.node, "fixer", AgentInput(task=task, code=artifact, review=report),
                    lambda output: self._save_fix(output, artifact, report), repair_count=index + 1,
                )
                self._message("fixer", "workflow", "fix", fix_ref)
                artifact = fixed.code_artifact
                code_ref, code_sender = self.final_code_ref, "fixer"
        except Exception as exc:
            # Record unexpected adapter/agent bugs as well; process interrupts still propagate.
            return self._failed(exc)
