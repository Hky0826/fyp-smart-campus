# Facial-Recognition-Access-LLM-Navigation-for-Smart-Universities

Cloud startup on Windows is handled by one command from the repository root:

```powershell
.\start_cloud.ps1
```

Use `.\start_cloud.ps1 -Reload` when developing. See [setup.md](setup.md) for
the first-run prerequisites and access-control device setup.

---

## Workspace Directory Structure

* **cloud/**: Central server components (Dashboard API backend, RAG Chatbot, and Database Synchronization Routers).
* **edge/**: Local edge device components.
* **edge/facial_recognition/**: Hailo face-recognition, access-control, surveillance, SQLite sync, Docker, and local facial API code.
* **edge/audio_io/**: Audio activation, speech recording, cloud Gemini transcription/RAG/TTS client, and local playback.

---

## Pre-Connection Setup Guide (Dashboard Configurations)

Before connecting an edge kiosk device to the cloud central server, you must seed and configure the structural database entities using the cloud administrative dashboard. If these prerequisites are not configured, the synchronization worker will not run correctly, and offline authentications will fail.

### 1. Seed Security Roles (`roles` table)
Seed your campus database with core security classifications in the `roles` table (e.g., `role_id = 1` for `STUDENT`, `role_id = 2` for `LECTURER`). 
* *Sync Impact*: These definitions are synced downstream to the SQLite `device_roles` table to establish category relations.

### 2. Define Physical Node Maps (`nodes` and `devices` tables)
1. **Create Campus Nodes**: Add physical points of entry or rooms in the `nodes` table (e.g., node `5` corresponding to `Block A Entrance`).
2. **Register the Edge Device**: Map your device string (for example `entry-gate-01`) directly to its physical campus placement in the `devices` table by setting its `node_id` attribute.
* *Sync Impact*: During verification checks, the cloud upstream log ingestion endpoint matches the incoming `device_id` against the `devices` table to extract the physical installation node, updating the user's `last_known_location` in the cloud database.

### 3. Establish Location Entitlements (`node_rbac` table)
Map location entry policies in the `node_rbac` table, binding allowed security roles to physical campus nodes:
* Example: Insert a mapping granting `role_id = 1` (STUDENT) access to `node_id = 5` (Block A Entrance).
* *Sync Impact*: The downstream poller queries these rules and writes them to SQLite `device_node_rbac`. When a user presents their face, the edge device checks this local table to verify if the user's security role is authorized to enter through that node.

### 4. Enroll User Profiles (`users` table)
Enroll user accounts via the administrative panel:
1. Populate accounts with active status (`is_active = 1`).
2. Upload a face photo. The dashboard backend runs face embedding models to generate a **512-dimensional facial embedding vector** and stores it in the MySQL database's `face_vector` column.
* *Sync Impact*: The edge poller retrieves these vectors, converts them into binary float32 BLOB arrays, and caches them in the SQLite `device_users` table for offline biometric matching.
