$ErrorActionPreference = "Stop"

$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Repo ".venv-backend\Scripts\python.exe"
$LogDir = Join-Path $Repo "logs"
$BridgeBuild = Join-Path $Repo "local_clients\kinect_sdk_audio_bridge\build.ps1"
$BridgeExe = Join-Path $Repo "local_clients\kinect_sdk_audio_bridge\bin\OpenClaw.KinectSdkAudioBridge.exe"
$SnapshotDir = Join-Path $Repo "data\kinect-sdk-snapshots"
$WakeSnapshotDir = Join-Path $Repo "data\kinect-wake-snapshots"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $SnapshotDir | Out-Null
New-Item -ItemType Directory -Force -Path $WakeSnapshotDir | Out-Null
Set-Location $Repo

if (-not (Test-Path $BridgeExe)) {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $BridgeBuild
}

$ErrorActionPreference = "Continue"
$LogPath = Join-Path $LogDir "kinect-sdk-client.combined.log"
cmd.exe /c "`"$Python`" -u local_clients\kinect_windows_client.py --input-backend kinect-sdk --sdk-bridge-exe `"$BridgeExe`" --sdk-snapshot-dir `"$SnapshotDir`" --vision-context-provider openclaw-cli --vision-context-timeout-ms 5000 --vision-wake-snapshot-dir `"$WakeSnapshotDir`" --output-device Altavoces --ws-url ws://127.0.0.1:8080/ --wake-word --wake-sound-ms 220 > `"$LogPath`" 2>&1"

