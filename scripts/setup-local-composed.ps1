<#
.SYNOPSIS
  Windows setup for the local/free composed TrueFit pipeline.

.DESCRIPTION
  Native PowerShell counterpart to setup-local-composed.sh. It detects the
  Windows CPU architecture, uses the project venv, and expects PostgreSQL,
  Redis, Ollama, Node and pnpm to be installed through winget/Chocolatey or
  another package manager.

.EXAMPLE
  .\scripts\setup-local-composed.ps1 -SkipModels
#>

[CmdletBinding()]
param(
  [switch]$SkipModels,
  [string]$OllamaModel = "qwen2.5:7b"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
Write-Host "[setup] Detected platform: Windows / $Arch"
$DbPort = 5432
$DbUser = "postgres"

function Require-Command([string]$Name, [string]$Hint = "") {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    $message = "Missing '$Name'. Install it and re-run."
    if ($Hint) { $message += " $Hint" }
    throw $message
  }
}

Require-Command "python" "Python 3.11+ is required."
Require-Command "node"
Require-Command "pnpm"
Require-Command "psql" "Install PostgreSQL client/server tools."
Require-Command "createdb" "Install PostgreSQL client/server tools."
Require-Command "pg_isready" "Install PostgreSQL client/server tools."
Require-Command "redis-cli" "Install Redis or run it through WSL/Docker."
Require-Command "ollama" "Install Ollama for Windows."

$PythonVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$PythonVersion -lt [version]"3.11") { throw "Python $PythonVersion is too old; Python 3.11+ is required." }

$RedisReady = (& redis-cli ping 2>$null) -contains "PONG"
if (-not $RedisReady) { throw "Redis is not responding. Start Redis and re-run." }

$PgReady = (& pg_isready -q 2>$null; $LASTEXITCODE -eq 0)
if (-not $PgReady) {
  if (Get-Command pg_ctl -ErrorAction SilentlyContinue) {
    $PgData = Join-Path $env:LOCALAPPDATA "truefit-pgdata"
    $PgPort = 5433
    if (-not (Test-Path (Join-Path $PgData "PG_VERSION"))) {
      & initdb -D $PgData --auth=trust -U postgres | Out-Null
    }
    & pg_ctl -D $PgData -o "-p $PgPort" -l (Join-Path $PgData "server.log") start | Out-Null
    $DbPort = $PgPort
  } else {
    throw "PostgreSQL is not responding and pg_ctl is unavailable. Start PostgreSQL and re-run."
  }
}

$Venv = Join-Path $Root "examples\truefit\backend\.venv"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
  & python -m venv $Venv
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$VenvPip = Join-Path $Venv "Scripts\pip.exe"
& $VenvPip install --upgrade pip --quiet
Push-Location (Join-Path $Root "examples\truefit\backend")
& $VenvPip install -r requirements.txt
Pop-Location

Push-Location (Join-Path $Root "examples\truefit\frontend")
& pnpm install
Pop-Location

$BackendEnv = Join-Path $Root "examples\truefit\backend\.env"
$ExampleEnv = Join-Path $Root "examples\truefit\backend\env.example"
if (-not (Test-Path $BackendEnv)) { Copy-Item $ExampleEnv $BackendEnv }

& createdb -h 127.0.0.1 -p $DbPort -U $DbUser truefit_db 2>$null

function Set-EnvValue([string]$Key, [string]$Value) {
  $content = Get-Content $BackendEnv -Raw
  $line = "$Key=$Value"
  if ($content -match "(?m)^$Key=.*$") {
    $content = [regex]::Replace($content, "(?m)^$Key=.*$", [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $line }, 1)
  } else {
    $content = $content.TrimEnd() + "`n$line`n"
  }
  Set-Content -Path $BackendEnv -Value $content -NoNewline
}

Set-EnvValue "LLM_PRIMARY_PROVIDER" "composed"
Set-EnvValue "DATABASE_URL" "postgresql+asyncpg://$DbUser@127.0.0.1:$DbPort/truefit_db"
Set-EnvValue "COMPOSED_LLM_BASE_URL" "http://127.0.0.1:11434/v1"
Set-EnvValue "COMPOSED_LLM_MODEL" $OllamaModel
Set-EnvValue "COMPOSED_STT_MODEL" "base.en"

if (-not $SkipModels) {
  $VoiceDir = Join-Path $Root "examples\truefit\backend\models\piper"
  New-Item -ItemType Directory -Force $VoiceDir | Out-Null
  $VoiceBase = Join-Path $VoiceDir "en_US-lessac-medium"
  foreach ($Extension in @(".onnx", ".onnx.json")) {
    $Target = "$VoiceBase$Extension"
    if (-not (Test-Path $Target)) {
      Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium$Extension" -OutFile $Target
    }
  }
  & $VenvPython -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')"
  if (-not ((Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -ErrorAction SilentlyContinue))) {
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
  }
  & ollama pull $OllamaModel
  Set-EnvValue "COMPOSED_TTS_VOICE" "$VoiceBase.onnx"
}

Push-Location (Join-Path $Root "examples\truefit\backend")
& $VenvPython -m alembic upgrade head
foreach ($Module in @("faster_whisper", "piper", "onnxruntime", "numpy", "httpx", "soro")) {
  & $VenvPython -c "import $Module"
}
Pop-Location

Write-Host "[ok] Local setup complete for Windows / $Arch"
Write-Host "     Run: make dev (Git Bash) or examples\truefit\backend\.venv\Scripts\python.exe run.py"
