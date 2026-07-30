# Mapping and notification cloud context

This is the Python/FastAPI bounded context for campus floorplans, RBAC-aware
navigation, private wall detection, route rendering, and notification delivery.
It reuses the canonical SQLAlchemy models in
`cloud/dashboard/backend/app/models/models.py` and is mounted at
`/api/mapping-notification`.

## Prerequisites

- Python 3.10+
- MySQL with the cloud database configured
- Node.js/npm for the Vite dashboard frontend
- RabbitMQ for notification delivery
- SMTP settings if the worker must send email

From the repository root, create and activate the virtual environment, then
install the cloud dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r cloud\requirements.txt
```

Configure `cloud/dashboard/backend/.env` with at least:

```ini
DB_HOST=localhost
DB_PORT=3306
DB_USER=smart_campus_app
DB_PASSWORD=your_database_password
DB_NAME=biometric_rag_db
JWT_SECRET=replace-with-at-least-32-random-characters
APP_ENV=development
```

Set `PRIVATE_STORAGE_ROOT`, `RABBITMQ_URL`, `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM` when using private assets,
RabbitMQ, or email delivery. Never commit these values.

## Prepare the database

For an existing/shared database, use the non-destructive preparation script.
It now applies the mapping/notification hardening migration, including
`floorplans.graph_version`, when the schema migration has not been recorded:

```powershell
python cloud\dashboard\backend\scripts\prepare_cloud.py
```

Restarting `start_cloud.ps1` runs the same safe preparation automatically.

Do not use `app/db_init.py` against a shared database; it is intended for a
disposable development database. Before changing an existing schema, take the
required schema and row-count snapshot, then apply the additive mapping
migration:

```powershell
Get-Content cloud\dashboard\backend\migrations\20260730_mapping_notification_hardening.sql |
  mysql --host localhost --port 3306 --user smart_campus_app --password biometric_rag_db
```

The migration adds graph versions, notification retry/idempotency fields, and
the required indexes. Existing IDs and rows are not imported or remapped.

## Run the cloud backend

The repository launcher starts Redis, validates MySQL, prepares the database,
and starts FastAPI:

```powershell
.\start_cloud.ps1
```

For development auto-reload:

```powershell
.\start_cloud.ps1 -Reload
```

The dashboard is available at `http://localhost:8000/dashboard/` and the API
health check is `http://localhost:8000/api/health`.

To run FastAPI manually without the launcher:

```powershell
$env:PYTHONPATH = "$PWD\cloud\dashboard\backend;$PWD\cloud"
python -m uvicorn cloud.dashboard.backend.app.main:app --reload --port 8000
```

## Run the notification worker

Run the worker separately from Uvicorn. It declares the durable exchange,
queue, and routing key (`campus.notifications.exchange`,
`campus.notifications.queue`, `appointment_routing`) and acknowledges messages
only after the notification audit row is terminal:

```powershell
$env:PYTHONPATH = "$PWD\cloud\dashboard\backend;$PWD\cloud"
python -m cloud.mapping_and_notification.workers.notification_worker
```

The worker requires `RABBITMQ_URL` and the same database environment as the API.

## Run the Vite dashboard frontend

The feature is already included in the cloud dashboard source at
`/dashboard/mapping-notification`. It uses the dashboard's existing session and
CSRF protection; no second login or token store is required. The migrated page
includes floorplan upload/delete, graph editing, RBAC preservation, wall
overlays, cross-floor edges, route preview/highlights, notification testing,
and notification audit refresh. For frontend development, use a relative
`/api` client and point Vite at the HTTP FastAPI server:

```powershell
cd cloud\dashboard\frontend
npm install
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8000"
npm run dev
```

Open the Vite URL shown in the terminal, normally `http://localhost:5173/`.
For a production bundle, run `npm run build`; on Windows/OneDrive setups where
Vite's default config bundler hits an ACL error, use:

```powershell
npm run build:runner
```

## Verify the integration

```powershell
$env:PYTHONPATH = "$PWD\cloud\dashboard\backend;$PWD\cloud"
pytest -q cloud\mapping_and_notification\tests cloud\RagChatbot\tests\test_query_router.py cloud\RagChatbot\tests\test_personalisation.py
cd cloud\dashboard\frontend
npm run lint
npm run build:runner
cd ..\..\..
.\scripts\mapping_cutover_check.ps1
```

The cutover check verifies that the cloud API exposes the canonical mapping
routes and that production-facing cloud code and documentation contain no
hard-coded port-5000 calls. It also reports the remaining release gates: the
standalone runtime and compatibility aliases stay available until backup,
parity testing, deployment, and migration sign-off are complete. Start the API
and worker together for local integration testing with:

```powershell
.\start_cloud.ps1 -StartNotificationWorker
```

After production sign-off, the remaining Phase 7 actions are to stop the
standalone writers, monitor route/storage/broker/worker/location metrics during
the migration window, remove compatibility aliases, and archive the legacy
runtime and its CRA/Node dependency files.

`mapping/pathfinding.py` and `mapping/instructions.py` are database-independent
and can be tested without MySQL. The API routes require the cloud database and
dashboard authentication session.
