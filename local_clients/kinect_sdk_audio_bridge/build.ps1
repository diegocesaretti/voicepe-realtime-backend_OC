$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Resolve-Path (Join-Path $Root "..\..")
$OutDir = Join-Path $Root "bin"
$KinectSdk = "C:\Program Files\Microsoft SDKs\Kinect\v1.8"
$KinectDll = Join-Path $KinectSdk "Assemblies\Microsoft.Kinect.dll"
$Csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not (Test-Path $KinectDll)) {
    throw "Kinect SDK v1.8 Microsoft.Kinect.dll not found at $KinectDll"
}

if (-not (Test-Path $Csc)) {
    throw ".NET Framework csc.exe not found at $Csc"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutExe = Join-Path $OutDir "OpenClaw.KinectSdkAudioBridge.exe"

& $Csc `
    /nologo `
    /target:exe `
    /platform:x64 `
    "/out:$OutExe" `
    /reference:$KinectDll `
    /reference:System.Drawing.dll `
    (Join-Path $Root "Program.cs")

if ($LASTEXITCODE -ne 0) {
    throw "csc.exe failed with exit code $LASTEXITCODE"
}

Copy-Item -Force $KinectDll (Join-Path $OutDir "Microsoft.Kinect.dll")

Write-Host "Built $OutDir\OpenClaw.KinectSdkAudioBridge.exe"

