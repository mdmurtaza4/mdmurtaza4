# ELiXIR AI Video Studio - one-step Windows installer
#
# Run in PowerShell (not as Administrator is fine; winget may ask for approval):
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# What it does (safe to run again; it skips anything already installed):
#   1. Installs Python 3.11, Git and FFmpeg (full build with NVENC, libx264, libass) via winget
#   2. Downloads the project to C:\ELiXIR-Video-Studio (or updates it)
#   3. Creates the Python environment and installs the engine
#   4. Prints the hardware report and runs the tests
# It does NOT install CUDA libraries, extra AI models or anything else.

param(
    [string]$InstallDir = "C:\ELiXIR-Video-Studio",
    [string]$Repo = "https://github.com/mdmurtaza4/mdmurtaza4.git",
    [string]$Branch = "claude/elixir-video-studio-hardware-5355gp"
)
$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Ensure($command, $wingetId, $label) {
    if (Get-Command $command -ErrorAction SilentlyContinue) {
        Write-Host "  $label already installed"
        return
    }
    Write-Host "  Installing $label ..."
    winget install --id $wingetId -e --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) { throw "winget could not install $label ($wingetId)." }
    Refresh-Path
}

Step "Checking winget"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget is missing. Install 'App Installer' from the Microsoft Store, then run this script again."
}

Step "Installing prerequisites"
Ensure git "Git.Git" "Git"
Ensure ffmpeg "Gyan.FFmpeg" "FFmpeg"
$hasPy311 = $false
if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 --version *> $null; $hasPy311 = ($LASTEXITCODE -eq 0) }
if (-not $hasPy311) {
    Write-Host "  Installing Python 3.11 ..."
    winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements --silent
    Refresh-Path
} else { Write-Host "  Python 3.11 already installed" }

foreach ($c in "git", "ffmpeg", "ffprobe", "py") {
    if (-not (Get-Command $c -ErrorAction SilentlyContinue)) {
        throw "$c is still not on PATH. Close PowerShell, open a new window and run this script again."
    }
}

Step "Downloading the project to $InstallDir"
if (Test-Path (Join-Path $InstallDir ".git")) {
    git -C $InstallDir fetch origin $Branch
    git -C $InstallDir checkout $Branch
    git -C $InstallDir pull --ff-only origin $Branch
} else {
    git clone --branch $Branch $Repo $InstallDir
}
if ($LASTEXITCODE -ne 0) { throw "Could not download the project. If GitHub asks you to sign in, do so and run again." }

Step "Creating the Python environment"
$backend = Join-Path $InstallDir "backend"
Set-Location $backend
if (-not (Test-Path ".venv")) { py -3.11 -m venv .venv }
$python = Join-Path $backend ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip wheel
& $python -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Python package installation failed." }

Step "Hardware report (share this with Claude)"
& $python -m elixir_studio detect

Step "Running tests"
# End-to-end tests need espeak-ng and are skipped without it; unit tests always run.
& $python -m pytest -q

Write-Host "`nInstallation complete." -ForegroundColor Green
Write-Host "Process a video:"
Write-Host "  cd $backend"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python -m elixir_studio process C:\Videos\speech.mp4 --preset vertical --preset landscape"
Write-Host "The first transcription downloads the Whisper model (about 500 MB for 'small')."
