"""Command line delivery for the persisted three-role workflow."""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
from se02.config import load_config
from se02.domain import Task, ValidationError
from se02.domain.errors import DomainError
from se02.providers import MockProvider
from se02.workflow import Workflow, WorkflowConfig

DEMO_TASK = 'Implement total(values) returning the sum of numbers; empty input must return 0.'

class CliParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes rejected argument values, including accidental secrets.
        self.exit(2, "se02: invalid or missing command-line arguments; use --help\n")

def parser():
    root = CliParser(prog='se02')
    commands = root.add_subparsers(dest='command', required=True)
    for command in ('run', 'demo'):
        sub = commands.add_parser(command)
        if command == 'run':
            sub.add_argument('--task', required=True, help='UTF-8 task description file')
        sub.add_argument('--config', help='TOML configuration file')
        sub.add_argument('--provider', choices=('http', 'mock'), default='mock' if command == 'demo' else None)
        sub.add_argument('--scenario', choices=('direct_pass', 'repair_pass', 'always_reject', 'call_failure'), default='direct_pass')
        sub.add_argument('--base-url')
        sub.add_argument('--model')
        sub.add_argument('--timeout', type=float)
        sub.add_argument('--max-retries', type=int)
        sub.add_argument('--retry-delay', type=float)
        sub.add_argument('--max-repairs', type=int)
        sub.add_argument('--output-dir')
        sub.add_argument('--json', action='store_true')
        sub.add_argument('--quiet', action='store_true')
    return root

def main(argv=None):
    args = parser().parse_args(argv)
    secret = os.environ.get('SE02_API_KEY')
    def safe(value):
        rendered = str(value)
        return rendered.replace(secret, '[REDACTED]') if secret else rendered
    try:
        if args.command == 'demo':
            description = DEMO_TASK
        else:
            try:
                description = Path(args.task).read_text(encoding='utf-8')
            except (OSError, UnicodeError):
                raise ValidationError('task must be a readable UTF-8 file') from None
        task = Task(task_id='task-' + uuid4().hex, description=description)
        names = ('provider', 'base_url', 'model', 'timeout', 'max_retries', 'retry_delay', 'max_repairs', 'output_dir')
        config = load_config({name: getattr(args, name) for name in names}, config_path=args.config)
        if config.provider == 'http':
            if not config.base_url or not config.model or not config.api_key:
                raise ValidationError('http requires base_url, model and SE02_API_KEY')
            from se02.providers import HttpProvider
            provider = HttpProvider(base_url=config.base_url, model=config.model, api_key=config.api_key, timeout=config.timeout,
                                    max_retries=config.max_retries, retry_delay=config.retry_delay)
        else:
            provider = MockProvider(args.scenario)
        def progress(event):
            if not args.quiet:
                print(safe(f'[{event.phase}] {event.node} {event.status} attempt={event.attempt}'), file=sys.stderr)
        result = Workflow(provider, root=config.output_dir, on_event=progress).run(task, WorkflowConfig(max_repairs=config.max_repairs))
        if args.json:
            print(safe(json.dumps(result.to_dict(), ensure_ascii=False)))
        else:
            print(safe(f'Status: {result.state.status}\nRun directory: {result.run_dir}\nRepairs: {result.state.repair_count}'))
            for label, reference in (('Final source', result.final_code_ref), ('Final review', result.final_review_ref)):
                if reference:
                    path = Path(result.run_dir) / reference
                    print(safe(f'{label}: {path}\n{path.read_text(encoding="utf-8")}'))
            if result.state.error:
                print(safe(result.state.error), file=sys.stderr)
            for diagnostic in result.persistence_errors:
                print(safe(f"Persistence diagnostic: {diagnostic}"), file=sys.stderr)
        return result.exit_code
    except (DomainError, OSError, ValueError) as exc:
        message = safe(exc)
        if args.json:
            print(json.dumps({'error': message}, ensure_ascii=False))
        else:
            print('Error: ' + message, file=sys.stderr)
        return 2 if isinstance(exc, (ValidationError, ValueError)) else 1

if __name__ == '__main__':
    raise SystemExit(main())
