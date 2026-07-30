# Surveillance Module

The `surveillance` module provides multi-face and multi-person tracking and identification on Hailo-equipped edge devices. It combines YOLOX-M, YuNet, AuraFace, ByteTrack, local SQLite storage, and cloud synchronization.

## Features & Architecture

- **Person Detection (`YOLOX-M`)**: Detects person bounding boxes in video frames (`surveillance/models/yolox.py`).
- **Multi-Object Tracking (`ByteTrack`)**: Assigns persistent `track_id` values to tracked persons using Kalman Filtering and Hungarian IoU matching (`surveillance/tracking/bytetrack.py`).
- **Face Detection (`YuNet`)**: Detects face regions and 5 facial landmarks within tracked person regions (`surveillance/models/yunet.py`).
- **Face Recognition (`AuraFace`)**: Extracts 512-dimensional normalized face embeddings for matching against enrolled user templates (`surveillance/models/auraface.py`).
- **Identity Persistence & Redundancy Avoidance**:
  - Once a person's face is recognized in even a single frame, the identity is linked to the active `track_id`.
  - The identity is preserved for the entire lifetime of the active track, even when the face is occluded or turned away in subsequent frames.
  - Face recognition processing is skipped for already-recognized active tracks.
- **Local SQLite Database (`SurveillanceUserRepository`)**: Caches enrolled `auraface` user embeddings and buffers surveillance recognition events (`surveillance/database.py`). Default path: `surveillance/surveillance.db`.
- **Cloud Sync Engine (`SurveillanceSyncEngine`)**:
  - Downstream worker polls cloud for `module=surveillance` user deltas.
  - Upstream client replays offline-buffered surveillance logs and heartbeats (`surveillance/sync.py`).

## Configuration

Model paths, thresholds, and sync settings are fully configurable via `SurveillanceConfig` in `surveillance/config.py` or environment variables:

| Environment Variable | Default Path / Value | Description |
|---|---|---|
| `SURVEILLANCE_PERSON_DETECTOR_MODEL_PATH` | `surveillance/models/yolox_m_hailo8.hef` | Path to YOLOX-M HEF model (or `yolox_s_hailo8.hef`) |
| `SURVEILLANCE_FACE_DETECTOR_MODEL_PATH` | `surveillance/models/yunet_hailo8.hef` | Path to YuNet HEF model |
| `SURVEILLANCE_FACE_EMBEDDER_MODEL_PATH` | `surveillance/models/auraface_hailo8.hef` | Path to AuraFace HEF model |
| `SURVEILLANCE_DB_PATH` | `surveillance/surveillance.db` | Path to local SQLite database |
| `SURVEILLANCE_CAMERA` | `0` | Camera device index, RTSP URL, or video file |
| `SURVEILLANCE_PERSON_DETECTION_THRESHOLD` | `0.50` | YOLOX-M confidence threshold |
| `SURVEILLANCE_FACE_DETECTION_THRESHOLD` | `0.60` | YuNet confidence threshold |
| `SURVEILLANCE_RECOGNITION_THRESHOLD` | `0.65` | AuraFace cosine similarity threshold |
| `SURVEILLANCE_SYNC_CLOUD_URL` | `http://10.178.101.3:8000` | Cloud sync URL endpoint |
| `SURVEILLANCE_SYNC_DEVICE_ID` | `surveillance-cam-01` | Cloud-registered device ID |
| `SURVEILLANCE_SYNC_DEVICE_SECRET` | *(required)* | One-time HMAC secret provisioned by the cloud dashboard |

The cloud sync API requires signed device requests. Create or rotate the surveillance device in the cloud dashboard, then store the returned one-time secret as `SURVEILLANCE_SYNC_DEVICE_SECRET` in the device's secret store. The device ID and secret must match the cloud registration.

> **Note:** Safe mock model runners are automatically used if physical `.hef` files are absent or when running without Hailo hardware.

## Quick Start

### 1. Run Surveillance Camera with Live OpenCV Display
To start the live video stream with OpenCV bounding boxes, track IDs, recognized names, and confidence scores:

```bash
python -m surveillance
```
Or with custom flags:
```bash
python -m surveillance --camera 0 --window-name "Surveillance Monitor"
```
**Options**:
- `--camera`: Camera index (e.g. `0`), RTSP stream URL, or video file path.
- `--database`: Path to custom SQLite database file.
- `--display` / `--no-display`: Show or hide live OpenCV display window (default: `--display`).
- `--mirror` / `--no-mirror`: Mirror the displayed camera preview.
- Press **`q`** or **`ESC`** on the display window to exit.

### 2. Run Surveillance Daemon API (Background Service)
```bash
uvicorn surveillance.app:app --host 0.0.0.0 --port 8002
```

### 3. Run Automated Test Suite
```bash
pytest surveillance/tests -v
```
