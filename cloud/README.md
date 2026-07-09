# Smart Campus Cloud Central Server Setup

This directory contains the central server application components, including the administrative dashboard backend, the RAG chatbot query services, and the synchronization API routers.

---

## 1. Prerequisites

Before running the server, ensure you have initialized the database and configured the environment.

### A. Environment Configuration
Create or edit the `.env` file located in `cloud/dashboard/backend/.env` with your database credentials:
```ini
# Database configurations
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=smart_campus_db

# Security configurations
JWT_SECRET=your_super_secret_jwt_key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120
```

### B. Python Virtual Environment
Create or activate a virtual environment, then install the cloud backend dependencies:
```powershell
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

python -m pip install -r cloud/requirements.txt
```

---

## 2. Running the Cloud Server

Run the central server from the root of the project (`Code_FYP`):

```powershell
.venv\Scripts\python -m uvicorn cloud.dashboard.backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

* **`--host 0.0.0.0`**: Exposes the server to local area network (LAN) connections, allowing edge devices to submit logs and retrieve data.
* **`--port 8000`**: Runs the API gateway on port 8000.
* **`--reload`**: Enbles auto-reload of the server on script modification (development mode).

---

## 3. Registered Synchronization Endpoints

The synchronization server exposes the following API structures:

### A. Downstream Router (`/api/sync/downstream`)
* `POST /register`: Accepts LAN IP, port, and node configurations from edge nodes for push notifications.
* `GET /delta`: Distributes database delta updates (users, roles, RBAC changes) since a given ISO timestamp.
* `POST /deactivate`: Admin command endpoint to deactivate a user profile and dispatch instant push notifications to edge clients.

### B. Upstream Router (`/api/sync/upstream`)
* `POST /logs`: Collects batches of offline-buffered authentication events, appends them to cloud logs, and updates the user's last known location and timestamp inside single transaction blocks.
* `POST /heartbeat`: Registers client keep-alive pings and logs client IP addresses.

### C. RAG Chatbot Router (`/api/chatbot`)
* `POST /chat`: Returns one complete RAG chatbot response as JSON. Without JWT, the request uses visitor/PUBLIC access.
* `POST /chat/stream`: Streams the same chatbot response as Server-Sent Events for edge audio playback. Without JWT, the request uses visitor/PUBLIC access.
* `POST /chat/audio`: Accepts edge audio, returns the cloud transcription, chatbot text response, optional base64 PCM TTS audio, sources, and status.
* `POST /chat/public-smoke-test`: Optional no-JWT PUBLIC-only RAG smoke test.
* `POST /chat/public-smoke-test/stream`: Optional no-JWT PUBLIC-only RAG smoke test as Server-Sent Events.
* `GET /health`: Reports chatbot health and Google API configuration status.

The edge audio pipeline calls `POST /api/chatbot/chat/audio` with a multipart `audio` file plus optional `device_id` and `session_id`. The cloud transcribes the audio with Gemini 3.1 Lite, checks the transcription for prompt injection, embeds validated input with Gemini Embedding 2, generates the grounded RAG answer with Gemini 3.1 Lite, and converts the answer to speech with Gemini 2.5 Flash TTS. If the edge has a face-auth JWT, it also sends `Authorization: Bearer <JWT>` to unlock RBAC levels above visitor/PUBLIC. If it has no JWT, the chatbot can still answer using PUBLIC documents.

The public smoke-test endpoints are disabled by default. Enable them only for
diagnostics by setting this on the cloud backend before startup:

```ini
RAG_ENABLE_PUBLIC_SMOKE_TEST=1
```
