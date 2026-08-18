[CmdletBinding()]
param(
    [switch]$SkipFrontendBuild,
    [switch]$ForceReinstall,
    [switch]$InstallDocker,
    [string]$DbPassword = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Smart Campus Cloud Central Server First-Time Setup       " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

function Write-Step([string]$Message) {
    Write-Host "[+] $Message" -ForegroundColor Green
}

function Write-Info([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Gray
}

function Write-Warn([string]$Message) {
    Write-Host "[!] $Message" -ForegroundColor Yellow
}

function Stop-WithMessage([string]$Message) {
    Write-Host "[X] ERROR: $Message" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 1. Python & Virtual Environment Setup
# ---------------------------------------------------------------------------
Write-Step "Checking Python environment..."

$venvDir = Join-Path $repoRoot ".venv"
$python = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Info "Virtual environment not found. Creating .venv..."
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $systemPython) {
        Stop-WithMessage "Python binary was not found on PATH. Please install Python 3.11+ first."
    }
    
    & python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "Failed to create Python virtual environment."
    }
    Write-Info "Virtual environment created at: $venvDir"
} else {
    Write-Info "Virtual environment found at: $venvDir"
}

Write-Step "Installing/upgrading Python cloud requirements..."
& $python -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Could not upgrade pip, continuing with existing version."
}

$cloudReqs = Join-Path $repoRoot "cloud\requirements.txt"
if (Test-Path -LiteralPath $cloudReqs) {
    Write-Info "Installing dependencies from cloud\requirements.txt..."
    & $python -m pip install -r $cloudReqs --quiet
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "Failed to install Python dependencies from cloud\requirements.txt"
    }
    Write-Info "Python packages installed successfully."
} else {
    Write-Warn "cloud\requirements.txt not found! Skipping package installation."
}

# ---------------------------------------------------------------------------
# 2. Environment Configuration (.env) Setup
# ---------------------------------------------------------------------------
Write-Step "Configuring Environment (.env)..."

$envDir = Join-Path $repoRoot "cloud\dashboard\backend"
$envFile = Join-Path $envDir ".env"
$envExample = Join-Path $envDir ".env.example"

if (-not (Test-Path -LiteralPath $envFile)) {
    if (Test-Path -LiteralPath $envExample) {
        Write-Info "Copying .env.example -> .env..."
        Copy-Item -Path $envExample -Destination $envFile
    } else {
        Write-Warn ".env.example not found! Creating default .env file..."
        $defaultEnv = @"
APP_ENV=development
COOKIE_SECURE=false
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=smart_campus_db
RATE_LIMIT_REDIS_URL=redis://127.0.0.1:6379/0
JWT_SECRET=your_super_secret_jwt_key_here_min_32_chars
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120
DEVICE_CREDENTIAL_KEY=your_fernet_encryption_key_here
DASHBOARD_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
"@
        Set-Content -Path $envFile -Value $defaultEnv -Encoding UTF8
    }
}

# Inject DB Password if provided via CLI
if ($DbPassword -ne "") {
    Write-Info "Updating DB_PASSWORD in .env..."
    $content = Get-Content -LiteralPath $envFile
    $updatedContent = $content | ForEach-Object {
        if ($_ -match '^\s*DB_PASSWORD\s*=') { "DB_PASSWORD=$DbPassword" } else { $_ }
    }
    Set-Content -Path $envFile -Value $updatedContent -Encoding UTF8
}

# Auto-generate JWT_SECRET and DEVICE_CREDENTIAL_KEY if placeholder values exist
Write-Info "Checking security keys in .env..."
$genKeysScript = @"
import sys, re
from secrets import token_urlsafe
try:
    from cryptography.fernet import Fernet
    fernet_key = Fernet.generate_key().decode()
except Exception:
    fernet_key = token_urlsafe(32)

env_path = sys.argv[1]
with open(env_path, 'r', encoding='utf-8') as f:
    content = f.read()

jwt_placeholder = re.search(r'JWT_SECRET\s*=\s*(.*)', content)
if not jwt_placeholder or 'your_super_secret' in jwt_placeholder.group(1) or len(jwt_placeholder.group(1).strip()) < 16:
    new_jwt = token_urlsafe(48)
    content = re.sub(r'JWT_SECRET\s*=.*', f'JWT_SECRET={new_jwt}', content)
    print('Generated new secure JWT_SECRET.')

dev_placeholder = re.search(r'DEVICE_CREDENTIAL_KEY\s*=\s*(.*)', content)
if not dev_placeholder or 'your_fernet' in dev_placeholder.group(1) or len(dev_placeholder.group(1).strip()) < 16:
    content = re.sub(r'DEVICE_CREDENTIAL_KEY\s*=.*', f'DEVICE_CREDENTIAL_KEY={fernet_key}', content)
    print('Generated new DEVICE_CREDENTIAL_KEY.')

with open(env_path, 'w', encoding='utf-8') as f:
    f.write(content)
"@

& $python -c $genKeysScript $envFile
Write-Info "Environment configuration ready at: $envFile"

# ---------------------------------------------------------------------------
# 3. Docker & Redis Container Setup
# ---------------------------------------------------------------------------
Write-Step "Configuring Docker & Redis Service..."

$redisContainer = "smart-campus-redis"
$dockerAvailable = $false

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Warn "Docker CLI was not found on your system."
    if ($InstallDocker -or (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Step "Attempting to install Docker Desktop via Windows Package Manager (winget)..."
        try {
            winget install --id Docker.DockerDesktop -e --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -eq 0) {
                Write-Info "Docker Desktop installation completed."
                Write-Warn "Please launch Docker Desktop from the Start Menu, complete any initial setup/restart, then re-run setup_cloud.ps1."
            } else {
                Write-Warn "winget installation exited with code $LASTEXITCODE. You can manually download Docker Desktop from: https://www.docker.com/products/docker-desktop/"
            }
        } catch {
            Write-Warn "Could not execute winget. Download Docker Desktop manually from: https://www.docker.com/products/docker-desktop/"
        }
    } else {
        Write-Warn "Download Docker Desktop manually from: https://www.docker.com/products/docker-desktop/"
    }
} else {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) {
        $dockerAvailable = $true
    } else {
        Write-Warn "Docker Desktop is installed but not currently running. Please launch Docker Desktop."
    }
}

if ($dockerAvailable) {
    $existingContainers = @(docker ps -a --filter "name=^$redisContainer`$" --format "{{.Names}}")
    if ($existingContainers -notcontains $redisContainer) {
        Write-Info "Creating and starting local Redis Docker container ($redisContainer)..."
        docker run -d --name $redisContainer -p "127.0.0.1:6379:6379" --restart unless-stopped redis:7-alpine | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Could not create Redis Docker container. Port 6379 may be in use."
        }
    } else {
        $runningContainers = @(docker ps --filter "name=^$redisContainer`$" --format "{{.Names}}")
        if ($runningContainers -notcontains $redisContainer) {
            Write-Info "Starting existing Redis Docker container ($redisContainer)..."
            docker start $redisContainer | Out-Null
        } else {
            Write-Info "Redis Docker container is already running."
        }
    }

    # Ping Redis
    $redisReady = $false
    for ($i = 1; $i -le 10; $i++) {
        $ping = docker exec $redisContainer redis-cli ping 2>$null
        if ($LASTEXITCODE -eq 0 -and $ping -match "PONG") {
            $redisReady = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if ($redisReady) {
        Write-Info "Redis service is online and responding (PONG)."
    } else {
        Write-Warn "Redis container did not respond to ping. Please verify Docker container logs."
    }
} else {
    Write-Warn "Skipping Docker Redis auto-start. Ensure Redis is running locally at 127.0.0.1:6379."
}

# ---------------------------------------------------------------------------
# 4. MySQL Connectivity & Database Preparation
# ---------------------------------------------------------------------------
Write-Step "Checking MySQL Connection & Initializing Database..."

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
    Write-Warn "MySQL is not reachable at ${dbHost}:${dbPort}."
    if ($dockerAvailable) {
        Write-Info "Attempting to start/create a MySQL Docker container (smart-campus-mysql)..."
        $mysqlContainer = "smart-campus-mysql"
        $existingMysql = @(docker ps -a --filter "name=^$mysqlContainer`$" --format "{{.Names}}")
        if ($existingMysql -notcontains $mysqlContainer) {
            Write-Info "Spinning up MySQL 9.0 Docker container on port 3306..."
            docker run -d --name $mysqlContainer -e MYSQL_ROOT_PASSWORD=root -p "3306:3306" mysql:9.0 | Out-Null
            Write-Info "Waiting 10 seconds for MySQL container initialization..."
            Start-Sleep -Seconds 10
        } else {
            docker start $mysqlContainer | Out-Null
            Start-Sleep -Seconds 3
        }
        $dbTest = Test-NetConnection -ComputerName $dbHost -Port $dbPort -WarningAction SilentlyContinue
    }
}

if ($dbTest.TcpTestSucceeded) {
    Write-Info "MySQL connection verified at ${dbHost}:${dbPort}."
    Write-Info "Running database schema preparation script (prepare_cloud.py)..."
    & $python (Join-Path $repoRoot "cloud\dashboard\backend\scripts\prepare_cloud.py")
    if ($LASTEXITCODE -eq 0) {
        Write-Info "Database preparation completed successfully."
    } else {
        Write-Warn "prepare_cloud.py encountered an issue. Check database user/password in $envFile."
    }
} else {
    Write-Warn "MySQL is not reachable. Please start your MySQL service (e.g. Start-Service MySQL97) and run .\start_cloud.ps1"
}

# ---------------------------------------------------------------------------
# 5. Dashboard Frontend Setup (Optional)
# ---------------------------------------------------------------------------
if (-not $SkipFrontendBuild) {
    Write-Step "Checking Dashboard Frontend Assets..."
    $frontendDir = Join-Path $repoRoot "cloud\dashboard\frontend"
    $distDir = Join-Path $frontendDir "dist"
    
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        # Mapping Microservice setup
        $mappingBackendDir = Join-Path $repoRoot "mapping_and_notification\backend"
        $mappingFrontendDir = Join-Path $repoRoot "mapping_and_notification\frontend"
        if (Test-Path -LiteralPath $mappingBackendDir) {
            Write-Info "Installing dependencies for Mapping Microservice Backend..."
            Push-Location $mappingBackendDir
            try {
                npm install --quiet
                Write-Info "Mapping Backend dependencies installed successfully."
            } catch {
                Write-Warn "Failed to install mapping backend dependencies."
            } finally {
                Pop-Location
            }
        }
        if (Test-Path -LiteralPath $mappingFrontendDir) {
            Write-Info "Installing dependencies for Mapping Microservice Frontend..."
            Push-Location $mappingFrontendDir
            try {
                npm install --quiet
                Write-Info "Mapping Frontend dependencies installed successfully."
            } catch {
                Write-Warn "Failed to install mapping frontend dependencies."
            } finally {
                Pop-Location
            }
        }

        if (-not (Test-Path -LiteralPath $distDir)) {
            Write-Info "Building dashboard frontend static assets (npm run build)..."
            Push-Location $frontendDir
            try {
                npm install --quiet
                npm run build
                Write-Info "Dashboard frontend assets built successfully."
            } catch {
                Write-Warn "Frontend build encountered warnings/errors, but pre-built fallback may exist."
            } finally {
                Pop-Location
            }
        } else {
            Write-Info "Frontend build directory exists at cloud\dashboard\frontend\dist."
        }
    } else {
        Write-Info "Node.js / npm not found on PATH. Using existing static dashboard build."
    }

    # Ensure floorplan images are synced into mapping microservice uploads
    $floorplanSource = Join-Path $repoRoot "floorplan"
    $backendUploads = Join-Path $repoRoot "mapping_and_notification\backend\uploads"
    if (Test-Path -LiteralPath $floorplanSource) {
        if (-not (Test-Path -LiteralPath $backendUploads)) { New-Item -ItemType Directory -Path $backendUploads -Force | Out-Null }
        Copy-Item -Path (Join-Path $floorplanSource "*.jpeg") -Destination $backendUploads -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# Setup Summary Banner
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "   FIRST-TIME SETUP COMPLETE!                               " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start the cloud server now, run:" -ForegroundColor White
Write-Host "  .\start_cloud.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "To start with live code auto-reload:" -ForegroundColor White
Write-Host "  .\start_cloud.ps1 -Reload" -ForegroundColor Yellow
Write-Host ""
Write-Host "Dashboard URL: http://localhost:8000/dashboard/" -ForegroundColor Cyan
Write-Host "API Swagger Docs: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
