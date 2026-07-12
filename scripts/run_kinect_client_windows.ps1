$ErrorActionPreference = "Stop"

$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Repo ".venv-backend\Scripts\python.exe"
$LogDir = Join-Path $Repo "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Repo

$ErrorActionPreference = "Continue"
$LogPath = Join-Path $LogDir "kinect-client.combined.log"
cmd.exe /c "`"$Python`" -u local_clients\kinect_windows_client.py --input-device Kinect --output-device Altavoces --ws-url ws://127.0.0.1:8080/ --wake-word --wake-sound-ms 220 > `"$LogPath`" 2>&1"

