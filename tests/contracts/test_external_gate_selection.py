"""External-request tests belong to the opt-in gate, never ordinary runtime."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


class ExternalGateSelectionTests(unittest.TestCase):
    def command(self, gate, *, listing=True):
        root = Path(__file__).resolve().parents[2]
        environment = dict(os.environ)
        environment.pop("PQPC_LIVE_CODEX", None)
        command = [sys.executable, "-X", "utf8", str(root / "tools/run_checks.py"), gate]
        if listing:
            command.append("--list")
        return subprocess.run(command, cwd=root, env=environment, capture_output=True,
                              text=True, encoding="utf-8", timeout=60, check=False)

    def test_codex_gate_lists_assistant_and_problem_chain_without_requests(self):
        result = self.command("codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        cases = [line for line in result.stdout.splitlines() if line.startswith("tests.")]
        self.assertTrue(any(case.startswith("tests.runtime.test_codex_assistant_plan.") for case in cases))
        self.assertTrue(any(case.startswith("tests.runtime.test_codex_problem_chain.") for case in cases))
        self.assertTrue(all(case.startswith("tests.runtime.test_codex_") for case in cases))

    def test_runtime_gate_retains_excel_parity_and_excludes_codex_requests(self):
        result = self.command("runtime")
        self.assertEqual(result.returncode, 0, result.stderr)
        cases = [line for line in result.stdout.splitlines() if line.startswith("tests.")]
        self.assertTrue(any(case.startswith("tests.runtime.test_typed_local_parity_runtime.") for case in cases))
        self.assertTrue(all(case.startswith("tests.runtime.") for case in cases))
        self.assertFalse(any(case.startswith("tests.runtime.test_codex_") for case in cases))

    def test_codex_gate_rejects_missing_explicit_opt_in_before_running(self):
        result = self.command("codex", listing=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires explicit PQPC_LIVE_CODEX=1; no request was sent", result.stderr)
        self.assertNotIn("gate=codex run=", result.stdout)


if __name__ == "__main__":
    unittest.main()
