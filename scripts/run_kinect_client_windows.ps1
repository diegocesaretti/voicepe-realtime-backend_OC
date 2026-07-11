$ErrorActionPreference = "Stop"

$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Repo ".venv-backend\Scripts\python.exe"
$LogDir = Join-Path $Repo "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Repo

$ErrorActionPreference = "Continue"
& $Python -u local_clients\kinect_windows_client.py `
  --input-device Kinect `
  --ws-url ws://127.0.0.1:8080/ `
  --wake-word *> (Join-Path $LogDir "kinect-client.combined.log")

