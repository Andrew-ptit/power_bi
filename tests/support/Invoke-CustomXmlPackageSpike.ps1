param(
    [Parameter(Mandatory = $true)]
    [string]$RequestPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class PQPCNativeMethods {
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@

function Release-Com([object]$Value) {
    if ($null -ne $Value -and [Runtime.InteropServices.Marshal]::IsComObject($Value)) {
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($Value) } catch {}
    }
}

function Read-NamespaceParts([object]$Workbook, [string]$Namespace) {
    $allParts = $null
    $selection = $null
    $items = New-Object System.Collections.Generic.List[object]
    try {
        $allParts = $Workbook.CustomXMLParts
        $selection = $allParts.SelectByNamespace($Namespace)
        for ($index = 1; $index -le $selection.Count; $index++) {
            $part = $null
            try {
                $part = $selection.Item($index)
                $items.Add([ordered]@{ id = [string]$part.Id; xmlLength = ([string]$part.XML).Length })
            }
            finally { Release-Com $part }
        }
        return $items.ToArray()
    }
    finally {
        Release-Com $selection
        Release-Com $allParts
    }
}

$excel = $null
$workbooks = $null
$workbook = $null
$customXmlParts = $null
$excelPid = 0
$response = $null
$exitCode = 0
$cleanupForced = $false
$stage = "read-request"

try {
    $requestFile = (Resolve-Path -LiteralPath $RequestPath).Path
    $request = Get-Content -LiteralPath $requestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($request.version -ne 1 -or -not $request.workingCopyPath -or -not $request.saveAsPath -or
        -not $request.namespace -or -not $request.xmlDocuments) {
        throw "SPIKE_REQUEST_INVALID|Missing request fields."
    }
    $workingCopyPath = [IO.Path]::GetFullPath([string]$request.workingCopyPath)
    $saveAsPath = [IO.Path]::GetFullPath([string]$request.saveAsPath)
    if (-not [IO.File]::Exists($workingCopyPath) -or [IO.Path]::GetExtension($workingCopyPath) -ne ".xlsx") {
        throw "SPIKE_REQUEST_INVALID|workingCopyPath must be an existing .xlsx file."
    }
    if ([IO.File]::Exists($saveAsPath) -or [IO.Path]::GetExtension($saveAsPath) -ne ".xlsx" -or
        [IO.Path]::GetDirectoryName($workingCopyPath) -ne [IO.Path]::GetDirectoryName($saveAsPath)) {
        throw "SPIKE_REQUEST_INVALID|saveAsPath must be a new .xlsx beside the working copy."
    }

    $stage = "create-excel"
    $excel = New-Object -ComObject Excel.Application
    [uint32]$createdPid = 0
    [void][PQPCNativeMethods]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd, [ref]$createdPid)
    $excelPid = [int]$createdPid
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    $excelVersion = [string]$excel.Version
    $excelBuild = [string]$excel.Build
    $workbooks = $excel.Workbooks

    $stage = "add-parts"
    $workbook = $workbooks.Open($workingCopyPath, 0, $false)
    foreach ($xml in @($request.xmlDocuments)) {
        $part = $null
        try {
            if ($null -eq $customXmlParts) { $customXmlParts = $workbook.CustomXMLParts }
            $part = $customXmlParts.Add([string]$xml)
        }
        finally { Release-Com $part }
    }
    Release-Com $customXmlParts
    $customXmlParts = $null
    $workbook.Save()
    $workbook.Close($false)
    Release-Com $workbook
    $workbook = $null

    $stage = "reopen-working-copy"
    $workbook = $workbooks.Open($workingCopyPath, 0, $false)
    $workingParts = @(Read-NamespaceParts $workbook ([string]$request.namespace))

    $stage = "save-as"
    $workbook.SaveAs($saveAsPath, 51)
    $workbook.Close($false)
    Release-Com $workbook
    $workbook = $null

    $stage = "reopen-save-as"
    $workbook = $workbooks.Open($saveAsPath, 0, $true)
    $saveAsParts = @(Read-NamespaceParts $workbook ([string]$request.namespace))
    $workbook.Close($false)
    Release-Com $workbook
    $workbook = $null

    $response = [ordered]@{
        ok = $true
        excelVersion = $excelVersion
        excelBuild = $excelBuild
        excelPid = $excelPid
        workingParts = $workingParts
        saveAsParts = $saveAsParts
    }
}
catch {
    $exitCode = 1
    $message = [string]$_.Exception.Message
    $parts = $message -split "\|", 2
    $code = if ($parts.Count -eq 2) { $parts[0] } else { "SPIKE_COM_FAILED" }
    $detail = if ($parts.Count -eq 2) { $parts[1] } else { "Excel COM failed at $stage (HRESULT 0x$($_.Exception.HResult.ToString('X8')))." }
    $response = [ordered]@{ ok = $false; error = [ordered]@{ code = $code; detail = $detail; stage = $stage } }
}
finally {
    if ($null -ne $customXmlParts) { Release-Com $customXmlParts }
    if ($null -ne $workbook) { try { $workbook.Close($false) } catch {}; Release-Com $workbook }
    if ($null -ne $workbooks) { Release-Com $workbooks }
    if ($null -ne $excel) { try { $excel.Quit() } catch {}; Release-Com $excel }
    $workbook = $null
    $customXmlParts = $null
    $workbooks = $null
    $excel = $null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    if ($excelPid -gt 0) {
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        while ([DateTime]::UtcNow -lt $deadline -and $null -ne (Get-Process -Id $excelPid -ErrorAction SilentlyContinue)) {
            Start-Sleep -Milliseconds 250
        }
        if ($null -ne (Get-Process -Id $excelPid -ErrorAction SilentlyContinue)) {
            $cleanupForced = $true
            Stop-Process -Id $excelPid -Force -ErrorAction SilentlyContinue
            try { Wait-Process -Id $excelPid -Timeout 5 -ErrorAction SilentlyContinue } catch {}
        }
    }
}

$response["excelPidExited"] = ($excelPid -le 0 -or $null -eq (Get-Process -Id $excelPid -ErrorAction SilentlyContinue))
$response["cleanupForced"] = $cleanupForced
$response | ConvertTo-Json -Depth 8 -Compress
exit $exitCode
