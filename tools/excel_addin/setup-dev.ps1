param(
    [switch]$Trust
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$certDirectory = Join-Path $root ".certs"
$certificate = Join-Path $certDirectory "localhost.pem"
$key = Join-Path $certDirectory "localhost.key"

if (-not (Test-Path -LiteralPath $certDirectory)) {
    New-Item -ItemType Directory -Path $certDirectory | Out-Null
}

$arguments = @("dev-certs", "https", "--export-path", $certificate, "--format", "Pem", "--no-password")
if ($Trust) {
    $arguments += "--trust"
}

& dotnet @arguments
if ($LASTEXITCODE -ne 0) {
    throw "dotnet dev-certs failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath $certificate) -or -not (Test-Path -LiteralPath $key)) {
    throw "Expected PEM certificate/key were not created in $certDirectory"
}

Write-Host "Certificate: $certificate"
Write-Host "Private key: $key"
if (-not $Trust) {
    Write-Host "Certificate was exported but not trusted. Run again with -Trust before Excel sideload."
}
Write-Host "Start server: py -m pbip_assistant.excel_addin_server"
