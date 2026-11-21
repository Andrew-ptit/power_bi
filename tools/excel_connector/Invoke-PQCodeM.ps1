param(
    [Parameter(Mandatory = $true)]
    [string]$RequestPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Fail([string]$Code, [string]$Detail) { throw "$Code|$Detail" }
function Trace([string]$Stage) {
    $script:Stage = $Stage
    [Console]::Error.WriteLine("[pq] $Stage")
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class PQNativeMethods {
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@

function Get-NewExcelProcessProof {
    param([int]$ExcelProcessId, [int[]]$BaselineExcelPids, [long]$CreationFloorFileTime)
    if ($ExcelProcessId -le 0 -or $BaselineExcelPids -contains $ExcelProcessId) {
        Fail "EXCEL_INSTANCE_NOT_OWNED" "Excel application ownership is unproven; existing instances remain untouched."
    }
    $excelProcess = Get-Process -Id $ExcelProcessId -ErrorAction Stop
    try {
        $created = $excelProcess.StartTime.ToFileTimeUtc()
        if ($excelProcess.ProcessName -ine "EXCEL" -or $created -lt $CreationFloorFileTime) {
            Fail "EXCEL_INSTANCE_NOT_OWNED" "Excel process identity or creation time did not prove a new owned instance."
        }
        return [ordered]@{ excelOwned = $true; excelPid = $ExcelProcessId; excelCreationFileTime = $created.ToString([Globalization.CultureInfo]::InvariantCulture) }
    }
    finally { $excelProcess.Dispose() }
}

$excel = $null
$excelOwned = $false
$workbook = $null
$staticWorkbook = $null
$response = $null
$exitCode = 0
try {
    Trace "read-request"
    $requestFile = (Resolve-Path -LiteralPath $RequestPath).Path
    $request = Get-Content -LiteralPath $requestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($request.version -ne 1 -or -not $request.workbookPath -or -not $request.mCode -or -not $request.source) {
        Fail "PQ_REQUEST_INVALID" "Missing required request fields."
    }
    $workbookPath = [IO.Path]::GetFullPath([string]$request.workbookPath)
    if ([IO.Path]::GetExtension($workbookPath).ToLowerInvariant() -ne ".xlsx" -or -not [IO.File]::Exists($workbookPath)) {
        Fail "PQ_WORKBOOK_INVALID" "Target must be an existing temporary .xlsx copy."
    }
    if ([string]$request.mCode -match '^\s*$' -or ([string]$request.mCode).Length -gt 16000) {
        Fail "PQ_CODE_INVALID" "M code is empty or exceeds 16000 characters."
    }
    $resultWorkbookPath = $null
    if ($request.resultWorkbookPath) {
        $resultWorkbookPath = [IO.Path]::GetFullPath([string]$request.resultWorkbookPath)
        if ([IO.Path]::GetExtension($resultWorkbookPath).ToLowerInvariant() -ne ".xlsx" -or
            [IO.Path]::GetDirectoryName($resultWorkbookPath) -ne [IO.Path]::GetDirectoryName($workbookPath) -or
            $resultWorkbookPath -eq $workbookPath -or [IO.File]::Exists($resultWorkbookPath)) {
            Fail "PQ_REQUEST_INVALID" "Result workbook must be a new .xlsx beside the temporary copy."
        }
    }

    Trace "create-excel"
    $baselineExcelProcesses = @([Diagnostics.Process]::GetProcessesByName("EXCEL"))
    $baselineExcelPids = @($baselineExcelProcesses | ForEach-Object { $_.Id })
    foreach ($baselineProcess in $baselineExcelProcesses) { $baselineProcess.Dispose() }
    $creationFloorFileTime = [DateTime]::UtcNow.ToFileTimeUtc()
    $excel = New-Object -ComObject Excel.Application
    [uint32]$excelPid = 0
    [void][PQNativeMethods]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd, [ref]$excelPid)
    $ownershipProof = Get-NewExcelProcessProof -ExcelProcessId ([int]$excelPid) -BaselineExcelPids $baselineExcelPids -CreationFloorFileTime $creationFloorFileTime
    $excelOwned = $true
    if ($request.statePath) {
        $statePath = [IO.Path]::GetFullPath([string]$request.statePath)
        if ([IO.Path]::GetDirectoryName($statePath) -ne [IO.Path]::GetDirectoryName($requestFile)) {
            Fail "PQ_REQUEST_INVALID" "statePath must stay beside request."
        }
        $ownershipProof | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath -Encoding UTF8
    }
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    Trace "open-copy"
    $workbook = $excel.Workbooks.Open($workbookPath, 0, $false)

    Trace "resolve-source"
    $source = $request.source
    $sources = @($source)
    if ($request.PSObject.Properties.Name -contains "sources") {
        $sources = @($request.sources)
        if ($sources.Count -lt 1 -or $sources.Count -gt 20) {
            Fail "PQ_REQUEST_INVALID" "Typed preview requires 1-20 workbook-local sources."
        }
    }
    $inputRows = 0
    for ($sourceIndex = 0; $sourceIndex -lt $sources.Count; $sourceIndex++) {
        $currentSource = $sources[$sourceIndex]
        if ($currentSource.kind -eq "table") {
            $found = $false
            foreach ($sheet in @($workbook.Worksheets)) {
                if ($sheet.Name -ne [string]$currentSource.sheet) { continue }
                foreach ($table in @($sheet.ListObjects)) {
                    if ($table.Name -eq [string]$currentSource.name) {
                        if ($sourceIndex -eq 0) { $inputRows = [int]$table.ListRows.Count }
                        $found = $true
                        break
                    }
                }
                if ($found) { break }
            }
            if (-not $found) { Fail "PQ_SOURCE_MISSING" "Selected Excel Table is missing from the copy." }
        }
        elseif ($currentSource.kind -eq "sheet") {
            $sheet = $null
            try { $sheet = $workbook.Worksheets.Item([string]$currentSource.sheet) } catch {}
            if ($null -eq $sheet) { Fail "PQ_SOURCE_MISSING" "Selected sheet is missing from the copy." }
            $alias = if ($currentSource.alias) { [string]$currentSource.alias } else { "PQ_Input" }
            if ($alias -notmatch '^PQ_Input(?:_[a-f0-9]{8})?$') {
                Fail "PQ_REQUEST_INVALID" "Used-range alias is invalid."
            }
            foreach ($candidate in @($workbook.Worksheets)) {
                foreach ($table in @($candidate.ListObjects)) {
                    if ($table.Name -eq $alias) { Fail "PQ_SOURCE_CONFLICT" "A temporary input table name already exists." }
                }
            }
            $used = $sheet.UsedRange
            $headerRow = [int]$currentSource.headerRow
            $lastRow = [int]$used.Row + [int]$used.Rows.Count - 1
            $firstColumn = [int]$used.Column
            $lastColumn = $firstColumn + [int]$used.Columns.Count - 1
            if ($headerRow -lt [int]$used.Row -or $headerRow -gt $lastRow) {
                Fail "PQ_SOURCE_MISSING" "Header row is outside the used range."
            }
            $tableRange = $sheet.Range($sheet.Cells.Item($headerRow, $firstColumn), $sheet.Cells.Item($lastRow, $lastColumn))
            $newTable = $sheet.ListObjects.Add(1, $tableRange, $null, 1)
            $newTable.Name = $alias
            if ($sourceIndex -eq 0) { $inputRows = [int]$newTable.ListRows.Count }
        }
        else { Fail "PQ_SOURCE_MISSING" "Unknown source kind." }
    }

    Trace "create-query"
    $queryName = "PQ_Code_M_Result"
    if (@($workbook.Queries | Where-Object { $_.Name -eq $queryName }).Count -gt 0) {
        $queryName = "PQ_Code_M_" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
    }
    [void]$workbook.Queries.Add($queryName, [string]$request.mCode)
    $resultSheet = $workbook.Worksheets.Add()
    $sheetName = "PQ_Result"
    if (@($workbook.Worksheets | Where-Object { $_.Name -eq $sheetName -and $_ -ne $resultSheet }).Count -gt 0) {
        $sheetName = "PQ_Result_" + [Guid]::NewGuid().ToString("N").Substring(0, 6)
    }
    $resultSheet.Name = $sheetName

    Trace "refresh-query"
    $connectionString = 'OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;Location=' + $queryName + ';Extended Properties=""'
    $resultTable = $resultSheet.ListObjects.Add(0, $connectionString, $null, 1, $resultSheet.Range("A1"))
    $queryTable = $resultTable.QueryTable
    $queryTable.CommandType = 2
    $queryTable.CommandText = "SELECT * FROM [$queryName]"
    $queryTable.BackgroundQuery = $false
    [void]$queryTable.Refresh($false)

    Trace "read-result"
    $columnCount = [int]$resultTable.ListColumns.Count
    $rowCount = [int]$resultTable.ListRows.Count
    if ($columnCount -lt 1) { Fail "PQ_RESULT_NOT_TABLE" "M did not load a table result." }
    $columns = New-Object System.Collections.Generic.List[string]
    $rows = New-Object System.Collections.Generic.List[object]
    $visibleColumns = [Math]::Min(200, $columnCount)
    for ($col = 1; $col -le $visibleColumns; $col++) {
        $columns.Add([string]$resultTable.HeaderRowRange.Cells.Item(1, $col).Value2)
    }
    for ($row = 1; $row -le [Math]::Min(20, $rowCount); $row++) {
        $values = New-Object System.Collections.Generic.List[object]
        for ($col = 1; $col -le $visibleColumns; $col++) {
            $cell = $resultTable.DataBodyRange.Cells.Item($row, $col)
            $value = $cell.Value2
            if ($value -is [Runtime.InteropServices.ErrorWrapper]) {
                # Preview may contain original Excel error cells. Show their displayed error text;
                # the static result workbook still retains the underlying Excel error value.
                $value = [string]$cell.Text
            }
            $values.Add($value)
        }
        $rows.Add($values.ToArray())
    }
    Trace "save-preview"
    $workbook.Save()
    if ($resultWorkbookPath) {
        Trace "export-values"
        $staticWorkbook = $excel.Workbooks.Add(-4167)
        $staticSheet = $staticWorkbook.Worksheets.Item(1)
        $staticSheet.Name = "PQ_Result_Values"
        $resultRange = $resultTable.Range
        $staticRange = $staticSheet.Range($staticSheet.Cells.Item(1, 1), $staticSheet.Cells.Item([int]$resultRange.Rows.Count, [int]$resultRange.Columns.Count))
        # Preserve the materialized numeric/date/text variants. The old build
        # formatted the whole range as Text, which turned integer columns (for
        # example Qty) into numbers-stored-as-text. Avoid clipboard-based COM
        # operations because they are unreliable in the non-interactive helper.
        $staticRange.NumberFormat = "General"
        $sourceValues = $resultRange.Value2
        $resultRowCount = [int]$resultRange.Rows.Count
        $resultColumnCount = [int]$resultRange.Columns.Count
        if ($resultRowCount -eq 1 -and $resultColumnCount -eq 1) {
            if ($sourceValues -is [string] -and $sourceValues -match '^[=+@-]') {
                $staticRange.NumberFormat = "@"
            }
        }
        elseif ($sourceValues -is [Array]) {
            $rowLower = $sourceValues.GetLowerBound(0)
            $columnLower = $sourceValues.GetLowerBound(1)
            for ($rowOffset = 0; $rowOffset -lt $resultRowCount; $rowOffset++) {
                for ($columnOffset = 0; $columnOffset -lt $resultColumnCount; $columnOffset++) {
                    $candidateValue = $sourceValues.GetValue($rowLower + $rowOffset, $columnLower + $columnOffset)
                    if ($candidateValue -is [string] -and $candidateValue -match '^[=+@-]') {
                        $staticSheet.Cells.Item($rowOffset + 1, $columnOffset + 1).NumberFormat = "@"
                    }
                }
            }
        }
        $staticRange.Value2 = $sourceValues
        $staticWorkbook.SaveAs($resultWorkbookPath, 51)
        $staticWorkbook.Close($false)
        $staticWorkbook = $null
    }
    $response = [ordered]@{
        ok = $true
        queryName = $queryName
        resultSheet = $sheetName
        sourceRows = $inputRows
        resultRows = $rowCount
        resultColumns = $columnCount
        columns = $columns.ToArray()
        rows = $rows.ToArray()
        excelVersion = [string]$excel.Version
    }
}
catch {
    $exitCode = 1
    $message = [string]$_.Exception.Message
    $parts = $message -split "\|", 2
    $code = if ($parts.Count -eq 2) { $parts[0] } else { "PQ_REFRESH_FAILED" }
    $detail = if ($parts.Count -eq 2) { $parts[1] }
        elseif ($script:Stage -eq "refresh-query") {
            "Excel could not refresh M (HRESULT 0x$($_.Exception.HResult.ToString('X8'))). Check source/column names and whether row filters or Table.Distinct encounter Excel error cells."
        }
        else { "Excel failed at $($script:Stage) (HRESULT 0x$($_.Exception.HResult.ToString('X8')))." }
    $response = [ordered]@{ ok = $false; error = [ordered]@{ code = $code; target = "pq-temp-workbook"; detail = $detail; stage = $script:Stage } }
}
finally {
    Trace "cleanup"
    if ($excelOwned -and $null -ne $staticWorkbook) { try { $staticWorkbook.Close($false) } catch {} }
    if ($excelOwned -and $null -ne $workbook) { try { $workbook.Close($false) } catch {} }
    if ($excelOwned -and $null -ne $excel) { try { $excel.Quit() } catch {} }
    $workbook = $null
    $staticWorkbook = $null
    $excel = $null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$response | ConvertTo-Json -Depth 10 -Compress
exit $exitCode
