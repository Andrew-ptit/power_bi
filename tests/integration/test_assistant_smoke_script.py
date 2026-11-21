"""Keep the synthetic Assistant smoke entry point parseable on supported shells."""

from pathlib import Path
import shutil
import subprocess
import unittest


class AssistantSmokeScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell.exe"), "no PowerShell")
    def test_assistant_flow_smoke_script_parses(self):
        script = Path(__file__).resolve().parents[2] / "tools" / "assistant_flow_smoke.ps1"
        command = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('"
                   + str(script).replace("'", "''")
                   + "',[ref]$null,[ref]$e); if($e){ $e | ForEach-Object {$_.Message}; exit 1 }")
        shell = shutil.which("pwsh") or shutil.which("powershell.exe")
        result = subprocess.run([shell, "-NoProfile", "-Command", command],
                                capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
