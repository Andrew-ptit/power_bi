"""Opt-in Excel/M comparison; never uses an already open workbook or Excel instance.

This supplies runtime test evidence only. It does not grant product responses a
persisted or machine-wide ``parityChecked`` authority.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.excel_connector import PowerShellExcelRunner
from pbip_assistant.powerquery.typed.compiler import compile_m
from pbip_assistant.powerquery.typed_local import execute_plan
from pbip_assistant.xlsx import profile_workbook
from tests.unit.test_typed_local import all_operations_fixture, plan_for, source, table


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools" / "excel_connector" / "Invoke-PQCodeM.ps1"

# Only this script's Workbooks.Add result may be saved/closed. New-Object creates
# an independent automation instance; GetActiveObject is deliberately absent.
CREATE_FIXTURE = r'''
param([string]$RequestPath)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ParityNativeMethods {
 [DllImport("user32.dll")]
 public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@
$excel = $null
$excelOwned = $false
$workbook = $null
$stage = "read-fixture-request"
$exitCode = 0
try {
 $request = [IO.File]::ReadAllText($RequestPath) | ConvertFrom-Json
 $stage = "create-excel"
 [Console]::Error.WriteLine("[parity] $stage")
 $baselineProcesses = @([Diagnostics.Process]::GetProcessesByName("EXCEL"))
 $baselinePids = @($baselineProcesses | ForEach-Object { $_.Id })
 foreach ($baselineProcess in $baselineProcesses) { $baselineProcess.Dispose() }
 $creationFloorFileTime = [DateTime]::UtcNow.ToFileTimeUtc()
 $excel = New-Object -ComObject Excel.Application
 [uint32]$ownedPid = 0
 [void][ParityNativeMethods]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd, [ref]$ownedPid)
 if ($ownedPid -le 0 -or $baselinePids -contains [int]$ownedPid) { throw "Excel process ownership is unproven" }
 $ownedProcess = Get-Process -Id ([int]$ownedPid) -ErrorAction Stop
 try {
  $created = $ownedProcess.StartTime.ToFileTimeUtc()
  if ($ownedProcess.ProcessName -ine "EXCEL" -or $created -lt $creationFloorFileTime) { throw "Excel process identity is unproven" }
  $proof = @{excelOwned=$true;excelPid=[int]$ownedPid;excelCreationFileTime=$created.ToString([Globalization.CultureInfo]::InvariantCulture)}
 } finally { $ownedProcess.Dispose() }
 $excelOwned = $true
 [IO.File]::WriteAllText([string]$request.statePath, ($proof | ConvertTo-Json -Compress))
 $excel.Visible = $false
 $excel.DisplayAlerts = $false
 $excel.AskToUpdateLinks = $false
 $excel.EnableEvents = $false
 $excel.AutomationSecurity = 3
 $stage = "create-synthetic-workbook"
 [Console]::Error.WriteLine("[parity] $stage")
 $workbook = $excel.Workbooks.Add(-4167)
 # R/r is reserved by Excel. Assignment can silently normalize DisplayName
 # to r_ instead of raising, so choose an unambiguous fixture alias up front.
 $rightObjectName = "ParityRight"
 $reservedNameRejected = $false
 for ($index = 0; $index -lt $request.tables.Count; $index++) {
  if ($index -eq 0) { $sheet = $workbook.Worksheets.Item(1) }
  else { $sheet = $workbook.Worksheets.Add() }
  $sheet.Name = "ParitySource" + $index
  $data = $request.tables[$index]
  for ($col = 0; $col -lt $request.headers.Count; $col++) {
   $sheet.Cells.Item(1, $col + 1).Value2 = [string]$request.headers[$col]
  }
  for ($row = 0; $row -lt $data.rows.Count; $row++) {
   for ($col = 0; $col -lt $request.headers.Count; $col++) {
    $value = $data.rows[$row][$col]
    if ($value -is [string]) { $sheet.Cells.Item($row + 2, $col + 1).Value2 = [string]$value }
    elseif ($null -ne $value) { $sheet.Cells.Item($row + 2, $col + 1).Value2 = [double]$value }
   }
  }
  $range = $sheet.Range($sheet.Cells.Item(1,1), $sheet.Cells.Item($data.rows.Count + 1,$request.headers.Count))
  $table = $sheet.ListObjects.Add(1,$range,$null,1)
  $stage = "name-synthetic-table"
  $objectName = if ($index -eq 1 -and [string]$data.sourceId -eq "r") { $rightObjectName } else { [string]$data.sourceId }
  $table.Name = $objectName
  if ([string]$table.DisplayName -ne $objectName) { throw "Synthetic table alias was normalized unexpectedly" }
 }
 $stage = "save-synthetic-fixture"
 [Console]::Error.WriteLine("[parity] $stage")
 $workbook.SaveAs([string]$request.workbookPath,51)
 $response = @{ok=$true;rightObjectName=$rightObjectName;reservedNameRejected=$reservedNameRejected}
}
catch {
 $exitCode = 1
 $response = @{ok=$false;code="PARITY_FIXTURE_FAILED";stage=$stage;hresult=$_.Exception.HResult}
}
finally {
 if ($excelOwned -and $null -ne $workbook) { try { $workbook.Close($false) } catch {} }
 if ($excelOwned -and $null -ne $excel) { try { $excel.Quit() } catch {} }
 $table=$null; $range=$null; $sheet=$null; $workbook=$null; $excel=$null
 [GC]::Collect()
 [GC]::WaitForPendingFinalizers()
 [GC]::Collect()
 [GC]::WaitForPendingFinalizers()
}
$response | ConvertTo-Json -Compress
exit $exitCode
'''


def _create_fixture(folder: Path, tables: list[dict]) -> tuple[Path, dict]:
    """Build one synthetic workbook, returning safe binding/stage metadata."""
    script = folder / "create-fixture.ps1"
    script.write_text(CREATE_FIXTURE, encoding="utf-8")
    target, state = folder / "synthetic.xlsx", folder / "fixture-state.json"
    request = folder / "fixture-request.json"
    request.write_text(json.dumps({
        "workbookPath": str(target), "statePath": str(state),
        "headers": ["Key", "Amount", "Note"], "tables": tables,
    }), encoding="utf-8")
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(script), "-RequestPath", str(request)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        PowerShellExcelRunner._terminate_created_excel(state)
        traces = (exc.stderr or b"")
        if isinstance(traces, bytes):
            traces = traces.decode("utf-8", errors="replace")
        stages = [line for line in traces.splitlines() if line.startswith("[parity]")]
        stage = stages[-1] if stages else "no-stage"
        raise AssertionError(f"Blocked: PARITY_FIXTURE_TIMEOUT; {stage}") from None
    try:
        result = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        PowerShellExcelRunner._terminate_created_excel(state)
        raise AssertionError("Blocked: PARITY_FIXTURE_PROTOCOL") from None
    if completed.returncode or not result.get("ok"):
        raise AssertionError(
            f"Blocked: {result.get('code')}; stage={result.get('stage')}; "
            f"HRESULT={result.get('hresult')}"
        )
    return target, result


def _source_fingerprints(path: Path) -> dict[str, str]:
    profile = profile_workbook(path, include_preview=True, preview_limit=20)
    fingerprints = {}
    for sheet in profile["sheets"]:
        if not sheet["name"].startswith("ParitySource"):
            continue
        preview = sheet["preview"]
        if preview["truncated"]:
            raise AssertionError("Synthetic source fingerprint must cover every row")
        canonical = json.dumps(
            {"columns": preview["columns"], "rows": preview["rows"]},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        fingerprints[sheet["name"]] = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    if len(fingerprints) != 2:
        raise AssertionError("Both complete synthetic source sheets must be fingerprinted")
    return fingerprints


def _numeric_rows(rows: list[list]) -> list[list[str]]:
    """Only the final numeric Total column is normalized, never arbitrary text."""
    return [[format(Decimal(str(value)).normalize(), "f") for value in row] for row in rows]


@unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell is unavailable")
class TypedLocalRuntimeParityTests(unittest.TestCase):
    def test_all_six_joins_match_excel_m_with_duplicates_unmatched_and_null_keys(self) -> None:
        """Preserve multiplicity/null semantics without assuming M row ordering."""
        started = time.monotonic()
        tables = [
            table([["A", 10, "L1"], ["A", 20, "L2"], ["B", 30, "LB"], [None, 40, "LN"]]),
            table([["A", 100, "x"], ["A", 200, "y"], ["C", 300, "z"], [None, 400, "n"]], "r"),
        ]
        # Handwritten rows, independent of both implementations. Two A rows on
        # each side produce four matches; the null key matches the null key.
        a_matches = [
            ["A", 10, "L1", "A", 100, "x"],
            ["A", 10, "L1", "A", 200, "y"],
            ["A", 20, "L2", "A", 100, "x"],
            ["A", 20, "L2", "A", 200, "y"],
        ]
        null_match = [None, 40, "LN", None, 400, "n"]
        left_only = ["B", 30, "LB", None, None, None]
        right_only = [None, None, None, "C", 300, "z"]
        expected = {
            "inner": a_matches + [null_match],
            "leftOuter": a_matches + [left_only, null_match],
            "rightOuter": a_matches + [null_match, right_only],
            "fullOuter": a_matches + [left_only, null_match, right_only],
            "leftAnti": [left_only],
            "rightAnti": [right_only],
        }
        columns = ["Key", "Amount", "Note", "RightKey", "RightAmount", "RightNote"]

        def canonical_rows(rows: list[list]) -> list[tuple]:
            # Normalize only the declared numeric columns. Null/text retain
            # their types, and Counter preserves duplicate row multiplicity.
            result = []
            for row in rows:
                self.assertEqual(len(row), len(columns))
                values = list(row)
                for index in (1, 4):
                    if values[index] is not None:
                        self.assertNotIsInstance(values[index], bool)
                        values[index] = format(Decimal(str(values[index])).normalize(), "f")
                result.append(tuple(values))
            return result

        with tempfile.TemporaryDirectory(prefix="pq-six-join-parity-") as directory:
            target, binding = _create_fixture(Path(directory), tables)
            before = _source_fingerprints(target)
            metrics = []
            for kind, expected_rows in expected.items():
                with self.subTest(joinKind=kind):
                    sources = [source(), source("r", kind="usedRange")]
                    sources[1]["objectName"] = binding["rightObjectName"]
                    plan = plan_for([
                        ("mergeTables", {
                            "keyPairs": [{"leftColumn": "Key", "rightColumn": "Key"}],
                            "joinKind": kind, "nestedColumnName": "Matches",
                        }, ["t", "r"]),
                        ("expandTableColumn", {"nestedColumn": "Matches", "columns": [
                            {"column": "Key", "newName": "RightKey"},
                            {"column": "Amount", "newName": "RightAmount"},
                            {"column": "Note", "newName": "RightNote"},
                        ]}),
                    ], sources)
                    local = execute_plan(plan, tables)
                    self.assertEqual([column["name"] for column in local["columns"]], columns)
                    self.assertEqual(local["rowCount"], len(expected_rows))
                    # Local ordering is contractual and checked separately;
                    # M NestedJoin does not promise the same row ordering.
                    self.assertEqual(canonical_rows(local["rows"]), canonical_rows(expected_rows))
                    m_code = compile_m(plan)
                    runtime_started = time.monotonic()
                    try:
                        actual = PowerShellExcelRunner(HELPER, timeout_seconds=90).apply({
                            "version": 1, "workbookPath": str(target),
                            "source": {"kind": "table", "sheet": "ParitySource0", "name": "t"},
                            "sources": [
                                {"kind": "table", "sheet": "ParitySource0", "name": "t"},
                                {"kind": "table", "sheet": "ParitySource1", "name": binding["rightObjectName"]},
                            ], "mCode": m_code,
                        })
                    except InputError as exc:
                        self.fail(f"Excel/M joinKind={kind}; code={exc.code}; {exc}")
                    finally:
                        self.assertEqual(_source_fingerprints(target), before)
                    self.assertEqual(actual["columns"], columns)
                    self.assertEqual((actual["resultRows"], actual["resultColumns"]), (len(expected_rows), 6))
                    self.assertEqual(len(actual["rows"]), actual["resultRows"], "Runtime preview must contain every oracle row")
                    self.assertEqual(Counter(canonical_rows(actual["rows"])), Counter(canonical_rows(expected_rows)))
                    self.assertEqual(Counter(canonical_rows(actual["rows"])), Counter(canonical_rows(local["rows"])))
                    metrics.append({
                        "joinKind": kind, "resultDimensions": [actual["resultRows"], actual["resultColumns"]],
                        "elapsedSeconds": round(time.monotonic() - runtime_started, 3),
                        "mSha256": hashlib.sha256(m_code.encode()).hexdigest(),
                    })
            self.assertEqual(len(metrics), 6)
            print(json.dumps({
                "layer": "Excel COM + Power Query M six-join parity", "status": "Pass",
                "joins": metrics, "nullKeysMatch": True, "duplicateMultiplicityVerified": True,
                "sourceFingerprintsBefore": before, "sourceFingerprintsAfter": _source_fingerprints(target),
                "elapsedSeconds": round(time.monotonic() - started, 3),
            }, sort_keys=True))

    def test_python_executor_matches_excel_m_for_all_15_operations(self) -> None:
        started = time.monotonic()
        plan, tables = all_operations_fixture()
        self.assertEqual(len({step["operation"]["type"] for step in plan["steps"]}), 15)
        with tempfile.TemporaryDirectory(prefix="pq-typed-local-parity-") as directory:
            target, binding = _create_fixture(Path(directory), tables)
            # A usedRange source compiles to Excel.CurrentWorkbook's named object;
            # expose that object as a real Excel Table in the synthetic workbook.
            # Use the explicit fixture alias for Excel's reserved R/r name.
            plan = deepcopy(plan)
            plan["sources"][1]["objectName"] = binding["rightObjectName"]
            python_result = execute_plan(plan, tables)
            self.assertEqual(python_result["rows"], [["18"]])  # Hand-computed oracle.
            self.assertEqual(python_result["columns"], [{"name": "Total", "type": "number"}])
            m_code = compile_m(plan)
            before = _source_fingerprints(target)
            try:
                actual = PowerShellExcelRunner(HELPER, timeout_seconds=90).apply({
                    "version": 1, "workbookPath": str(target),
                    "source": {"kind": "table", "sheet": "ParitySource0", "name": "t"},
                    "sources": [
                        {"kind": "table", "sheet": "ParitySource0", "name": "t"},
                        {"kind": "table", "sheet": "ParitySource1", "name": binding["rightObjectName"]},
                    ], "mCode": m_code,
                })
            except InputError as exc:
                self.fail(f"Blocked: Excel/M runtime code={exc.code}; {exc}")
            self.assertEqual(actual["columns"], [column["name"] for column in python_result["columns"]])
            self.assertEqual((actual["resultRows"], actual["resultColumns"]), (1, 1))
            self.assertEqual(_numeric_rows(actual["rows"]), [["18"]])
            self.assertEqual(_numeric_rows(actual["rows"]), _numeric_rows(python_result["rows"]))
            after = _source_fingerprints(target)
            self.assertEqual(after, before)
            print(json.dumps({
                "layer": "Excel COM + Power Query M parity", "status": "Pass",
                "operations": 15, "resultDimensions": [1, 1],
                "elapsedSeconds": round(time.monotonic() - started, 2),
                "reservedRightNameRejected": binding["reservedNameRejected"],
                "sourceFingerprintsBefore": before, "sourceFingerprintsAfter": after,
                "mSha256": hashlib.sha256(m_code.encode()).hexdigest(),
            }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
