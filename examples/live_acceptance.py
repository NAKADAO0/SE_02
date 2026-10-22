"""Explicit opt-in external-model acceptance. Not part of routine offline tests."""

import argparse
import json
import os
from pathlib import Path
import shutil
from time import perf_counter

from se02.domain import CodeArtifact, Task
from se02.providers import HttpProvider
from se02.workflow import Workflow


class KnownDefectCoder:
    """Fixture for exercising real review and repair; does not claim model generation."""
    role = "coder"

    def run(self, context):
        return CodeArtifact(artifact_id="injected-empty-sum", version=1,
                            source="def total(values):\n    return sum(values) if values else None\n",
                            explanation="Known-defect fixture, not model-generated initial code")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, default=Path(__file__).parent / "tasks/sum.txt")
    parser.add_argument("--inject-defect", action="store_true", help="sum task only: fixture coder, real reviewer/fixer")
    parser.add_argument("--evidence", type=Path, help="explicit directory for sanitized copy of generated task artifacts")
    args = parser.parse_args()
    provider = HttpProvider(base_url=os.environ["SE02_BASE_URL"], model=os.environ["SE02_MODEL"],
                            api_key=os.environ["SE02_API_KEY"], reasoning_effort="low")
    task = Task(task_id="live-acceptance", description=args.task.read_text(encoding="utf-8"))
    started = perf_counter()
    agents = {"coder": KnownDefectCoder()} if args.inject_defect else None
    result = Workflow(provider, agents=agents).run(task)
    metadata = {"kind": "external-model-acceptance", "service_url": provider.base_url,
                "requested_model": provider.model, "reasoning_effort": "low",
                "initial_code": "known-defect-fixture" if args.inject_defect else "real-model",
                "status": result.state.status, "repair_count": result.state.repair_count,
                "run_id": result.state.run_id, "error": result.state.error,
                "elapsed_seconds": round(perf_counter() - started, 2),
                "generated_code_executed": False}
    if args.evidence is not None:
        source = Path(result.run_dir)
        if args.evidence.exists():
            raise ValueError("evidence destination already exists; choose a new directory")
        for path in source.rglob("*"):
            if path.is_file() and os.environ["SE02_API_KEY"].encode() in path.read_bytes():
                raise ValueError("credential found in candidate evidence")
        shutil.copytree(source, args.evidence)
        (args.evidence / "acceptance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
