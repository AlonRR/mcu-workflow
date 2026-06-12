# mcu-workflow bootstrap installer (Windows PowerShell / pwsh).
#
# One-liner (PowerShell, or from cmd via:  powershell -c "..."):
#   irm https://raw.githubusercontent.com/OWNER/REPO/main/install.ps1 | iex
#
# It installs uv (a standalone binary - no Python needed), uses uv to get a
# Python, clones this repo, runs `mcuflow doctor --fix` (which provisions the
# Python deps into a project .venv plus usbipd-win/Docker/the ESP-IDF cage
# image), and adds `mcuflow` to your user PATH.
#
# Override the source repo or install location:
#   $env:MCUFLOW_REPO='https://github.com/you/fork.git'; $env:MCUFLOW_HOME='C:\tools\mcuflow'; irm .../install.ps1 | iex
$ErrorActionPreference = 'Stop'

$Repo  = if ($env:MCUFLOW_REPO) { $env:MCUFLOW_REPO } else { 'https://github.com/OWNER/REPO.git' }
$Dest  = if ($env:MCUFLOW_HOME) { $env:MCUFLOW_HOME } else { Join-Path $env:USERPROFILE 'mcu-workflow' }
$PyVer = '3.12'
function Say($m) { Write-Host "[mcuflow] $m" -ForegroundColor Cyan }

# 1. uv (standalone; installs without Python).
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Say 'installing uv ...'
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
}
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"   # uv installs here

# 2. A managed Python (used only to bootstrap; the tool then builds its own .venv).
Say "ensuring Python $PyVer ..."
uv python install $PyVer | Out-Null

# 3. Fetch the repo (git if available, else a source zip).
if (Test-Path (Join-Path $Dest '.git')) {
  Say "updating existing checkout at $Dest ..."
  git -C $Dest pull --ff-only 2>$null
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
  Say "cloning into $Dest ..."
  git clone --depth 1 $Repo $Dest
} else {
  Say 'git not found - downloading source archive ...'
  $zip = Join-Path $env:TEMP 'mcuflow-src.zip'
  Invoke-WebRequest (($Repo -replace '\.git$','') + '/archive/refs/heads/main.zip') -OutFile $zip
  Expand-Archive $zip -DestinationPath $env:TEMP -Force
  $src = Get-ChildItem $env:TEMP -Directory | Where-Object Name -like 'mcu-workflow-*' | Select-Object -First 1
  New-Item -ItemType Directory -Force $Dest | Out-Null
  Copy-Item (Join-Path $src.FullName '*') $Dest -Recurse -Force
}

# 4. Provision everything via the tool's own self-install.
Say 'provisioning prerequisites (doctor --fix) ...'
uv run --no-project --python $PyVer -- python (Join-Path $Dest 'src\mcuflow\mcuflow.py') doctor --fix

# 5. Put mcuflow on the user PATH for future shells.
$Bin = Join-Path $Dest 'bin'
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $Bin) {
  [Environment]::SetEnvironmentVariable('Path', "$Bin;$userPath", 'User')
  Say "added $Bin to your user PATH"
}

Say 'done. Open a NEW terminal, then run:  mcuflow doctor'
