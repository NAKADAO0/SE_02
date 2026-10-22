"""Run the bounded three-agent workflow using only a fixed offline sum fixture."""

import argparse
import json
from pathlib import Path
import sys

from se02.domain import DomainError, Task
from se02.providers import MockProvider
from se02.workflow import Workflow, WorkflowConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("runs"))
    parser.add_argument("--scenario", default="repair_pass",
                        choices=("direct_pass", "repair_pass", "always_reject", "call_failure"))
    parser.add_argument("--max-repairs", type=int, choices=(0, 1, 2), default=2)
    args = parser.parse_args()
    try:
        result = Workflow(MockProvider(args.scenario), root=args.root).run(
            Task(task_id="sum-demo", description="实现 total(values)，返回列表之和，空列表返回 0。"),
            WorkflowConfig(max_repairs=args.max_repairs),
        )
    except DomainError as exc:
        print(f"Cannot start workflow: {exc}", file=sys.stderr)
        return 1
    # ASCII JSON also works in Windows consoles whose default encoding is not UTF-8.
    print(json.dumps(result.to_dict() | {"exit_code": result.exit_code, "mode": "mock-workflow"}, ensure_ascii=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
