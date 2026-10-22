"""Stage one Mock code/review exchange; intentionally not a workflow runner."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter

from se02.domain import (
    CodeArtifact, DomainError, ExecutionEvent, Message, ReviewReport, RunState, Task,
)
from se02.providers import MockProvider, ProviderRequest
from se02.storage import ArtifactStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("runs"))
    parser.add_argument("--scenario", default="repair_pass",
                        choices=("direct_pass", "repair_pass", "always_reject", "call_failure"))
    args = parser.parse_args()
    store = None
    state = None
    node = "setup"
    started = perf_counter()
    try:
        store = ArtifactStore.create(args.root)
        task = Task(task_id="sum-demo", description="实现 total(values)，返回列表之和，空列表返回 0。")
        task_ref = store.save_task(task)
        state = RunState(run_id=store.run_id)
        store.save_state(state)
        state = state.transition("running", current_node="coder")
        store.save_state(state)
        task_message = store.append_message(Message(message_id="task-to-coder", run_id=store.run_id,
                                                    sender="user", receiver="coder", kind="task", payload_ref=task_ref))
        provider = MockProvider(args.scenario)
        node = "coder"
        started = perf_counter()
        store.append_event(ExecutionEvent(run_id=store.run_id, node=node, status="running"))
        artifact = CodeArtifact.from_dict(json.loads(provider.complete(ProviderRequest(role="coder", task=task))))
        code_ref = store.save_code(artifact)
        store.append_event(ExecutionEvent(run_id=store.run_id, node=node, status="completed",
                                          artifact_version=1, elapsed_ms=(perf_counter() - started) * 1000))
        code_message = store.append_message(Message(message_id="code-to-reviewer", run_id=store.run_id,
                                                    sender="coder", receiver="reviewer", kind="code", payload_ref=code_ref))
        node = "review_0"
        started = perf_counter()
        store.append_event(ExecutionEvent(run_id=store.run_id, node=node, status="running"))
        report = ReviewReport.from_dict(json.loads(provider.complete(
            ProviderRequest(role="reviewer", task=task, code=artifact))))
        report_ref = store.save_review(report, artifact, review_index=0)
        store.append_event(ExecutionEvent(run_id=store.run_id, node=node, status="completed",
                                          artifact_version=1, elapsed_ms=(perf_counter() - started) * 1000))
        review_message = store.append_message(Message(message_id="review-to-workflow", run_id=store.run_id,
                                                      sender="reviewer", receiver="workflow", kind="review", payload_ref=report_ref))
        # This example stops at a checkpoint. Only a future orchestrator may decide a workflow terminal state.
        state = replace(state, current_node="awaiting_workflow", artifact_refs=(task_ref, code_ref, report_ref),
                        message_refs=(task_message, code_message, review_message))
        store.save_state(state)
        print(json.dumps({"mode": "mock-fixture-checkpoint", "scenario": args.scenario,
                          "run_dir": str(store.run_dir), "status": state.status,
                          "review_verdict": report.verdict, "workflow_complete": False}, ensure_ascii=True))
        return 0
    except DomainError as exc:
        print(f"Infrastructure example failed: {exc}", file=sys.stderr)
        if store is not None and state is not None:
            try:
                store.append_event(ExecutionEvent(run_id=store.run_id, node=node, status="failed",
                                                  detail=str(exc), elapsed_ms=(perf_counter() - started) * 1000))
                store.save_state(state.transition("failed", current_node=node, error=str(exc)))
            except DomainError as persistence_error:
                print(f"Could not persist failure: {persistence_error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
