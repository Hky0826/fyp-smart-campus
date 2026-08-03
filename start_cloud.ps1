[CmdletBinding()]
param(
    [switch]$Reload,
    [switch]$SkipNotificationWorker,
    [int]$Port = 8000,
    [string]$BindAddress = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$redisContainer = "smart-campus-redis"

function Stop-WithMessage([string]$Message) {
    Write-Error $Message
    exit 1
}

if (-not (Test-Path -LiteralPath $python)) {
    Stop-WithMessage "The project virtual environment was not found. Create it first with: python -m venv .venv"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-WithMessage "Docker CLI was not found. Install/start Docker Desktop, then run .\start_cloud.ps1 again."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "Docker Desktop is not running. Start Docker Desktop, wait until it is ready, then retry."
}

$containerNames = @(docker ps -a --filter "name=^$redisContainer`$" --format "{{.Names}}")
if ($containerNames -notcontains $redisContainer) {
    Write-Host "Creating local Redis container..." -ForegroundColor Cyan
    docker run -d --name $redisContainer -p "127.0.0.1:6379:6379" --restart unless-stopped redis:7-alpine | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "Redis container creation failed. Check Docker Desktop and whether port 6379 is already in use."
    }
} else {
    $runningNames = @(docker ps --filter "name=^$redisContainer`$" --format "{{.Names}}")
    if ($runningNames -notcontains $redisContainer) {
        Write-Host "Starting existing Redis container..." -ForegroundColor Cyan
        docker start $redisContainer | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Stop-WithMessage "The existing Redis container could not be started."
        }
    }
}

$redisReady = $false
for ($attempt = 1; $attempt -le 15; $attempt++) {
    $ping = docker exec $redisContainer redis-cli ping 2>$null
    if ($LASTEXITCODE -eq 0 -and $ping -match "PONG") {
        $redisReady = $true
        break
    }
    Start-Sleep -Milliseconds 500
}
if (-not $redisReady) {
    Stop-WithMessage "Redis did not become ready. Check: docker logs $redisContainer"
}

# This launcher is for local development. Point the config loader at a
# development-only path so an old production secret store cannot override the
# checked-out development .env file. Development credentials remain untracked.
$developmentSecretPath = Join-Path $env:USERPROFILE ".smart-campus-cloud\development-secrets.env"
$env:CLOUD_SECRET_STORE_PATH = $developmentSecretPath
$env:APP_ENV = "development"
$env:COOKIE_SECURE = "false"

# Read only connection coordinates from the backend .env for an early, clear
# failure.  Passwords and other secrets are never printed by this script.
$envFile = Join-Path $repoRoot "cloud\dashboard\backend\.env"
$dbHost = "localhost"
$dbPort = 3306
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*DB_HOST\s*=\s*(.*?)\s*$') { $dbHost = $matches[1].Trim() }
        if ($line -match '^\s*DB_PORT\s*=\s*(\d+)\s*$') { $dbPort = [int]$matches[1] }
    }
}
$dbTest = Test-NetConnection -ComputerName $dbHost -Port $dbPort -WarningAction SilentlyContinue
if (-not $dbTest.TcpTestSucceeded) {
    Stop-WithMessage "MySQL is not reachable at ${dbHost}:${dbPort}. Start MySQL and verify cloud\dashboard\backend\.env."
}

Write-Host "Preparing the cloud database (safe to repeat)..." -ForegroundColor Cyan
& $python (Join-Path $repoRoot "cloud\dashboard\backend\scripts\prepare_cloud.py")
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "Cloud database preparation failed. No backend process was started."
}

$uvicornArgs = @(
    "-m", "uvicorn",
    "cloud.dashboard.backend.app.main:app",
    "--host", $BindAddress,
    "--port", $Port.ToString()
)
$env:PYTHONPATH = "$repoRoot\cloud\dashboard\backend;$repoRoot\cloud"
if (-not $SkipNotificationWorker) {
    Write-Host "Starting the background notification worker..." -ForegroundColor Cyan
    Start-Process -WindowStyle Hidden -FilePath $python -ArgumentList @(
        "-m", "cloud.mapping_and_notification.workers.notification_worker"
    ) -WorkingDirectory $repoRoot | Out-Null
}
if ($Reload) {
    $uvicornArgs += @("--reload", "--reload-dir", (Join-Path $repoRoot "cloud"))
}

Write-Host "Cloud development backend is starting at http://$BindAddress`:$Port" -ForegroundColor Green
Write-Host "Dashboard: http://localhost`:$Port/dashboard/" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the cloud backend."
& $python @uvicornArgs
exit $LASTEXITCODE
