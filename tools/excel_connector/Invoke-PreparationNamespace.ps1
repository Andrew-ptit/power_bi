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

function Get-NewExcelProcessProof {
    param([int]$ExcelProcessId, [int[]]$BaselineExcelPids, [long]$CreationFloorFileTime)
    if ($ExcelProcessId -le 0 -or $BaselineExcelPids -contains $ExcelProcessId) {
        Throw-ConnectorError "EXCEL_INSTANCE_NOT_OWNED" "Excel application ownership is unproven; existing instances remain untouched."
    }
    $excelProcess = Get-Process -Id $ExcelProcessId -ErrorAction Stop
    try {
        $created = $excelProcess.StartTime.ToFileTimeUtc()
        if ($excelProcess.ProcessName -ine "EXCEL" -or $created -lt $CreationFloorFileTime) {
            Throw-ConnectorError "EXCEL_INSTANCE_NOT_OWNED" "Excel process identity or creation time did not prove a new owned instance."
        }
        return [ordered]@{ excelOwned = $true; excelPid = $ExcelProcessId; excelCreationFileTime = $created.ToString([Globalization.CultureInfo]::InvariantCulture) }
    }
    finally { $excelProcess.Dispose() }
}

$excel=$null; $workbook=$null; $excelOwned=$false; $exitCode=0
try {
    Write-ConnectorTrace "read-namespace-request"
    $resolvedRequest=(Resolve-Path -LiteralPath $RequestPath).Path
    $request=Get-Content -LiteralPath $resolvedRequest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($request.version -ne 1 -or $request.mode -ne 'preparation-namespace-v1' -or $request.namespaceId -notmatch '^[a-f0-9]{16}$') { Throw-ConnectorError 'CONNECTOR_PROTOCOL' 'Invalid namespace request.' }
    $source=[IO.Path]::GetFullPath([string]$request.workbookPath)
    $output=[IO.Path]::GetFullPath([string]$request.outputPath)
    if ([IO.Path]::GetDirectoryName($source) -ne [IO.Path]::GetDirectoryName($output) -or [IO.Path]::GetFileName($source) -ne 'source.xlsx' -or [IO.Path]::GetFileName($output) -ne 'normalized.xlsx' -or [IO.File]::Exists($output)) { Throw-ConnectorError 'CONNECTOR_PROTOCOL' 'Only a fresh sibling normalized copy is allowed.' }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $request.sourceSha256) { Throw-ConnectorError 'DP_SOURCE_STALE' 'Temporary source hash changed.' }
    $baseline=@([Diagnostics.Process]::GetProcessesByName('EXCEL')); $pids=@($baseline | ForEach-Object {$_.Id})
    foreach($process in $baseline){$process.Dispose()}
    $floor=[DateTime]::UtcNow.ToFileTimeUtc()
    Write-ConnectorTrace 'create-owned-excel'
    $excel=New-Object -ComObject Excel.Application
    [uint32]$pidValue=0
    [void][W21NativeMethods]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd,[ref]$pidValue)
    $proof=Get-NewExcelProcessProof -ExcelProcessId ([int]$pidValue) -BaselineExcelPids $pids -CreationFloorFileTime $floor
    $excelOwned=$true
    if($request.statePath){
        $state=[IO.Path]::GetFullPath([string]$request.statePath)
        if([IO.Path]::GetDirectoryName($state) -ne [IO.Path]::GetDirectoryName($resolvedRequest)){Throw-ConnectorError 'CONNECTOR_PROTOCOL' 'State must remain beside request.'}
        $proof | ConvertTo-Json -Compress | Set-Content -LiteralPath $state -Encoding UTF8
    }
    $excel.Visible=$false; $excel.DisplayAlerts=$false; $excel.AskToUpdateLinks=$false; $excel.EnableEvents=$false; $excel.AutomationSecurity=3
    Write-ConnectorTrace 'open-readonly-temporary-source'
    $workbook=$excel.Workbooks.Open($source,0,$true)
    if($workbook.ProtectStructure -or $workbook.HasVBProject -or $workbook.Connections.Count -gt 0 -or $null -ne $workbook.LinkSources(1)){Throw-ConnectorError 'DP_UNSUPPORTED_PRESERVATION' 'External, executable or protected source is unsupported.'}
    if($workbook.Worksheets.Count -ne @($request.sheets).Count -or $workbook.Sheets.Count -ne $workbook.Worksheets.Count){Throw-ConnectorError 'DP_UNSUPPORTED_PRESERVATION' 'Complete worksheet group is required.'}
    foreach($mapping in $request.sheets){if($workbook.Worksheets.Item([string]$mapping.sourceName).ProtectContents){Throw-ConnectorError 'DP_UNSUPPORTED_PRESERVATION' 'Protected worksheet is unsupported.'}}
    Write-ConnectorTrace 'native-rename-defined-names'
    # Resolve native name objects before changing any spelling or sheet scope.
    $nameObjects=@()
    foreach($mapping in $request.names){
        if($mapping.scope -eq 'workbook'){$item=$workbook.Names.Item([string]$mapping.name)}
        else {$sheet=$workbook.Worksheets.Item([string]$mapping.scope); $item=$sheet.Names.Item("'"+$sheet.Name.Replace("'","''")+"'!"+[string]$mapping.name)}
        $nameObjects+=,[ordered]@{item=$item; target=[string]$mapping.targetName; scope=[string]$mapping.scope}
    }
    foreach($entry in $nameObjects){
        # The object retains its scope. Qualifying the new Name here makes
        # Excel store the qualifier as part of the local identifier itself.
        $entry.item.Name=$entry.target
    }
    Write-ConnectorTrace 'native-rename-tables'
    foreach($mapping in $request.tables){
        $found=$false
        foreach($sheet in $workbook.Worksheets){foreach($table in $sheet.ListObjects){if($table.Name -eq $mapping.name){$table.Name=[string]$mapping.targetName; $found=$true}}}
        if(-not $found){Throw-ConnectorError 'DP_UNSUPPORTED_PRESERVATION' 'Reviewed Table was not found.'}
    }
    Write-ConnectorTrace 'native-rename-worksheet-group'
    $sheetObjects=@(); $index=0
    foreach($mapping in $request.sheets){$sheet=$workbook.Worksheets.Item([string]$mapping.sourceName); $sheetObjects+=,[ordered]@{item=$sheet; target=[string]$mapping.targetName}; $sheet.Name='_dp_'+$request.namespaceId+'_'+$index; $index++}
    foreach($entry in $sheetObjects){$entry.item.Name=$entry.target}
    $excel.CalculateFullRebuild()
    $evidence=@()
    $totalCells=0
    foreach($entry in $sheetObjects){
        $sheet=$entry.item; $range=$sheet.UsedRange
        $height=[int]$range.Rows.Count; $width=[int]$range.Columns.Count
        $totalCells+=$height*$width
        if($height -gt 100000 -or $width -gt 200 -or $totalCells -gt 400000){Throw-ConnectorError 'REQUEST_LIMIT' 'Native source frames exceed bounded recovery limits.'}
        $values=@();$formulas=@();$formats=@();$mask=@()
        for($r=1;$r -le $height;$r++){
            $valueRow=@();$formulaRow=@();$formatRow=@()
            for($c=1;$c -le $width;$c++){
                $cell=$range.Cells.Item($r,$c)
                $value=$cell.Value2
                if($null -eq $value){$value=''}
                $valueRow+=,$value
                if($cell.HasFormula){$formulaRow+=,[string]$cell.Formula2; $mask+=,@(($r-1),($c-1))}else{$formulaRow+=,$value}
                $formatRow+=,[string]$cell.NumberFormat
                $cell=$null
            }
            $values+=,@($valueRow);$formulas+=,@($formulaRow);$formats+=,@($formatRow)
        }
        $evidence+=,[ordered]@{name=[string]$sheet.Name; rowOffset=[int]$range.Row-1; columnOffset=[int]$range.Column-1; values=@($values); formulas=@($formulas); formulaCells=@($mask); numberFormats=@($formats)}
    }
    Write-ConnectorTrace 'export-owned-temporary-copy'
    $workbook.SaveCopyAs($output)
    if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $request.sourceSha256){Throw-ConnectorError 'DP_SOURCE_STALE' 'Read-only input copy changed.'}
    $result=[ordered]@{ok=$true; namespaceId=[string]$request.namespaceId; connector='excel-com-preparation-namespace-v1'; sheets=$evidence}
} catch {
    $exitCode=1; $parts=([string]$_.Exception.Message) -split '\|',2
    $result=[ordered]@{ok=$false;error=[ordered]@{code=$(if($parts.Count -eq 2){$parts[0]}else{'EXCEL_CONNECTOR_FAILED'});detail=$(if($parts.Count -eq 2){$parts[1]}else{$parts[0]});stage=$script:CurrentStage}}
} finally {
    if($excelOwned -and $null -ne $workbook){try{$workbook.Close($false)}catch{}}
    if($excelOwned -and $null -ne $excel){try{$excel.Quit()}catch{}}
    $workbook=$null; $excel=$null
    [GC]::Collect();[GC]::WaitForPendingFinalizers();[GC]::Collect();[GC]::WaitForPendingFinalizers()
}
$result | ConvertTo-Json -Depth 12 -Compress
exit $exitCode

