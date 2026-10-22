"""Run the documented example as a user would, checking persisted results."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ExampleTests(unittest.TestCase):
    def test_fixture_staging_leaves_explicit_checkpoint_not_workflow_success(self):
        project = Path(__file__).resolve().parents[1]
        for scenario, verdict in (("direct_pass", "pass"), ("repair_pass", "fail"), ("always_reject", "fail")):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as root:
                result = subprocess.run([sys.executable, str(project / "examples/infrastructure_demo.py"),
                                         "--root", root, "--scenario", scenario],
                                        cwd=project, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
                run_dir = next(Path(root).iterdir())
                state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
                report = json.loads((run_dir / "reviews/review_0.json").read_text(encoding="utf-8"))
                self.assertEqual(report["verdict"], verdict)
                self.assertEqual(state["status"], "running")
                self.assertIsNone(state["ended_at"])
                self.assertEqual(len((run_dir / "events.jsonl").read_text().splitlines()), 4)
                self.assertEqual(len((run_dir / "messages.jsonl").read_text().splitlines()), 3)

    def test_fixture_failure_is_persisted_and_returns_nonzero(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, str(project / "examples/infrastructure_demo.py"),
                                     "--root", root, "--scenario", "call_failure"],
                                    cwd=project, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 1, result.stderr)
            state = json.loads((next(Path(root).iterdir()) / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "failed")
            self.assertIn("mock call failure", state["error"])


if __name__ == "__main__":
    unittest.main()
