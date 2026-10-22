import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class WorkflowExampleTests(unittest.TestCase):
    def test_four_scenarios_return_real_terminal_states_and_exit_codes(self):
        project = Path(__file__).resolve().parents[1]
        for scenario, status, code, repairs in (
            ("direct_pass", "succeeded", 0, 0),
            ("repair_pass", "succeeded", 0, 1),
            ("always_reject", "needs_attention", 3, 2),
            ("call_failure", "failed", 1, 0),
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as root:
                result = subprocess.run([sys.executable, str(project / "examples/workflow_demo.py"),
                                         "--root", root, "--scenario", scenario], cwd=project,
                                        capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, code, result.stderr)
                summary = json.loads(result.stdout)
                self.assertEqual(summary["state"]["status"], status)
                self.assertEqual(summary["state"]["repair_count"], repairs)
                state = json.loads((Path(summary["run_dir"]) / "state.json").read_text(encoding="utf-8"))
                self.assertEqual(summary["state"], state)

    def test_invalid_repair_limit_is_a_usage_error(self):
        project = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(project / "examples/workflow_demo.py"),
                                 "--max-repairs", "3"], cwd=project, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--max-repairs", result.stderr)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
