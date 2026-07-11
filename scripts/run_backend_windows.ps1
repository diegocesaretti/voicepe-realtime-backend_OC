$ErrorActionPreference = "Stop"

$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$AppDir = Join-Path $Repo "openai_realtime_voice_agent"
$Python = Join-Path $Repo ".venv-backend\Scripts\python.exe"
$LogDir = Join-Path $Repo "logs"
$DataDir = Join-Path $Repo "data"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "voice-enrollment") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "enroll-prompts") | Out-Null

$OpenAiSecret = Get-Content -Raw "C:\Users\diego\.openclaw\secrets\openai.json" | ConvertFrom-Json
$env:OPENAI_API_KEY = $OpenAiSecret.api_key
$env:OPENCLAW_WORKSPACE = "C:\Users\diego\.openclaw\workspace"
$env:HOMEASSISTANT_SECRET_PATH = "C:\Users\diego\.openclaw\secrets\homeassistant.json"
$env:WEBSOCKET_HOST = "127.0.0.1"
$env:WEBSOCKET_PORT = "8080"
$env:ENABLE_OPENCLAW_TOOLS = "true"
$env:TRANSCRIPTION_LANGUAGE = "es"
$env:ENROLL_DIR = Join-Path $DataDir "voice-enrollment"
$env:ENROLL_PROMPT_CACHE_DIR = Join-Path $DataDir "enroll-prompts"
$env:ENROLLMENT_PHRASE = "hey jarvis"
$env:INSTRUCTIONS = "Sos Jarvis, asistente personal y de BWA 3D de Diego. HablÃ¡ en espaÃ±ol rioplatense, breve y natural. PodÃ©s ayudar con OpenClaw y controlar Home Assistant usando solo tools seguras."

Set-Location $AppDir
$ErrorActionPreference = "Continue"
& $Python -m app.main *> (Join-Path $LogDir "backend.combined.log")

