param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $RagArgs
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

if (-not $RagArgs -or $RagArgs.Count -eq 0) {
    $RagArgs = @("--root", $ProjectRoot, "--help")
} elseif ($RagArgs[0] -ne "--root") {
    $RagArgs = @("--root", $ProjectRoot) + $RagArgs
}

python -m rbs_rag @RagArgs
exit $LASTEXITCODE

