[CmdletBinding()]
param(
    [switch]$Reload,
    [switch]$SkipNotificationWorker,
    [switch]$StartNotificationWorker,
    [int]$Port = 8000,
    [string]$BindAddress = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$redisContainer = "smart-campus-redis"
$rabbitmqContainer = "smart-campus-rabbitmq"
$envFile = Join-Path $repoRoot "cloud\dashboard\backend\.env"

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

# The notification worker uses RabbitMQ by default. Start a local broker when
# no external broker URL is configured; deployments can provide RABBITMQ_URL.
$rabbitmqUrl = $env:RABBITMQ_URL
if (-not $rabbitmqUrl -and (Test-Path -LiteralPath $envFile)) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*RABBITMQ_URL\s*=\s*(.*?)\s*$') {
            $rabbitmqUrl = $matches[1].Trim()
            break
        }
    }
}

if (-not $rabbitmqUrl) {
    $rabbitmqReady = Test-NetConnection -ComputerName 127.0.0.1 -Port 5672 -WarningAction SilentlyContinue
    if (-not $rabbitmqReady.TcpTestSucceeded) {
        $rabbitmqNames = @(docker ps -a --filter "name=^$rabbitmqContainer`$" --format "{{.Names}}")
        if ($rabbitmqNames -notcontains $rabbitmqContainer) {
            Write-Host "Creating local RabbitMQ container..." -ForegroundColor Cyan
            docker run -d --name $rabbitmqContainer -p "127.0.0.1:5672:5672" -p "127.0.0.1:15672:15672" --restart unless-stopped rabbitmq:3-management | Out-Host
            if ($LASTEXITCODE -ne 0) {
                Stop-WithMessage "RabbitMQ container creation failed. Check whether port 5672 is already in use."
            }
        } else {
            $runningRabbitmq = @(docker ps --filter "name=^$rabbitmqContainer`$" --format "{{.Names}}")
            if ($runningRabbitmq -notcontains $rabbitmqContainer) {
                Write-Host "Starting existing RabbitMQ container..." -ForegroundColor Cyan
                docker start $rabbitmqContainer | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    Stop-WithMessage "The existing RabbitMQ container could not be started."
                }
            }
        }
    }

    $rabbitmqReady = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $rabbitmqReady = Test-NetConnection -ComputerName 127.0.0.1 -Port 5672 -WarningAction SilentlyContinue
        if ($rabbitmqReady.TcpTestSucceeded) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $rabbitmqReady.TcpTestSucceeded) {
        Stop-WithMessage "RabbitMQ did not become ready. Check: docker logs $rabbitmqContainer"
    }
}

# This launcher is for local development. Point the config loader at a
# development-only path so an old production secret store cannot override the
# checked-out development .env file. Development credentials remain untracked.
$developmentSecretPath = Join-Path $env:USERPROFILE ".smart-campus-cloud\development-secrets.env"
$env:CLOUD_SECRET_STORE_PATH = $developmentSecretPath
$env:APP_ENV = "development"
$env:COOKIE_SECURE = "false"

# Read only connection coordinates from the backend .env for an early, clear
# failure. Passwords and other secrets are never printed by this script.
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
if ($SkipNotificationWorker -and $StartNotificationWorker) {
    Stop-WithMessage "Use either -SkipNotificationWorker or -StartNotificationWorker, not both."
}
if ($StartNotificationWorker -or -not $SkipNotificationWorker) {
    & $python -c "import pika" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "The notification worker dependency 'pika' is missing from .venv. Install cloud\dashboard\backend\requirements.txt, then retry."
    }

    try {
        $existingNodeServices = @(Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" | Where-Object { $_.CommandLine -match 'mapping_and_notification[\\/]backend' })
        foreach ($proc in $existingNodeServices) {
            Write-Host "Stopping existing Mapping Microservice (PID $($proc.ProcessId))..." -ForegroundColor DarkCyan
            Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Warning "Could not inspect existing node processes."
    }

    Write-Host "Starting Node.js Mapping Microservice on port 5000..." -ForegroundColor Cyan
    $mappingServiceProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath "node" -ArgumentList @(
        "index.js"
    ) -WorkingDirectory (Join-Path $repoRoot "mapping_and_notification\backend")
    Start-Sleep -Seconds 1

    Write-Host "Starting background notification worker/consumer..." -ForegroundColor Cyan
    $workerProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath "node" -ArgumentList @(
        "consumer.js"
    ) -WorkingDirectory (Join-Path $repoRoot "mapping_and_notification\backend")
    Start-Sleep -Seconds 1

    Write-Host "Starting Python AI Microservice on port 8001..." -ForegroundColor Cyan
    $aiServiceDir = Join-Path $repoRoot "mapping_and_notification\ai-services"
    $aiVenvPython = Join-Path $aiServiceDir "venv\Scripts\python.exe"
    $aiPython = if (Test-Path -LiteralPath $aiVenvPython) { $aiVenvPython } else { $python }
    $aiProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath $aiPython -ArgumentList @(
        "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", "8001"
    ) -WorkingDirectory $aiServiceDir
    Start-Sleep -Seconds 1
}
if ($Reload) {
    $uvicornArgs += @("--reload", "--reload-dir", (Join-Path $repoRoot "cloud"))
}

Write-Host "Cloud development backend is starting at http://$BindAddress`:$Port" -ForegroundColor Green
Write-Host "Dashboard: http://localhost`:$Port/dashboard/" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the cloud backend."
try {
    & $python @uvicornArgs
} finally {
    Write-Host "`nStopping background microservices..." -ForegroundColor DarkCyan
    if ($mappingServiceProcess -and -not $mappingServiceProcess.HasExited) {
        Stop-Process -Id $mappingServiceProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($workerProcess -and -not $workerProcess.HasExited) {
        Stop-Process -Id $workerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($aiProcess -and -not $aiProcess.HasExited) {
        Stop-Process -Id $aiProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
exit $LASTEXITCODE
