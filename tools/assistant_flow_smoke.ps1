[CmdletBinding()]
param(
    [int]$Port = 0,
    [string]$BaseUrl,
    [string]$Root,
    [ValidateSet('tp-fin', 'tp-sales')][string]$Scenario = 'tp-fin',
    [ValidateSet('session', 'ingest', 'understand', 'plan', 'branches', 'freeze', 'approvals', 'apply', 'record')][string]$StopAfter = 'record',
    [string]$WorkbookPath,
    [string]$Prompt = 'Summarize the source numeric amount and compare all rows with positive rows.',
    [switch]$KeepSession
)

# Synthetic, read-only source smoke. Use an isolated coordinator for automated
# runs: bootstrap/reset share the session of a pane using the same coordinator.
# No workbook is opened, written or saved. Apply completion is a synthetic
# backend receipt, not evidence of a write by Office.js. The plan stage uses the coordinator's injected
# test planner or real Codex; earlier stages never call Codex.
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = Join-Path $RepoRoot "tests/fixtures/assistant/$Scenario/source" }
try { $Root = (Resolve-Path -LiteralPath $Root).Path }
catch { Write-Host 'FAIL: source root does not exist'; exit 1 }
$script:Failures = New-Object 'System.Collections.Generic.List[string]'
$script:Steps = New-Object 'System.Collections.Generic.List[object]'
$script:Count = 0
$script:Hashes = [ordered]@{}
$timer = [System.Diagnostics.Stopwatch]::StartNew()
$laterStages = @('freeze', 'approvals', 'apply', 'record')
# Explicit deterministic metadata for synthetic automation, not a real approval.
$syntheticTime = '2026-10-31T03:00:00.000Z'
$workbookIdentity = @{name='AssistantSmokeSynthetic'; documentHash=('sha256:' + ('7' * 64))}

function Assert-True([string]$Name, $Condition) {
    $script:Count++
    if (-not $Condition) { $script:Failures.Add($Name) }
}

function Complete-Smoke([int]$ExitCode = 0) {
    $script:Steps | Format-Table -AutoSize | Out-Host
    foreach ($entry in $script:Hashes.GetEnumerator()) { Write-Host "$($entry.Key) $($entry.Value)" }
    foreach ($failure in $script:Failures) { Write-Host "FAIL: $failure" }
    if ($script:Failures.Count -gt 0 -and $ExitCode -eq 0) { $ExitCode = 1 }
    $outcome = if ($ExitCode -eq 0) { 'PASS' } else { 'FAIL' }
    Write-Host ("RESULT: {0}; assertions={1}; elapsed={2:F3}s" -f $outcome, $script:Count, $timer.Elapsed.TotalSeconds)
    exit $ExitCode
}

function Invoke-Flow([string]$Step, [string]$Path, [hashtable]$Payload) {
    $json = ConvertTo-Json -InputObject $Payload -Depth 64 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        $response = Invoke-RestMethod -Uri "$script:Base$Path" -Method Post -Body $bytes `
            -ContentType 'application/json; charset=utf-8' -Headers $script:Headers -TimeoutSec 180 -DisableKeepAlive
    } catch {
        $code = 'HTTP_FAILURE'
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            try { $code = ($_.ErrorDetails.Message | ConvertFrom-Json).error.code } catch { }
        }
        $script:Steps.Add([pscustomobject]@{Step=$Step; Http='ERR'; Stage='-'; Note=$code})
        # Do not print raw HTTP bodies: they could contain private source data.
        Complete-Smoke 3
    }
    $script:Steps.Add([pscustomobject]@{Step=$Step; Http=200; Stage=[string]$response.stage; Note=''})
    return $response
}

$candidates = @()
if ($BaseUrl) {
    try {
        $parsed = [Uri]$BaseUrl
        if ($parsed.Scheme -notin @('http','https') -or $parsed.Host -notin @('localhost','127.0.0.1','::1') `
            -or $parsed.AbsolutePath -ne '/' -or $parsed.Query -or $parsed.Fragment -or $parsed.UserInfo) { throw 'invalid' }
        $candidates = @($BaseUrl.TrimEnd('/'))
    } catch { Write-Host 'FAIL: BaseUrl must be an explicit loopback HTTP(S) origin'; exit 1 }
} else {
    $ports = if ($Port -gt 0) { @($Port) } else { @(3079..3072) }
    foreach ($candidatePort in $ports) {
        $candidates += "https://localhost:$candidatePort"
        $candidates += "http://127.0.0.1:$candidatePort"
    }
}
$script:Base = $null
foreach ($candidate in $candidates) {
    try {
        $health = Invoke-RestMethod -Uri "$candidate/api/health" -TimeoutSec 2 -DisableKeepAlive
        if ($health.status -eq 'ok') { $script:Base = $candidate; break }
    } catch { }
}
if (-not $script:Base) { Write-Host 'No coordinator found'; exit 2 }
try { $bootstrap = Invoke-RestMethod -Uri "$script:Base/api/bootstrap" -TimeoutSec 10 -DisableKeepAlive }
catch { Write-Host 'Bootstrap failed'; exit 3 }
if (-not $bootstrap.token -or $bootstrap.capabilities.assistantFlowV2 -ne $true) {
    Write-Host 'Coordinator does not support assistantFlowV2'; exit 3
}
$script:Headers = @{'X-Local-Token'=[string]$bootstrap.token; Origin=$script:Base}

$s1 = Invoke-Flow '01 /session' '/api/assistant/session' @{root=$Root}
$expectedStage = [string]$s1.stage
Assert-True 'session root label' (-not [string]::IsNullOrWhiteSpace($s1.rootLabel))
if ($StopAfter -ne 'session') {
    $requests = @()
    foreach ($file in (Get-ChildItem -LiteralPath $Root -Filter '*.csv' -File | Sort-Object Name)) {
        $requests += @{kind='csv'; mode='discover'; path=$file.Name}
    }
    if ($Scenario -eq 'tp-sales' -and (Test-Path -LiteralPath (Join-Path $Root 'orders') -PathType Container)) {
        $requests += @{kind='folder'; mode='discover'; path='orders'; name='Orders'}
    }
    Assert-True 'source selection is not empty' ($requests.Count -gt 0)
    if ($script:Failures.Count -gt 0) { Complete-Smoke 1 }
    $s2 = Invoke-Flow '02 /ingest' '/api/assistant/ingest' @{requests=$requests}
    $expectedStage = [string]$s2.stage
    Assert-True 'ingest reaches ingested' ($s2.stage -eq 'ingested')
    Assert-True 'ingest has sources and tables' (@($s2.sources).Count -gt 0 -and @($s2.tables).Count -gt 0)
    Assert-True 'ingest source/table count matches' (@($s2.sources).Count -eq @($s2.tables).Count)
    $expectedSources = if ($Scenario -eq 'tp-fin') { 7 } else { 5 }
    Assert-True 'synthetic fixture source count' (@($s2.sources).Count -eq $expectedSources)
    Assert-True 'ingest has no blockers' (@($s2.errors).Count -eq 0 -and @($s2.requiresRename).Count -eq 0)
    if ($s2.snapshot.snapshotHash) { $script:Hashes.snapshotHash = $s2.snapshot.snapshotHash }
    if ($script:Failures.Count -gt 0) { Complete-Smoke 1 }
    if ($StopAfter -in (@('understand','plan','branches') + $laterStages)) {
        $s3 = Invoke-Flow '03 /understand' '/api/assistant/understand' @{}
        $expectedStage = [string]$s3.stage
        Assert-True 'understand reaches understood' ($s3.stage -eq 'understood')
        Assert-True 'questions are generated' (@($s3.questions).Count -gt 0)
        foreach ($question in @($s3.questions)) {
            Assert-True 'question carries evidence' (@($question.evidence).Count -gt 0)
        }
        if ($s3.understand.understandHash) { $script:Hashes.understandHash = $s3.understand.understandHash }
        if ($StopAfter -in (@('plan','branches') + $laterStages)) {
            Write-Host 'PLAN DISCLOSURE: prompt, at most 20 sample rows, column names and statistics are sent to the configured planner; no workbook binary or file path.'
            $answers = @()
            foreach ($question in @($s3.questions)) {
                $answers += @{questionId=[string]$question.id; answer='Synthetic smoke: leave business assumptions unverified.'}
            }
            $s4 = Invoke-Flow '04 /plan-draft' '/api/assistant/plan-draft' @{prompt=$Prompt; answers=$answers; acknowledged=$true}
            $expectedStage = [string]$s4.stage
            Assert-True 'plan reaches planning' ($s4.stage -eq 'planning')
            Assert-True 'planning input binding hash' ([string]$s4.planningHash -match '^sha256:[a-f0-9]{64}$')
            $script:Hashes.planningHash = $s4.planningHash
            Assert-True 'two branch plans' (@($s4.branches).Count -eq 2)
            Assert-True 'branch identifiers' ((@($s4.branches | ForEach-Object {$_.id} | Sort-Object) -join ',') -eq 'A,B')
            foreach ($branch in @($s4.branches)) {
                Assert-True 'branch has typed steps' (@($branch.steps).Count -gt 0)
                Assert-True 'branch plan hash' ([string]$branch.planHash -match '^sha256:[a-f0-9]{64}$')
                $script:Hashes[('planHash' + [string]$branch.id)] = $branch.planHash
            }
            if ($StopAfter -eq 'branches' -or $StopAfter -in $laterStages) {
                foreach ($request in $requests) { $request['mode'] = 'compute' }
                $compute = Invoke-Flow 'compute-bind' '/api/assistant/ingest' @{requests=$requests; expectedPlanningHash=$s4.planningHash}
                Assert-True 'full ingest uses compute mode' ($compute.mode -eq 'compute')
                Assert-True 'full ingest preserves the displayed plans' ($compute.stage -eq 'planning' -and $compute.planningHash -eq $s4.planningHash)
                foreach ($sample in @($compute.sampleInfo)) {
                    Assert-True 'full rows admitted' ($sample.mode -eq 'compute' -and $sample.rowCount -eq $sample.totalRows)
                }
                $s5 = Invoke-Flow '05 /branches' '/api/assistant/branches' @{}
                $expectedStage = [string]$s5.stage
                Assert-True 'branches reaches branched' ($s5.stage -eq 'branched')
                Assert-True 'two computed branches' (@($s5.branches).Count -eq 2)
                Assert-True 'both branches use one compute snapshot' ($s5.snapshotHash -eq $compute.snapshotHash)
                Assert-True 'delta is engine computed' ($s5.delta.computedBy -eq 'typed_local')
                Assert-True 'A/B identity verified' ($s5.abIdentityPassed -eq $true)
                if ($s5.delta.applicable) {
                    $culture = [System.Globalization.CultureInfo]::InvariantCulture
                    $a = [decimal]::Parse([string]$s5.delta.a, $culture)
                    $b = [decimal]::Parse([string]$s5.delta.b, $culture)
                    $difference = [decimal]::Parse([string]$s5.delta.value, $culture)
                    Assert-True 'independent Decimal A minus B' (($a - $b) -eq $difference)
                }
                foreach ($branch in @($s5.branches)) {
                    Assert-True 'branch has no execution error' ($null -eq $branch.error)
                    Assert-True 'branch preview is bounded' (@($branch.rows).Count -le 200)
                    Assert-True 'synthetic branch reconciliation passed' ($branch.reconciliation.passed -eq $true)
                    Assert-True 'branch preview hash' ([string]$branch.previewHash -match '^sha256:[a-f0-9]{64}$')
                    Assert-True 'branch digest' ([string]$branch.resultDigest -match '^sha256:[a-f0-9]{64}$')
                    Assert-True 'engine parity remains unclaimed' ($branch.engine.parityChecked -eq 'none')
                    $script:Hashes[('previewHash' + [string]$branch.id)] = $branch.previewHash
                }
                $script:Hashes.snapshotHash = $s5.snapshotHash
                if ($StopAfter -in $laterStages) {
                    $frozen = Invoke-Flow '06 /freeze' '/api/assistant/freeze' @{
                        branchId='A'; createdAt=$syntheticTime; acknowledgeMissingControl=$false; workbookIdentity=$workbookIdentity
                        expectedPlanningHash=$s5.planningHash; expectedPreviewHash=$s5.branches[0].previewHash
                        expectedResultDigest=$s5.branches[0].resultDigest
                    }
                    $expectedStage = [string]$frozen.stage
                    Assert-True 'freeze reaches frozen' ($frozen.stage -eq 'frozen')
                    Assert-True 'freeze selects A' ($frozen.chosenBranch -eq 'A')
                    Assert-True 'spec fingerprint' ([string]$frozen.spec.fingerprint -match '^sha256:[a-f0-9]{64}$')
                    $script:Hashes.specFingerprint = $frozen.spec.fingerprint
                    if ($StopAfter -in @('approvals','apply','record')) {
                        $approved = Invoke-Flow '07 /approvals' '/api/assistant/approvals' @{
                            approvedAt=$syntheticTime; acknowledged=$true; workbookIdentity=$workbookIdentity; workbookSources=@()
                            expectedSpecFingerprint=$frozen.spec.fingerprint; expectedPreviewHash=$s5.branches[0].previewHash
                            expectedResultDigest=$s5.branches[0].resultDigest
                        }
                        $expectedStage = [string]$approved.stage
                        Assert-True 'approval reaches approved' ($approved.stage -eq 'approved')
                        Assert-True 'approval is single use' ($approved.approval.singleUse -eq $true -and $approved.approval.consumed -eq $false)
                        if ($StopAfter -in @('apply','record')) {
                            if (-not $WorkbookPath) { $WorkbookPath = Join-Path $RepoRoot 'tests/fixtures/excel/excel_mcp_sales_input.xlsx' }
                            if (-not (Test-Path -LiteralPath $WorkbookPath -PathType Leaf)) {
                                Assert-True 'synthetic workbook fixture exists' $false
                                Complete-Smoke 1
                            }
                            $workbookBytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $WorkbookPath).Path)
                            $sha = [System.Security.Cryptography.SHA256]::Create()
                            try { $beforeHash = [Convert]::ToBase64String($sha.ComputeHash($workbookBytes)) } finally { $sha.Dispose() }
                            $handoff = Invoke-Flow '08 /apply handoff' '/api/assistant/apply' @{
                                workbookBase64=[Convert]::ToBase64String($workbookBytes); appliedAt=$syntheticTime
                                workbookIdentity=$workbookIdentity; workbookSources=@()
                                expectedSpecFingerprint=$frozen.spec.fingerprint; expectedPreviewHash=$s5.branches[0].previewHash
                                expectedResultDigest=$s5.branches[0].resultDigest
                            }
                            Assert-True 'handoff does not claim completed write' ($handoff.stage -eq 'handoff')
                            Assert-True 'approval consumed before handoff' ($handoff.apply.approval.consumed -eq $true)
                            Assert-True 'full result returned' ($handoff.result.truncated -eq $false -and @($handoff.result.rows).Count -eq $handoff.result.totalRows)
                            Assert-True 'handoff result matches chosen digest' ($handoff.resultDigest -eq $s5.branches[0].resultDigest)
                            Assert-True 'server chooses target' (-not [string]::IsNullOrWhiteSpace($handoff.apply.target.sheet))
                            Assert-True 'handoff never saves workbook' ($handoff.apply.workbookSaved -eq $false)
                            Write-Host 'SYNTHETIC RECEIPT: validating backend completion only; no Excel opened or written.'
                            $receipt = @{}
                            foreach ($property in $handoff.receiptBinding.PSObject.Properties) { $receipt[$property.Name] = $property.Value }
                            $receipt.rowCount = [int]$handoff.result.totalRows
                            $receipt.columnCount = @($handoff.result.columns).Count
                            $receipt.verified = $true
                            $completed = Invoke-Flow 'apply receipt' '/api/assistant/apply' @{receipt=$receipt; appliedAt=$syntheticTime}
                            $expectedStage = [string]$completed.stage
                            Assert-True 'receipt reaches applied' ($completed.stage -eq 'applied')
                            $sha = [System.Security.Cryptography.SHA256]::Create()
                            try { $afterHash = [Convert]::ToBase64String($sha.ComputeHash([System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $WorkbookPath).Path))) } finally { $sha.Dispose() }
                            Assert-True 'synthetic input package remains byte identical' ($beforeHash -eq $afterHash)
                            if ($StopAfter -eq 'record') {
                                $record = Invoke-Flow '09 /record' '/api/assistant/record' @{}
                                $expectedStage = [string]$record.stage
                                Assert-True 'record reaches recorded' ($record.stage -eq 'recorded')
                                Assert-True 'record hash' ([string]$record.recordHash -match '^sha256:[a-f0-9]{64}$')
                                Assert-True 'metadata references full record hash' ($record.node.recordHash -eq $record.recordHash)
                                Assert-True 'metadata own hash differs from full record hash' ($record.node.hash -ne $record.recordHash)
                                $script:Hashes.recordHash = $record.recordHash
                                $script:Hashes.persistedNodeHash = $record.node.hash
                            }
                        }
                    }
                }
            }
        }
    }
}
$state = Invoke-Flow 'state' '/api/assistant/state' @{}
Assert-True 'state carries current stage' ($state.stage -eq $expectedStage)
if (-not $KeepSession) {
    $reset = Invoke-Flow 'reset' '/api/assistant/reset' @{}
    Assert-True 'reset reaches new' ($reset.stage -eq 'new')
}
Complete-Smoke
