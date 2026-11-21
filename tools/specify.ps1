# Repository-local Spec Kit CLI; application Python dependencies stay separate.
$specifyExecutable = Join-Path $PSScriptRoot '../.artifacts/spec-kit-venv/Scripts/specify.exe'
if (-not (Test-Path -LiteralPath $specifyExecutable -PathType Leaf)) {
    throw 'Spec Kit environment is missing. See docs/current/DEVELOPMENT_WORKFLOWS.md for setup.'
}
& $specifyExecutable @args
exit $LASTEXITCODE
