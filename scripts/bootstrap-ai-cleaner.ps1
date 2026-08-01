param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$repoPath = (Resolve-Path -LiteralPath $RepoRoot).Path
$venvPath = Join-Path $repoPath ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    $ErrorActionPreference = "Continue"
    if ($null -ne $uv) {
        $venvOutput = & $uv.Source venv --python 3.11 $venvPath 2>&1
    } else {
        $venvOutput = & python -m venv $venvPath 2>&1
    }
    $venvExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($venvExitCode -ne 0) {
        throw "Could not create the metadata-cleaner Python environment."
    }
}

$dependencyCheck = @(
    "import click",
    "from PIL import Image",
    "import mutagen",
    "import pikepdf",
    "import docx"
) -join ";"
$ErrorActionPreference = "Continue"
& $pythonPath -c $dependencyCheck *> $null
$dependencyExitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($dependencyExitCode -ne 0) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    $ErrorActionPreference = "Continue"
    if ($null -ne $uv) {
        $installOutput = & $uv.Source pip install --python $pythonPath -e $repoPath 2>&1
    } else {
        $upgradeOutput = & $pythonPath -m pip install --upgrade pip 2>&1
        $upgradeExitCode = $LASTEXITCODE
        $installOutput = & $pythonPath -m pip install -e $repoPath 2>&1
    }
    $installExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($installExitCode -ne 0) {
        throw "Could not install metadata-cleaner Python dependencies."
    }
}

Push-Location $repoPath
try {
    & $pythonPath -c "from m_c.core.tool_bootstrap import resolve_exiftool; print(resolve_exiftool())"
    $toolExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($toolExitCode -ne 0) {
    throw "Could not bootstrap or validate ExifTool."
}

Write-Output $pythonPath
