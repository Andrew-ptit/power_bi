"""No real process signals: validate timeout cleanup's process-identity proof."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from pbip_assistant.excel import connector


class ExcelProcessOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name, "state.json")
        self.handle = object()
        self.api = Mock()
        self.api.open.return_value = self.handle
        self.api.creation_time.return_value = 134064000000000000
        self.api.image_path.return_value = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"
        self.api.terminate.return_value = True
        self.api.wait.return_value = 0
        self.factory = self.enterContext(patch.object(connector, "_WindowsProcessApi", return_value=self.api, create=True))
        # A regression must fail in the mock, never signal a real/user PID.
        self.enterContext(patch.object(connector.os, "kill", side_effect=AssertionError("PID-only termination is forbidden")))

    def write(self, **overrides):
        proof = {"excelOwned": True, "excelPid": 4242, "excelCreationFileTime": "134064000000000000"}
        proof.update(overrides)
        self.state.write_text(json.dumps(proof), encoding="utf-8")

    def clean(self):
        connector.PowerShellExcelRunner._terminate_created_excel(self.state)

    def test_missing_ownership_or_creation_proof_never_opens_or_kills(self):
        for proof in ({"excelPid": 4242}, {"excelOwned": True, "excelPid": 4242},
                      {"excelOwned": False, "excelPid": 4242, "excelCreationFileTime": "134064000000000000"}):
            with self.subTest(proof=proof):
                self.state.write_text(json.dumps(proof), encoding="utf-8")
                self.clean()
        self.factory.assert_not_called()

    def test_malformed_state_and_identifier_fail_closed(self):
        for value in ("not-json", "[]", "null"):
            self.state.write_text(value, encoding="utf-8")
            self.clean()
        for overrides in ({"excelPid": True}, {"excelPid": 0}, {"excelPid": -2},
                          {"excelCreationFileTime": "-1"}, {"excelCreationFileTime": "NaN"},
                          {"excelCreationFileTime": "18446744073709551616"}):
            with self.subTest(overrides=overrides):
                self.write(**overrides)
                self.clean()
        self.factory.assert_not_called()

    def test_reused_pid_creation_mismatch_never_terminates(self):
        self.write()
        self.api.creation_time.return_value += 1
        self.clean()
        self.api.terminate.assert_not_called()
        self.api.close.assert_called_once_with(self.handle)

    def test_wrong_process_image_never_terminates(self):
        self.write()
        self.api.image_path.return_value = r"C:\Windows\System32\notepad.exe"
        self.clean()
        self.api.terminate.assert_not_called()
        self.api.close.assert_called_once_with(self.handle)

    def test_inaccessible_identity_never_terminates_and_closes_handle(self):
        self.write()
        self.api.creation_time.side_effect = OSError("Access denied")
        self.clean()
        self.api.terminate.assert_not_called()
        self.api.close.assert_called_once_with(self.handle)

    def test_exited_before_open_never_terminates_or_closes_invalid_handle(self):
        self.write()
        self.api.open.side_effect = OSError("Process already exited")
        self.clean()
        self.api.terminate.assert_not_called()
        self.api.close.assert_not_called()

    def test_exit_racing_termination_still_closes_the_same_handle(self):
        self.write()
        self.api.terminate.side_effect = OSError("Process exited after identity query")
        self.clean()
        self.api.wait.assert_not_called()
        self.api.close.assert_called_once_with(self.handle)

    def test_proven_owned_excel_terminates_and_waits_on_the_queried_handle(self):
        self.write()
        self.clean()
        self.assertEqual(self.api.mock_calls, [call.open(4242), call.creation_time(self.handle),
            call.image_path(self.handle), call.terminate(self.handle), call.wait(self.handle, 2000), call.close(self.handle)])

    def test_bounded_wait_timeout_never_falls_back_to_a_second_pid_kill(self):
        self.write()
        self.api.wait.return_value = 258  # WAIT_TIMEOUT
        self.clean()
        self.api.terminate.assert_called_once_with(self.handle)
        self.api.wait.assert_called_once_with(self.handle, 2000)
        self.api.close.assert_called_once_with(self.handle)


class ExcelHelperOwnershipTests(unittest.TestCase):
    def helper_paths(self):
        directory = Path(__file__).resolve().parents[2] / "tools" / "excel_connector"
        return [directory / "Invoke-PQCodeM.ps1", directory / "Invoke-ExcelConnector.ps1"]

    def test_existing_excel_is_excluded_before_app_mutations_and_finally_quit(self):
        for path in self.helper_paths():
            with self.subTest(helper=path.name):
                text = path.read_text(encoding="utf-8-sig")
                baseline = text.index("$baselineExcelProcesses = @([Diagnostics.Process]::GetProcessesByName")
                created = text.index("$excel = New-Object -ComObject Excel.Application")
                proof = text.index("$ownershipProof = Get-NewExcelProcessProof")
                owned = text.index("$excelOwned = $true", proof)
                self.assertLess(baseline, created)
                self.assertLess(created, proof)
                self.assertLess(proof, owned)
                self.assertLess(owned, text.index("$excel.Visible = $false"))
                self.assertLess(owned, text.index("$excel.AutomationSecurity = 3"))
                self.assertLess(owned, text.index("$excel.Workbooks.Open"))
                cleanup = text[text.rindex("\nfinally {"):]
                self.assertIn("if ($excelOwned -and $null -ne $excel)", cleanup)
                self.assertIn("if ($excelOwned -and $null -ne $workbook)", cleanup)
                self.assertNotIn("Stop-Process", text)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell is unavailable")
    def test_helper_proof_rejects_baseline_old_wrong_and_inaccessible_process_without_com(self):
        for path in self.helper_paths():
            with self.subTest(helper=path.name):
                # Parse and invoke only the pure ownership function. Get-Process
                # is a lexical test stub; New-Object/COM/Quit never execute.
                script = r'''
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile('__HELPER__', [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'PowerShell helper syntax errors' }
$function = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-NewExcelProcessProof' }, $true)
if ($null -eq $function) { throw 'Missing ownership proof function' }
. ([scriptblock]::Create($function.Extent.Text))
function Fail([string]$Code, [string]$Detail) { throw "$Code|$Detail" }
function Throw-ConnectorError([string]$Code, [string]$Detail) { throw "$Code|$Detail" }
$script:queries = 0; $script:disposed = 0; $script:image = 'EXCEL'; $script:inaccessible = $false
$script:created = [DateTime]::FromFileTimeUtc(134064000000000000)
function Get-Process {
    param([int]$Id, $ErrorAction)
    $script:queries++
    if ($script:inaccessible) { throw 'Access denied (synthetic)' }
    $process = [pscustomobject]@{ ProcessName = $script:image; StartTime = $script:created }
    Add-Member -InputObject $process -MemberType ScriptMethod -Name Dispose -Value { $script:disposed++ }
    return $process
}
function Assert-Rejected([scriptblock]$Action) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Unowned process accepted' }
}
Assert-Rejected { Get-NewExcelProcessProof -ExcelProcessId 4242 -BaselineExcelPids @(4242) -CreationFloorFileTime 134064000000000000 }
Assert-Rejected { Get-NewExcelProcessProof -ExcelProcessId 0 -BaselineExcelPids @() -CreationFloorFileTime 134064000000000000 }
if ($script:queries -ne 0) { throw 'Baseline/invalid PID must be rejected before inspection' }
$script:image = 'NOTEPAD'
Assert-Rejected { Get-NewExcelProcessProof -ExcelProcessId 4242 -BaselineExcelPids @(17) -CreationFloorFileTime 134064000000000000 }
$script:image = 'EXCEL'
Assert-Rejected { Get-NewExcelProcessProof -ExcelProcessId 4242 -BaselineExcelPids @(17) -CreationFloorFileTime 134064000000000001 }
$proof = Get-NewExcelProcessProof -ExcelProcessId 4242 -BaselineExcelPids @(17) -CreationFloorFileTime 134064000000000000
if ($proof.excelOwned -ne $true -or $proof.excelPid -ne 4242 -or $proof.excelCreationFileTime -cne '134064000000000000') { throw 'Ownership proof changed identity or precision' }
if ($script:disposed -ne 3) { throw 'Process query objects were not disposed' }
$script:inaccessible = $true
Assert-Rejected { Get-NewExcelProcessProof -ExcelProcessId 4242 -BaselineExcelPids @() -CreationFloorFileTime 134064000000000000 }
Write-Output 'ownership proof tests passed without COM'
'''.replace("__HELPER__", str(path).replace("'", "''"))
                result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                    capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("passed without COM", result.stdout)


if __name__ == "__main__":
    unittest.main()
