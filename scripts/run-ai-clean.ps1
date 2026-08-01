param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot

$ErrorActionPreference = "Continue"
$bootstrapOutput = & (Join-Path $scriptRoot "bootstrap-ai-cleaner.ps1") -RepoRoot $repoRoot 2>&1
$bootstrapExitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($bootstrapExitCode -ne 0) {
    $bootstrapOutput | ForEach-Object { Write-Output $_ }
    exit $bootstrapExitCode
}

if (-not (Test-Path -LiteralPath (Join-Path $repoRoot ".venv\Scripts\python.exe"))) {
    Write-Output "The metadata-cleaner Python environment was not created."
    exit 2
}

$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$exitCode = 1
Push-Location $repoRoot
try {
    & $pythonPath -m m_c.cli.main ai-clean @Arguments
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $exitCode
