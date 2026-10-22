"""Real local HTTP transport through the installed CLI, roles and file store."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from http_fixture import completion, http_service
from se02.providers import MockProvider, ProviderRequest


class HttpEndToEndTests(unittest.TestCase):
    def invoke(self, base, root):
        project = Path(__file__).resolve().parents[1]
        task = Path(root) / "task.txt"
        task.write_text("实现 total(values)，空列表返回 0。", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("SE02_")}
        env.update(SE02_API_KEY="local-e2e-credential", SE02_BASE_URL=base, SE02_MODEL="local-fixture")
        return subprocess.run([sys.executable, "-m", "se02", "run", "--task", str(task),
                               "--output-dir", str(Path(root) / "runs"), "--retry-delay", "0", "--json"],
                              cwd=project, env=env, capture_output=True, text=True, encoding="utf-8")

    def test_http_retry_and_three_role_repair_leave_consistent_terminal_evidence(self):
        delegate = MockProvider("repair_pass")
        count = 0

        def responder(record):
            nonlocal count
            count += 1
            if count == 1:
                return {"status": 429}
            request = ProviderRequest.from_dict(json.loads(record["body"]["messages"][1]["content"]))
            return {"body": completion(delegate.complete(request))}

        with tempfile.TemporaryDirectory() as root, http_service(responder=responder) as (base, requests):
            result = self.invoke(base, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["state"]["status"], "succeeded")
            self.assertEqual(output["state"]["repair_count"], 1)
            self.assertEqual(len(requests), 5)
            run_dir = Path(output["run_dir"])
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(output["state"], state)
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
            provider = [e for e in events if e["phase"] == "provider"]
            self.assertEqual([(e["attempt"], e["status"]) for e in provider[:4]],
                             [(1, "running"), (1, "failed"), (2, "running"), (2, "completed")])
            self.assertEqual([e["node"] for e in events if e["phase"] == "node" and e["status"] == "completed"],
                             ["coder", "review_0", "repair_1", "review_1"])
            self.assertIn("[provider] coder failed attempt=1", result.stderr)
            for path in run_dir.rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"local-e2e-credential", path.read_bytes())
            self.assertNotIn("local-e2e-credential", result.stdout + result.stderr)

    def test_auth_failure_has_one_http_attempt_and_safe_persisted_error(self):
        with tempfile.TemporaryDirectory() as root, http_service([
            {"status": 401, "body": {"error": "local-e2e-credential"}},
        ]) as (base, requests):
            result = self.invoke(base, root)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(len(requests), 1)
            output = json.loads(result.stdout)
            self.assertEqual(output["state"]["status"], "failed")
            self.assertIn("401", output["state"]["error"])
            self.assertNotIn("local-e2e-credential", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
