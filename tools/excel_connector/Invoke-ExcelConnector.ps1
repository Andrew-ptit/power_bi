param(
    [Parameter(Mandatory = $true)]
    [string]$RequestPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Throw-ConnectorError {
    param([string]$Code, [string]$Detail)
    throw "$Code|$Detail"
}

function Write-ConnectorTrace {
    param([string]$Stage)
    $script:CurrentStage = $Stage
    [Console]::Error.WriteLine("[w21] $Stage")
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class W21NativeMethods {
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@

function Get-TableByName {
    param($Workbook, [string]$Name)
    for ($sheetIndex = 1; $sheetIndex -le $Workbook.Worksheets.Count; $sheetIndex++) {
        $sheet = $Workbook.Worksheets.Item($sheetIndex)
        try {
            for ($tableIndex = 1; $tableIndex -le $sheet.ListObjects.Count; $tableIndex++) {
                $table = $sheet.ListObjects.Item($tableIndex)
                if ($table.Name -eq $Name) {
                    return $table
                }
            }
        }
        finally { $sheet = $null }
    }
    return $null
}

function Get-ListColumnByName {
    param($Table, [string]$Name)
    for ($index = 1; $index -le $Table.ListColumns.Count; $index++) {
        $column = $Table.ListColumns.Item($index)
        if ($column.Name -eq $Name) {
            return $column
        }
        $column = $null
    }
    return $null
}

$catalog = [ordered]@{
    "op-net-revenue" = [ordered]@{
        Table = "SalesTable"
        Column = "Net Revenue"
        Formula = "=[@[Gross Revenue]]-[@[Discount Value]]-[@[Return Value]]"
        NumberFormat = "#,##0.00"
    }
    "op-return-rate" = [ordered]@{
        Table = "SalesTable"
        Column = "Return Rate"
        Formula = "=IFERROR([@[Total Return Qty]]/[@[Total Sold Qty]],0)"
        NumberFormat = "0.00%"
    }
    "op-commission" = [ordered]@{
        Table = "SalesTable"
        Column = "Commission Value"
        Formula = "=[@[Net Revenue]]*XLOOKUP([@[Net Revenue]],CommissionTable[Min Net Revenue],CommissionTable[Commission Rate],0,-1)"
        NumberFormat = "#,##0.00"
    }
    "op-sales-rank" = [ordered]@{
        Table = "SalesTable"
        Column = "Sales Rank"
        Formula = '=LET(p,PERCENTRANK.INC(SalesTable[Net Revenue],[@[Net Revenue]]),IFS(p>=0.9,"Top 10%",p>=0.8,"Top 20%",TRUE,"Bottom"))'
        NumberFormat = $null
    }
}

$excel = $null
$workbook = $null
$result = $null
$exitCode = 0
$stopwatch = [Diagnostics.Stopwatch]::StartNew()

try {
    Write-ConnectorTrace "read-request"
    $resolvedRequest = (Resolve-Path -LiteralPath $RequestPath).Path
    $request = Get-Content -LiteralPath $resolvedRequest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($request.version -ne 1) {
        Throw-ConnectorError "CONNECTOR_PROTOCOL" "Unsupported request version."
    }
    if (-not $request.workbookPath) {
        Throw-ConnectorError "CONNECTOR_PROTOCOL" "workbookPath is required."
    }
    $workbookPath = [IO.Path]::GetFullPath([string]$request.workbookPath)
    if ([IO.Path]::GetExtension($workbookPath).ToLowerInvariant() -ne ".xlsx" -or -not [IO.File]::Exists($workbookPath)) {
        Throw-ConnectorError "WORKBOOK_EXPORT_INVALID" "The target copy must be an existing .xlsx file."
    }
    $operationIds = @($request.operations | ForEach-Object { [string]$_.id })
    $expectedIds = @($catalog.Keys)
    if ($operationIds.Count -ne $expectedIds.Count) {
        Throw-ConnectorError "UNSUPPORTED_OPERATION" "Exactly four W-21 operations are required."
    }
    for ($index = 0; $index -lt $expectedIds.Count; $index++) {
        if ($operationIds[$index] -ne $expectedIds[$index]) {
            Throw-ConnectorError "UNSUPPORTED_OPERATION" "Operation order or identifier is not allowlisted."
        }
    }

    Write-ConnectorTrace "create-excel"
    $excel = New-Object -ComObject Excel.Application
    [uint32]$excelPid = 0
    [void][W21NativeMethods]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd, [ref]$excelPid)
    if ($request.statePath) {
        $statePath = [IO.Path]::GetFullPath([string]$request.statePath)
        $requestDirectory = [IO.Path]::GetDirectoryName($resolvedRequest)
        if ([IO.Path]::GetDirectoryName($statePath) -ne $requestDirectory) {
            Throw-ConnectorError "CONNECTOR_PROTOCOL" "statePath must remain beside the request file."
        }
        [ordered]@{ excelPid = [int]$excelPid } | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath -Encoding UTF8
    }
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    Write-ConnectorTrace "open-copy"
    $workbook = $excel.Workbooks.Open($workbookPath, 0, $false)

    Write-ConnectorTrace "find-tables"
    $salesTable = Get-TableByName -Workbook $workbook -Name "SalesTable"
    if ($null -eq $salesTable) {
        Throw-ConnectorError "SCHEMA_MISMATCH" "SalesTable was not found in the copy."
    }
    $commissionTable = Get-TableByName -Workbook $workbook -Name "CommissionTable"
    if ($null -eq $commissionTable) {
        Throw-ConnectorError "SCHEMA_MISMATCH" "CommissionTable was not found in the copy."
    }
    $commissionTable = $null

    $changedTargets = New-Object System.Collections.Generic.List[string]
    foreach ($operationId in $expectedIds) {
        $entry = $catalog[$operationId]
        Write-ConnectorTrace "apply-$operationId"
        $existing = Get-ListColumnByName -Table $salesTable -Name $entry.Column
        if ($null -ne $existing) {
            $existing = $null
            Throw-ConnectorError "TARGET_EXISTS" "The target column '$($entry.Column)' already exists in the copy."
        }
        $column = $salesTable.ListColumns.Add()
        try {
            $column.Name = $entry.Column
            if ($null -eq $column.DataBodyRange) {
                Throw-ConnectorError "EMPTY_TARGET" "SalesTable has no data rows."
            }
            try {
                $column.DataBodyRange.Formula2 = $entry.Formula
            }
            catch {
                Throw-ConnectorError "FORMULA_UNSUPPORTED" "Excel rejected formula for '$($entry.Column)': $($_.Exception.Message)"
            }
            if ($null -ne $entry.NumberFormat) {
                $column.DataBodyRange.NumberFormat = $entry.NumberFormat
            }
            $changedTargets.Add("SalesTable[$($entry.Column)]")
        }
        finally {
            $column = $null
        }
    }

    Write-ConnectorTrace "calculate"
    $excel.CalculateFullRebuild()
    $calculationTimeout = [Math]::Max(1, [int]$request.calculationTimeoutSeconds)
    $calculationWatch = [Diagnostics.Stopwatch]::StartNew()
    while ($excel.CalculationState -ne 0) {
        if ($calculationWatch.Elapsed.TotalSeconds -ge $calculationTimeout) {
            Throw-ConnectorError "CALC_TIMEOUT" "Excel calculation did not finish within $calculationTimeout seconds."
        }
        Start-Sleep -Milliseconds 100
    }

    Write-ConnectorTrace "read-results"
    $resultColumns = @("SaleID", "Net Revenue", "Return Rate", "Commission Value", "Sales Rank")
    $rows = New-Object System.Collections.Generic.List[object]
    $formulaErrors = New-Object System.Collections.Generic.List[object]
    $rowCount = $salesTable.ListRows.Count
    for ($rowIndex = 1; $rowIndex -le $rowCount; $rowIndex++) {
        $rowResult = [ordered]@{}
        foreach ($columnName in $resultColumns) {
            $column = Get-ListColumnByName -Table $salesTable -Name $columnName
            if ($null -eq $column) {
                Throw-ConnectorError "RESULT_TARGET_MISSING" "Result column '$columnName' is missing."
            }
            $cell = $column.DataBodyRange.Cells.Item($rowIndex, 1)
            try {
                $value = $cell.Value2
                if ($value -is [Runtime.InteropServices.ErrorWrapper]) {
                    $formulaErrors.Add([ordered]@{
                        row = $rowIndex
                        column = $columnName
                        text = [string]$cell.Text
                    })
                    $rowResult[$columnName] = $null
                }
                else {
                    $rowResult[$columnName] = $value
                }
            }
            finally {
                $cell = $null
                $column = $null
            }
        }
        $rows.Add([PSCustomObject]$rowResult)
    }

    $formulas = [ordered]@{}
    foreach ($operationId in $expectedIds) {
        $entry = $catalog[$operationId]
        $column = Get-ListColumnByName -Table $salesTable -Name $entry.Column
        try {
            $formulaCell = $column.DataBodyRange.Cells.Item(1, 1)
            try {
                $formulas[$entry.Column] = [string]$formulaCell.Formula2
            }
            finally {
                $formulaCell = $null
            }
        }
        finally {
            $column = $null
        }
    }

    Write-ConnectorTrace "save-copy"
    $workbook.Save()
    $result = [ordered]@{
        ok = $true
        connector = "excel-com-w21"
        excelVersion = [string]$excel.Version
        calculationState = "done"
        durationMs = [int]$stopwatch.Elapsed.TotalMilliseconds
        changedTargets = $changedTargets.ToArray()
        formulas = $formulas
        rows = $rows.ToArray()
        formulaErrors = $formulaErrors.ToArray()
    }
}
catch {
    $exitCode = 1
    $message = [string]$_.Exception.Message
    $parts = $message -split "\|", 2
    $code = if ($parts.Count -eq 2) { $parts[0] } else { "EXCEL_CONNECTOR_FAILED" }
    $detail = if ($parts.Count -eq 2) { $parts[1] } else { $message }
    $result = [ordered]@{
        ok = $false
        error = [ordered]@{
            code = $code
            target = "excel-copy"
            detail = $detail
            stage = $script:CurrentStage
        }
    }
}
finally {
    Write-ConnectorTrace "cleanup"
    if ($null -ne $workbook) {
        try { $workbook.Close($false) } catch {}
    }
    if ($null -ne $excel) {
        try { $excel.Quit() } catch {}
    }
    $salesTable = $null
    $workbook = $null
    $excel = $null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

Write-ConnectorTrace "emit-result"
$result | ConvertTo-Json -Depth 10 -Compress
exit $exitCode
