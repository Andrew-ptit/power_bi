"""The isolated preparation scenario must not run another gate's driver."""
import json
from pathlib import Path
import queue
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]


class PreparationGateTests(unittest.TestCase):
    def test_preparation_scenario_serves_its_own_guarded_driver_and_synthetic_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with (folder / "stderr.log").open("w", encoding="utf-8") as errors:
                process = subprocess.Popen(
                    [sys.executable, "tools/live_excel_gate.py", "--run-id", "prep_gate_contract",
                     "--out", str(folder), "--port", "0", "--scenario", "preparation"],
                    cwd=ROOT, stdout=subprocess.PIPE, stderr=errors, text=True,
                )
                try:
                    messages = queue.Queue()
                    reader = threading.Thread(target=lambda: messages.put(process.stdout.readline()), daemon=True)
                    reader.start()
                    line = messages.get(timeout=15)
                    self.assertTrue(line.strip(), "Preparation gate never became ready")
                    ready = json.loads(line)
                    self.assertEqual(ready["status"], "ready")
                    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
                    self.assertEqual(Path(config["driverPath"]).name, "preparation_gate_driver.js")
                    self.assertTrue(config["driverParameters"]["preparation"])
                    context = ssl.create_default_context(cafile=str(ROOT / "tools/excel_addin/.certs/localhost.pem"))
                    url = ready["baseUrl"] + "/__gate/driver.js?gateKey=" + config["gateKey"]
                    with urlopen(url, context=context, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        payload = response.read().decode("utf-8")
                    prefix = payload.split(";\n", 1)[0].split("=", 1)[1]
                    public = json.loads(prefix)
                    self.assertEqual(public["driverParameters"]["preparationOracle"]["sourceTotal"], 11)
                    self.assertNotIn("outputPath", public)
                finally:
                    process.terminate()
                    process.wait(timeout=10)
                    if process.stdout:
                        process.stdout.close()


if __name__ == "__main__":
    unittest.main()
