param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$skillRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

function Resolve-Repository {
    $configured = $env:METADATA_CLEANER_REPO
    if ($configured -and (Test-Path -LiteralPath $configured)) {
        return (Resolve-Path -LiteralPath $configured).Path
    }

    $bundledRunner = Join-Path $skillRoot "scripts\run-ai-clean.ps1"
    if (Test-Path -LiteralPath $bundledRunner) {
        return $skillRoot
    }

    $workspaceCandidate = Join-Path (Get-Location) "metadata-cleaner"
    if (Test-Path -LiteralPath (Join-Path $workspaceCandidate "scripts\run-ai-clean.ps1")) {
        return (Resolve-Path -LiteralPath $workspaceCandidate).Path
    }

    throw "Bundled metadata-cleaner implementation not found. Set METADATA_CLEANER_REPO or place a metadata-cleaner repository under the current workspace."
}

$repoRoot = Resolve-Repository
$runner = Join-Path $repoRoot "scripts\run-ai-clean.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "The repository does not contain scripts\run-ai-clean.ps1: $repoRoot"
}

& $runner @Arguments
exit $LASTEXITCODE
