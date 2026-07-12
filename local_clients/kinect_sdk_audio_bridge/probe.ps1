$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Exe = Join-Path $Root "bin\OpenClaw.KinectSdkAudioBridge.exe"
$Repo = Resolve-Path (Join-Path $Root "..\..")
$Out = Join-Path $Repo "data\kinect-sdk-probe.wav"

if (-not (Test-Path $Exe)) {
    & (Join-Path $Root "build.ps1")
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
& $Exe --wav $Out --probe-seconds 10
Write-Host "Wrote $Out"

