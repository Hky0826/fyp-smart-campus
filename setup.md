# First-Time Access-Control Device Setup

This guide provisions one access-control edge device against the Smart Campus cloud backend.

The intended order is:

```text
Prepare cloud secrets and database
        ↓
Start cloud backend and apply migrations
        ↓
Create a campus node and device in the dashboard
        ↓
Copy the one-time device secret to the edge secret store
        ↓
Configure and start the edge service
        ↓
Enroll users and configure node access rules
        ↓
Verify signed synchronization and face-authentication
```

Do not use a device ID or user ID as a credential. The cloud-generated device secret is required for HMAC-signed requests.

## 1. Prerequisites

Install or provide:

- Python 3.11 or newer;
- MySQL for the cloud database;
- Redis for production rate limiting;
- OpenCV YuNet and SFace model files on the edge device;
- a tested Presentation Attack Detection (PAD) model for production access decisions;
- TLS for the cloud URL in production;
- a deployment secret store for JWT, database, Google API, device-credential, and edge database-encryption secrets.

Create or activate the project virtual environment from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r cloud\requirements.txt
python -m pip install -r access_control\facial_recognition\requirements.txt
```

When edge SQLite encryption is enabled, install the platform-specific SQLCipher Python binding (`pysqlcipher3`) and its native SQLCipher dependency. The edge service fails closed if `EDGE_DB_ENCRYPTION_KEY` is set but the binding is unavailable.

## 2. Configure cloud secrets

Copy `cloud/dashboard/backend/.env.example` to `cloud/dashboard/backend/.env`, or inject the same values through the production secret provider. Do not commit `.env` files.

At minimum, configure:

```ini
APP_ENV=production
JWT_SECRET=<random-value-at-least-32-characters>
DEVICE_CREDENTIAL_KEY=<Fernet-key>
DB_HOST=<mysql-host>
DB_PORT=3306
DB_USER=<cloud-database-user>
DB_PASSWORD=<cloud-database-password>
DB_NAME=smart_campus_db
RATE_LIMIT_REDIS_URL=redis://<redis-host>:6379/0
DASHBOARD_ORIGINS=https://<dashboard-origin>
PRIVATE_STORAGE_ROOT=/var/lib/smart-campus/private
COOKIE_SECURE=true
```

Generate values rather than choosing memorable strings:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Also provide the Google/Gemini credentials required by the RAG configuration. Rotate any credentials that were previously present in repository files, databases, logs, or snapshots.

The recommended audio defaults enable the Gemini Live transport while retaining
the existing HTTP fallback. The Live gateway uses `gemini-3.1-flash-live-preview`
for 16 kHz mono microphone input and 24 kHz mono output. The backend validates
the transcript and applies the normal authentication, authorization, safety,
navigation, and RAG pipeline before sending approved text back for speech.

Optional cloud settings:

```ini
RAG_LIVE_ENABLED=true
RAG_LIVE_FALLBACK_ENABLED=true
RAG_LIVE_MODEL=gemini-3.1-flash-live-preview
RAG_LIVE_INPUT_SAMPLE_RATE=16000
RAG_LIVE_OUTPUT_SAMPLE_RATE=24000
RAG_LIVE_IO_TIMEOUT_SECONDS=15
RAG_LIVE_BACKEND_TIMEOUT_SECONDS=45
RAG_LIVE_SESSION_TIMEOUT_SECONDS=900
RAG_AUDIO_LEGACY_FALLBACK_ENABLED=true
```

For this laptop's local development installation, use `APP_ENV=development`, `DB_HOST=localhost`, `DB_PORT=3306`, `DB_USER=root`, and `DB_NAME=smart_campus_db`; keep the database password only in the untracked `.env` file. Use `COOKIE_SECURE=false` and dashboard origins such as `http://127.0.0.1:8000`. When the first device is created, development mode automatically generates and stores the encryption key outside the repository at `~/.smart-campus-cloud/device_credential.key`.

For production-like testing on this laptop, bootstrap the persistent production secret store once:

```powershell
\.venv\Scripts\python.exe cloud\dashboard\backend\scripts\bootstrap_local_production_secrets.py
```

Then set `APP_ENV=production` and restart the cloud backend. The store is loaded automatically from `~/.smart-campus-cloud/production-secrets.env`; it is not recreated on restart. Production deployments should replace this local file with a real secret manager. Production must still use HTTPS, Redis, and externally supplied Google credentials.

## 3. Initialize the cloud database

Use a fresh database or a verified backup. Choose one initialization path:

- For a disposable development database, the legacy initializer drops and recreates tables from the current ORM models, then seeds development reference data. Run it once and do not apply the SQL migrations below unless your migration runner confirms that a migration is still missing:

```powershell
python cloud\dashboard\backend\app\db_init.py
```

- For an existing or production database, do **not** run `db_init.py`. It drops tables. Use the approved base-schema/bootstrap process, take a backup, and apply the migrations below in order.

The development initializer contains a legacy test administrator seed. Do not use its default password in production. Production must start from an approved database bootstrap process with a unique administrator password.

For the existing/production path, apply migrations in order during a maintenance window. Replace the MySQL command with the organization's migration runner if one exists:

```bash
mysql -h <mysql-host> -P 3306 -u <migration-user> -p smart_campus_db < cloud\dashboard\backend\migrations\20260719_multi_model_embeddings.sql
mysql -h <mysql-host> -P 3306 -u <migration-user> -p smart_campus_db < cloud\dashboard\backend\migrations\20260720_widen_log_sync_keys.sql
mysql -h <mysql-host> -P 3306 -u <migration-user> -p smart_campus_db < cloud\dashboard\backend\migrations\20260728_security_hardening.sql
mysql -h <mysql-host> -P 3306 -u <migration-user> -p smart_campus_db < cloud\dashboard\backend\migrations\20260728_face_auth_challenges.sql
mysql -h <mysql-host> -P 3306 -u <migration-user> -p smart_campus_db < cloud\dashboard\backend\migrations\20260728_private_data.sql
```

For an existing installation, migrate old private files before disabling the old public paths:

```powershell
Push-Location cloud\dashboard\backend
python scripts\migrate_private_files.py
Pop-Location
```

Review the migration output and database object keys before exposing the new backend.

## 4. Start and verify the cloud backend

For this laptop, the normal startup command is now:

```powershell
.\start_cloud.ps1
```

You can also double-click `start_cloud.bat`. The launcher starts or reuses the
loopback-only Redis container, uses `APP_ENV=development` with the untracked
development `.env`, checks MySQL, prepares the database without dropping
existing tables, and then starts the backend on loopback. Use
`.\start_cloud.ps1 -Reload` during development when you want code reloads. Do not use
`cloud\dashboard\backend\app\db_init.py` from this launcher; that legacy
initializer drops all tables.

From the repository root:

```powershell
\.venv\Scripts\python.exe -m uvicorn cloud.dashboard.backend.app.main:app --host 127.0.0.1 --port 8000
```

Use a reverse proxy with TLS for a remote production deployment. Do not bind the dashboard directly to a public interface without the deployment’s TLS and access-control layer.

Verify that:

- `GET https://<cloud-host>/` redirects to `/dashboard/`;
- the dashboard loads locally built assets;
- the administrator can log in;
- unsafe browser requests include the CSRF header;
- the backend can connect to MySQL and Redis;
- startup does not report missing `JWT_SECRET`, `DEVICE_CREDENTIAL_KEY`, or other required secrets.

Open the dashboard at `https://<cloud-host>/dashboard/` and sign in with the approved administrator account.

## 5. Guided first-time device setup

For a non-technical operator, use this order. The access-control screen is the setup guide; do not edit `access_control/.env` for normal laptop setup.

1. Start the access-control module with `python access_control\run.py all`.
2. On the device screen, note the displayed edge address and cloud dashboard URL.
3. On the administrator laptop, open the dashboard and go to **Infrastructure → Devices → Add Device**.
4. Create the physical node/location first, then create the device. Leave the device ID blank; the cloud generates it automatically.
5. Keep the one-time provisioning dialog open. It displays the generated Device ID and secret and explains the next steps.
6. On the access-control setup screen, enter the cloud URL, generated Device ID, and one-time secret. Select **Apply and start**.
7. The device saves its runtime configuration outside the repository, starts signed synchronization, and closes the setup screen. The dashboard can then show the device heartbeat/status.

If the cloud and edge run on separate computers, select **Enable secure cloud-to-edge push over Wi-Fi** on the edge setup screen. The edge automatically detects its LAN IP, binds the authenticated sync receiver to that address, and advertises the address in its signed heartbeat. Leave this option unchecked when both services run on the same laptop; the edge remains loopback-only and uses `127.0.0.1`.

If the edge and cloud services run on different laptops, replace `127.0.0.1` in the cloud URL with the cloud laptop's Wi-Fi IP address and use HTTPS for the non-loopback connection. Both computers must be on the same reachable network.

## 6. Create the physical node and device in the cloud

Before registering the device, create the physical location that owns it:

1. In the dashboard, create or verify a campus building/floor/node.
2. Record the node ID; the device record requires it.
3. Configure `node_rbac` so the appropriate roles may access that node.
4. Open the infrastructure/device administration view.
5. Create a device with:
   - a descriptive device name;
   - no device ID; the cloud generates a unique stable ID such as `ENTRY-A1B2C3D4` or `KIOSK-A1B2C3D4`;
   - the node ID;
   - device type `ENTRY_GATE` or `KIOSK`;
   - the edge host address only when the cloud must contact it.

The dashboard displays `provisioned_secret` in a one-time provisioning dialog. Enter it into the access-control setup screen immediately; it is not shown again after the dialog is closed. The cloud database stores only encrypted device credential data.

If the secret is lost, use the device's **Rotate credential** action. Rotation invalidates the old secret; update the edge configuration and restart it before expecting synchronization to resume.

## 7. Prepare the edge host

No edge `.env` file is required for the normal first-time flow. Start the
module directly with `python access_control\run.py all`. On first start it
creates or migrates SQLite outside the repository, displays the setup
instructions, and waits for the administrator to enter the cloud URL,
generated device ID, and one-time secret.

An `access_control/.env` file is an optional advanced-deployment fallback.
The normal UI flow saves the device ID, cloud URL, and secret in
`~/.smart-campus-edge/device_runtime.env` through the access-control UI.

Set the values that identify this specific device:

```ini
APP_ENV=production
EDGE_SYNC_ENABLED=true
EDGE_SYNC_CLOUD_URL=https://<cloud-host>
EDGE_SYNC_DEVICE_ID=entry-gate-01
EDGE_SYNC_DEVICE_SECRET=<one-time-secret-from-cloud>
EDGE_SYNC_DEVICE_NAME=North Entry Gate Kiosk
EDGE_SYNC_LOCAL_IP=127.0.0.1
EDGE_SYNC_LOCAL_PORT=8001
ACCESS_API_HOST=127.0.0.1
ACCESS_API_PORT=8080
EDGE_DB_PATH=
EDGE_DB_ENCRYPTION_KEY=<deployment-provided-edge-database-key>
EDGE_ACCESS_SNAPSHOT_ENABLED=false
EDGE_ACCESS_PAD_MODEL_PATH=<tested-pad-model-path>
EDGE_ACCESS_PAD_MODEL_VERSION=<model-version>
EDGE_ACCESS_PAD_REQUIRED=true
EDGE_ALLOW_INSECURE_LOOPBACK=false
EDGE_REMOTE_API_ENABLED=false
EDGE_ACCESS_AUDIO_ENABLED=true
EDGE_AUDIO_LIVE_ENABLED=true
EDGE_AUDIO_LIVE_FALLBACK_ENABLED=true
EDGE_GUI_LIVE_ENABLED=true
```

Leaving `EDGE_DB_PATH` empty uses the external default `~/.smart-campus-edge/device_local.db`, outside the repository. If a different location is required, use an absolute path outside the checkout.

On the first edge start, the access-control display shows the edge address and guided instructions. The operator enters the dashboard URL, generated device ID, and one-time secret directly on that screen. Selecting **Apply and start** saves the runtime configuration outside the repository, starts synchronization, and records the persistent `.setup_complete` marker. Later restarts skip the wizard.

The edge service rejects non-HTTPS cloud URLs except when insecure loopback development mode is explicitly enabled. It also binds the local API and synchronization receiver to loopback by default. The guided Wi-Fi option uses the provisioned device secret to authenticate cloud trigger requests. For advanced manual deployments, remote mode may instead use a strong `EDGE_INSTALLATION_CREDENTIAL`:

```ini
EDGE_REMOTE_API_ENABLED=true
EDGE_INSTALLATION_CREDENTIAL=<random-installation-credential>
# Leave EDGE_SYNC_LOCAL_IP blank to auto-detect the LAN address in remote mode.
EDGE_SYNC_LOCAL_IP=<approved-private-interface>
```

Remote mode requires the installation credential on requests and should be protected by network policy or a firewall.

Download the face models if they are not already installed:

```bash
bash access_control/facial_recognition/download_models.sh
```

Verify the configured model paths and camera before starting production traffic.

## 8. Initialize and start the edge service

For the normal guided GUI flow, `run.py all` initializes the external edge database automatically. The standalone schema command is optional and is useful for a headless/pre-provisioned device; it creates the local users, embeddings, RBAC, sync-log, and nonce tables:

```powershell
python access_control\facial_recognition\setup_sqlite.py
```

Start the API for a headless device:

```powershell
python access_control\run.py api
```

For a device with the local GUI, use:

```powershell
python access_control\run.py all
```

On the first run, the startup sequence initializes SQLite and waits at the
guided setup screen. After setup is completed, it validates security settings,
opens the configured edge database, starts the loopback sync receiver, and
starts downstream/upstream synchronization. The cloud requests are signed with
the device ID, timestamp, nonce, method, path, query, and body hash.

Check the local service:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:8080/sync/status
Invoke-RestMethod http://127.0.0.1:8080/models/status
```

Expected results are a healthy API, synchronization enabled/running, and both face model files present. A `401` in the cloud sync logs usually means the device ID or secret does not exactly match the cloud device record, the secret was rotated, or the device clock is wrong.

## 9. Enroll users and verify authorization

After the device is connected:

1. Create or import the user account in the cloud dashboard and keep it active.
2. Enroll the required face poses using the live enrollment flow.
3. Confirm the user’s role is assigned.
4. Confirm the role is allowed at the device’s node through `node_rbac`.
5. Wait for the next downstream sync, or trigger a sync from the approved administrator workflow.
6. Check the edge local database/sync status without copying biometric data back into the repository.
7. Test one authorized user, one unauthorized user, and a liveness/PAD failure.

The chatbot remains anonymous for public content only. A face-authenticated edge session receives a short-lived user JWT only after a one-time cloud challenge, a signed assertion, a successful match, and a successful liveness result. A device ID plus user ID alone must not issue a token.

## 10. First-device acceptance checklist

- [ ] Cloud secrets are external, strong, and not committed.
- [ ] Database migrations completed and private-file migration reviewed.
- [ ] Redis is reachable from the cloud backend.
- [ ] Cloud backend is behind HTTPS in production.
- [ ] Campus node exists and its RBAC rules are configured.
- [ ] Device was created in the dashboard with the correct node and type.
- [ ] One-time device secret was stored in the edge secret provider and removed from temporary copies.
- [ ] Edge database path is outside the repository.
- [ ] Edge database encryption key is configured in production.
- [ ] Edge API and sync receiver bind to loopback unless remote mode is explicitly approved.
- [ ] YuNet, SFace, and tested PAD models are present.
- [ ] Face snapshots are disabled unless explicitly approved with retention configured.
- [ ] Edge health, models, and sync endpoints pass.
- [ ] Authorized, unauthorized, replayed, expired, and liveness-failure cases were tested.
- [ ] Credential rotation and device decommission procedures are documented.

## Troubleshooting

### Cloud startup fails with a missing secret

Check the cloud deployment secret provider and the backend `.env` source. Production startup intentionally fails when `JWT_SECRET`, `DEVICE_CREDENTIAL_KEY`, or `RATE_LIMIT_REDIS_URL` is missing or weak.

### Edge startup rejects the cloud URL

Use an HTTPS URL. For local development only, use a loopback URL and explicitly set `EDGE_ALLOW_INSECURE_LOOPBACK=true`; never use that setting for a remote device.

### Synchronization returns `401`

Check that `EDGE_SYNC_DEVICE_ID` matches the cloud record exactly, the one-time secret was copied without whitespace, the credential was not rotated, and the system clock is synchronized. Signed requests are rejected outside the allowed timestamp window and on nonce replay.

### The edge database cannot be opened

If `EDGE_DB_ENCRYPTION_KEY` is set, install SQLCipher and `pysqlcipher3`, verify the key is unchanged, and ensure the service account can read/write the external database directory. Do not delete the database before preserving any required operational evidence.

### A production edge starts without PAD

It should not. Set a valid tested `EDGE_ACCESS_PAD_MODEL_PATH` and model version, or keep the device out of production access decisions until PAD validation is complete.
