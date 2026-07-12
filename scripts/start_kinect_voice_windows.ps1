$ErrorActionPreference = "Stop"

$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $Repo "logs"
$BackendScript = Join-Path $PSScriptRoot "run_backend_windows.ps1"
$ClientScript = Join-Path $PSScriptRoot "run_kinect_client_windows.ps1"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Stop-ExistingKinectVoice {
    $currentPid = $PID
    $excludedPids = [System.Collections.Generic.HashSet[int]]::new()
    [void]$excludedPids.Add($currentPid)

    $cursor = Get-CimInstance Win32_Process -Filter "ProcessId = $currentPid" -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 4 -and $cursor -and $cursor.ParentProcessId; $i++) {
        [void]$excludedPids.Add([int]$cursor.ParentProcessId)
        $cursor = Get-CimInstance Win32_Process -Filter "ProcessId = $($cursor.ParentProcessId)" -ErrorAction SilentlyContinue
    }

    $patterns = @(
        "*voicepe-realtime-backend_OC*run_backend_windows.ps1*",
        "*voicepe-realtime-backend_OC*run_kinect_client_windows.ps1*",
        "*voicepe-realtime-backend_OC*kinect_windows_client.py*",
        "*voicepe-realtime-backend_OC*app.main*"
    )
    Get-CimInstance Win32_Process |
        Where-Object {
            $cmd = $_.CommandLine
            -not $excludedPids.Contains([int]$_.ProcessId) -and
            $cmd -and
            ($patterns | Where-Object { $cmd -like $_ })
        } |
        ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            } catch {
                Add-Content -Path (Join-Path $LogDir "startup.log") -Value "Could not stop PID $($_.ProcessId): $($_.Exception.Message)"
            }
        }
}

function Wait-Backend {
    param([int]$TimeoutSeconds = 90)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path (Join-Path $LogDir "startup.log") -Value "[$stamp] Starting Kinect Voice"

Stop-ExistingKinectVoice

Start-Process -FilePath powershell.exe -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $BackendScript
) -WorkingDirectory $Repo -WindowStyle Hidden

if (-not (Wait-Backend -TimeoutSeconds 90)) {
    Add-Content -Path (Join-Path $LogDir "startup.log") -Value "[$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")] Backend did not open port 8080"
    exit 1
}

Start-Process -FilePath powershell.exe -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $ClientScript
) -WorkingDirectory $Repo -WindowStyle Hidden

Add-Content -Path (Join-Path $LogDir "startup.log") -Value "[$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")] Kinect Voice started"

