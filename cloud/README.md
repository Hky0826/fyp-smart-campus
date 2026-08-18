# Smart Campus Cloud Central Server

This directory contains the central server application components for the Smart Campus system, including the administrative dashboard backend & frontend, the RAG chatbot query services, synchronization API routers, and notification workers.

---

## 1. Prerequisites

Before running the server for the first time, ensure you have the following installed on your machine:

- **Python 3.11+**: Download from [python.org](https://www.python.org/).
- **Docker Desktop** (Recommended): Required for running Redis (rate limiting & session caching) and optionally MySQL. Download from [docker.com](https://www.docker.com/).
- **MySQL Server 8.0 / 9.0+**: Either installed natively as a Windows service or running via a Docker container.
- **Node.js 18+ & npm** (Optional): Only required if you intend to rebuild or develop the administrative dashboard frontend (`cloud/dashboard/frontend`).

---

## 2. First-Time Setup Guide

### Quick Start: Automated Setup Script (Recommended)

From the repository root (`Code_FYP`), run the setup script to automatically create the Python virtual environment, install dependencies, copy `.env`, generate secure keys, launch the Redis Docker container, check MySQL, and prepare the database:

```powershell
.\setup_cloud.ps1
```

*Or double-click `setup_cloud.bat` in Windows File Explorer.*

---

### Step-by-Step Manual Setup

#### A. Python Virtual Environment Setup

Create and activate a Python virtual environment from the repository root (`Code_FYP`):

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

Install all cloud backend dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r cloud/requirements.txt
```

---

### B. Redis Setup (Docker & Native)

Redis is required by the cloud backend for rate limiting, session storage, and asynchronous event processing (`RATE_LIMIT_REDIS_URL`).

#### Option 1: Automatic Redis via Docker (Recommended for Windows)
If Docker Desktop is running, the included `start_cloud.ps1` script automatically checks for and launches a Redis container named `smart-campus-redis`. No manual command is required!

#### Option 2: Manual Docker Redis Command
To start the Redis container manually:

```powershell
docker run -d --name smart-campus-redis -p 127.0.0.1:6379:6379 --restart unless-stopped redis:7-alpine
```

To check if Redis is running:

```powershell
docker ps --filter "name=smart-campus-redis"
docker exec -it smart-campus-redis redis-cli ping
# Expected output: PONG
```

#### Option 3: Native Redis (Linux / WSL)
On Linux or WSL:

```bash
sudo apt update
sudo apt install redis-server
sudo service redis-server start
redis-cli ping
```

---

### C. MySQL Database Setup

The cloud backend requires a MySQL database named `smart_campus_db`.

#### Option 1: Local Native Installation
1. Install [MySQL Installer for Windows](https://dev.mysql.com/downloads/installer/).
2. Keep the default port `3306`.
3. Ensure the MySQL Windows service (e.g. `MySQL97` or `MySQL80`) is running.

#### Option 2: Docker MySQL Container
```powershell
docker run -d --name smart-campus-mysql -e MYSQL_ROOT_PASSWORD=your_mysql_password -p 3306:3306 mysql:9.0
```

---

### D. Environment Configuration (`.env`)

Create your `.env` configuration file by copying the example template:

```powershell
# Copy from repository root
copy cloud\dashboard\backend\.env.example cloud\dashboard\backend\.env
```

Edit `cloud/dashboard/backend/.env` with your database, Redis, and security secrets:

```ini
# Core Environment Settings
APP_ENV=development
COOKIE_SECURE=false

# Database Configuration
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=smart_campus_db

# Redis Rate Limiting & Caching
RATE_LIMIT_REDIS_URL=redis://127.0.0.1:6379/0

# Security Secrets (Must be at least 32 characters for JWT)
JWT_SECRET=your_super_secret_jwt_key_here_min_32_chars
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120
DEVICE_CREDENTIAL_KEY=your_fernet_encryption_key_here

# RAG & Gemini API Configuration
GEMINI_API_KEY=your_gemini_api_key_here

# Dashboard Origins
DASHBOARD_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

> **Tip:** You can generate secure secrets using Python:
> ```powershell
> # JWT Secret
> python -c "import secrets; print(secrets.token_urlsafe(48))"
> # Fernet Device Credential Key
> python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
> ```

---

### E. Database Initialization & Schema Setup

Run the safe cloud database preparer to create required tables and default roles without dropping existing data:

```powershell
python cloud\dashboard\backend\scripts\prepare_cloud.py
```

*Note:* For disposable development environments where you wish to drop all tables and seed fresh default data (superadmin user `admin`, reference buildings, roles), you can run:

```powershell
python cloud\dashboard\backend\app\db_init.py
```

---

### F. Dashboard Frontend Build (Optional)

The pre-built dashboard frontend static files reside in `cloud/dashboard/frontend/dist` and are served automatically by FastAPI under `/dashboard/`.

If you modify frontend code inside `cloud/dashboard/frontend`, rebuild the frontend assets:

```powershell
cd cloud\dashboard\frontend
npm install
npm run build
cd ..\..\..
```

---

## 3. Running the Cloud Server

### Method A: One-Click Startup Script (Recommended)

Run the PowerShell launcher script from the project root directory (`Code_FYP`):

```powershell
# Normal startup
.\start_cloud.ps1

# Development mode with live auto-reload
.\start_cloud.ps1 -Reload

# The notification worker and local RabbitMQ broker start automatically
.\start_cloud.ps1 -Reload

# Optional: skip the worker when it is managed separately
.\start_cloud.ps1 -Reload -SkipNotificationWorker
```

*What `start_cloud.ps1` does automatically:*
1. Validates the Python `.venv` environment.
2. Checks Docker Desktop status and starts or creates the `smart-campus-redis` Docker container.
3. Tests Redis responsiveness (`PONG`).
4. Verifies connectivity to MySQL on port `3306`.
5. Prepares database tables safely using `prepare_cloud.py`.
6. Starts the local RabbitMQ broker when `RABBITMQ_URL` is not configured.
7. Starts the notification worker.
8. Launches Uvicorn server on `http://127.0.0.1:8000`.

*Alternatively, you can double-click `start_cloud.bat` in Windows File Explorer.*

---

### Method B: Manual Command-Line Startup

If running manually without the PowerShell script, execute the following steps from the repository root:

1. **Start Redis**:
   ```powershell
   docker start smart-campus-redis
   ```
2. **Prepare DB**:
   ```powershell
   python cloud\dashboard\backend\scripts\prepare_cloud.py
   ```
3. **Start FastAPI Uvicorn Server**:
   ```powershell
   python -m uvicorn cloud.dashboard.backend.app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
4. **Start Mapping & Navigation Microservice (Node.js)**:
   ```powershell
   cd cloud\mapping_microservice
   npm start
   ```
5. **(Optional) Start Notification Worker (Node.js)**:
   ```powershell
   cd cloud\mapping_microservice
   npm run worker
   ```

---

## 4. Access Points & Verification

Once the backend server is running:

- **Admin Dashboard UI**: [http://localhost:8000/dashboard/](http://localhost:8000/dashboard/)
- **Interactive OpenAPI Docs (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc API Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **RAG Chatbot Health Check**: [http://localhost:8000/api/chatbot/health](http://localhost:8000/api/chatbot/health)

---

## 5. Registered Synchronization & Chatbot Endpoints

The synchronization and central application server exposes the following API modules:

### A. Downstream Router (`/api/sync/downstream`)
- `POST /register`: Accepts LAN IP, port, and node configurations from edge nodes for push notifications.
- `GET /delta`: Distributes database delta updates (users, roles, RBAC changes) since a given ISO timestamp.
- `POST /deactivate`: Admin command endpoint to deactivate a user profile and dispatch instant push notifications to edge clients.

### B. Upstream Router (`/api/sync/upstream`)
- `POST /logs`: Collects batches of offline-buffered authentication events, appends them to cloud logs, and updates the user's last known location and timestamp inside single transaction blocks.
- `POST /heartbeat`: Registers client keep-alive pings and logs client IP addresses.

### C. RAG Chatbot Router (`/api/chatbot`)
- `POST /chat`: Returns one complete RAG chatbot response as JSON. Without JWT, the request uses visitor/PUBLIC access.
- `POST /chat/stream`: Streams the same chatbot response as Server-Sent Events for edge audio playback. Without JWT, the request uses visitor/PUBLIC access.
- `POST /chat/audio`: Accepts edge audio, returns the cloud transcription, chatbot text response, optional base64 PCM TTS audio, sources, and status.
- `POST /chat/public-smoke-test`: Optional no-JWT PUBLIC-only RAG smoke test.
- `POST /chat/public-smoke-test/stream`: Optional no-JWT PUBLIC-only RAG smoke test as Server-Sent Events.
- `GET /health`: Reports chatbot health and Google API configuration status.

The edge audio pipeline calls `POST /api/chatbot/chat/audio` with a multipart `audio` file plus optional `device_id` and `session_id`. The cloud transcribes the audio with Gemini 3.1 Lite, checks the transcription for prompt injection, embeds validated input with Gemini Embedding 2, generates the grounded RAG answer with Gemini 3.1 Lite, and converts the answer to speech with Gemini 2.5 Flash TTS. If the edge has a face-auth JWT, it also sends `Authorization: Bearer <JWT>` to unlock RBAC levels above visitor/PUBLIC. If it has no JWT, the chatbot can still answer using PUBLIC documents.

To enable public smoke test endpoints for testing:

```ini
RAG_ENABLE_PUBLIC_SMOKE_TEST=1
```

---

## 6. Troubleshooting

### 1. `Docker CLI was not found` or `Docker Desktop is not running`
- **Cause**: Docker Desktop is closed or not installed.
- **Solution**: Open Docker Desktop and wait until the engine is running before executing `.\start_cloud.ps1` or manual `docker run` commands.

### 2. `Redis container creation failed` / Port 6379 in use
- **Cause**: Another service or container is already bound to port `6379`.
- **Solution**: Stop any local Redis services (`Stop-Service redis` or `docker stop <other-redis-container>`).

### 3. `MySQL is not reachable at localhost:3306`
- **Cause**: MySQL server service is stopped or invalid `.env` DB host/port settings.
- **Solution**: Open `services.msc` and start **MySQL97** (or `docker start smart-campus-mysql`), and check credentials in `cloud/dashboard/backend/.env`.

### 4. Cloud Startup Fails with Secret Errors (`JWT_SECRET` / `DEVICE_CREDENTIAL_KEY`)
- **Cause**: `JWT_SECRET` is too short (< 32 characters) or `DEVICE_CREDENTIAL_KEY` is not a valid Fernet key.
- **Solution**: Generate proper keys using the Python snippet in Section 2.D and update `.env`.
