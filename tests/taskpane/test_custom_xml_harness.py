"""Independent Custom XML codec/package oracle fixture checks; no real Office host."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is not available")
class CustomXmlIndependentHarnessTests(unittest.TestCase):
    def test_codec_host_persistence_and_evidence_contracts(self) -> None:
        harness = Path(__file__).resolve().parents[1] / "support" / "custom_xml" / "officejs"
        for name in (
            "test_codec.js", "test_static.js", "test_taskpane_fake.js",
            "test_autorun_fake.js", "test_autorun_existing_fake.js", "test_server.js",
        ):
            with self.subTest(script=name):
                result = subprocess.run(
                    ["node", str(harness / name)], capture_output=True, text=True,
                    timeout=30, check=False, cwd=harness,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(result.stdout.strip(), "harness produced no result")
