import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class CliTests(unittest.TestCase):
    def invoke(self, *args):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'), SE02_API_KEY='sensitive-value')
        return subprocess.run([sys.executable, '-m', 'se02', *args], capture_output=True, text=True, env=env)
    def test_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            for scenario, code in [('direct_pass', 0), ('repair_pass', 0), ('always_reject', 3), ('call_failure', 1)]:
                result = self.invoke('demo', '--scenario', scenario, '--output-dir', directory, '--json')
                self.assertEqual(result.returncode, code, result.stderr)
                body = json.loads(result.stdout)
                self.assertIn('state', body)
                self.assertNotIn('sensitive-value', result.stdout + result.stderr)
    def test_invalid_input_before_provider(self):
        result = self.invoke('run', '--task', 'missing-task-file.txt', '--json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('error', json.loads(result.stdout))
    def test_progress_stderr_quiet(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke('demo', '--output-dir', directory, '--json')
            self.assertIn('coder', result.stderr)
            result = self.invoke('demo', '--output-dir', directory, '--json', '--quiet')
            self.assertEqual(result.stderr, '')

class WorkflowObservationTests(unittest.TestCase):
    def test_callback_after_persistence_and_provider_phase(self):
        from se02.domain import Task
        from se02.providers import MockProvider
        from se02.providers.telemetry import ProviderAttempt, emit_attempt
        from se02.workflow import Workflow
        class ObservedProvider(MockProvider):
            def complete(self, request):
                emit_attempt(ProviderAttempt(attempt=1, status='running', elapsed_ms=0, detail='request'))
                value = super().complete(request)
                emit_attempt(ProviderAttempt(attempt=1, status='completed', elapsed_ms=1, detail='ok'))
                return value
        with tempfile.TemporaryDirectory() as directory:
            events = []
            def observe(event):
                lines = list(Path(directory).rglob('events.jsonl'))
                self.assertEqual(len(lines), 1)
                persisted = [json.loads(line) for line in lines[0].read_text(encoding='utf-8').splitlines()]
                self.assertEqual(persisted[-1]['phase'], event.phase)
                self.assertEqual(persisted[-1]['status'], event.status)
                events.append(event)
            result = Workflow(ObservedProvider(), root=directory, on_event=observe).run(Task(task_id='observe', description='sum'))
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(len([e for e in events if e.phase == 'provider']), 4)
            self.assertTrue(any(e.status == 'skipped' for e in events))

class CliPreflightTests(unittest.TestCase):
    def test_invalid_task_never_constructs_http(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from se02.cli import main
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'task.txt'
            path.write_text('   ', encoding='utf-8')
            with patch('se02.providers.HttpProvider') as provider, redirect_stdout(StringIO()):
                self.assertEqual(main(['run', '--task', str(path), '--json']), 2)
                provider.assert_not_called()
    def test_http_missing_settings_is_explicit(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from se02.cli import main
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'task.txt'
            path.write_text('sum values', encoding='utf-8')
            output = StringIO()
            with patch.dict(os.environ, {}, clear=True), patch('se02.providers.HttpProvider') as provider, redirect_stdout(output):
                self.assertEqual(main(['run', '--task', str(path), '--json']), 2)
                provider.assert_not_called()
            self.assertIn('http requires', output.getvalue())
    def test_unwritable_output_is_failure_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file'
            path.write_text('occupied', encoding='utf-8')
            result = CliTests().invoke('demo', '--output-dir', str(path), '--json')
            self.assertEqual(result.returncode, 1)
            self.assertIn('error', json.loads(result.stdout))
            self.assertNotIn('Traceback', result.stderr)
    def test_accidental_plaintext_key_is_rejected_without_echo(self):
        result = CliTests().invoke('demo', '--api-key', 'accidental-sensitive-key')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('accidental-sensitive-key', result.stdout + result.stderr)

class CliPersistenceDiagnosticTests(unittest.TestCase):
    def test_failed_snapshot_diagnostic_on_stderr_is_redacted(self):
        from contextlib import redirect_stdout, redirect_stderr
        from io import StringIO
        from unittest.mock import patch
        from se02.cli import main
        from se02.domain.errors import StorageError
        from se02.storage import ArtifactStore
        original = ArtifactStore.save_state
        def fail_snapshot(store, state):
            if state.status == 'failed':
                raise StorageError('cannot persist sensitive-value')
            return original(store, state)
        with tempfile.TemporaryDirectory() as directory:
            output, error = StringIO(), StringIO()
            with patch.dict(os.environ, {'SE02_API_KEY': 'sensitive-value'}), patch.object(ArtifactStore, 'save_state', fail_snapshot), redirect_stdout(output), redirect_stderr(error):
                result = main(['demo', '--scenario', 'call_failure', '--output-dir', directory, '--quiet'])
            self.assertEqual(result, 1)
            self.assertIn('failed snapshot', error.getvalue())
            self.assertIn('[REDACTED]', error.getvalue())
            self.assertNotIn('sensitive-value', output.getvalue() + error.getvalue())
