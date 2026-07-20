# Standalone Access Control

This folder is a self-contained local access-control application. It preserves the native QML kiosk, RAG chatbot, cloud database synchronization, authenticated chatbot presence checks, cloud-managed identity embeddings, authentication and surveillance log storage, and GPIO/mock door control. YuNet is the authoritative detector, OpenCV SFace is the recognizer, and KCF is display-only localization between detections. It imports no runtime code from `edge/` or `legacy/`. The surveillance pipeline is not implemented yet, but the local database retains the shared `device_surveillance_logs` table and its cloud replay path for that future mode.

## Security model

A KCF box can be drawn, but it can never authenticate a person. Unlock requires two distinct, recent YuNet frames by default. Each accepted frame must contain exactly one valid face, pass the configured quality gate, produce a fresh SFace embedding, and match a compatible cloud-synchronized SFace template. Multiple faces, stale frames, tracker failures, quality failures, incompatible embeddings, cooldown, or missing door hardware prevent unlock.

Identity templates are authoritative in the cloud and arrive through downstream synchronization. The device stores and compares compatible templates but does not collect faces, create templates, or transform legacy embeddings.

## Requirements and installation

Use Python 3.11 or 3.12, 64-bit Raspberry Pi OS Bookworm or a supported desktop OS, an OpenCV-supported camera, and a Qt display stack for the native kiosk. On Raspberry Pi OS:

```sh
sudo apt update
sudo apt install -y python3-venv libgl1 libegl1 libxkbcommon0 libasound2 alsa-utils
cd "access control"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Use only `opencv-contrib-python-headless`; do not install another OpenCV wheel into the same environment. The contrib build supplies YuNet, SFace, and KCF. Both ONNX models and SFace metadata are already under `models/`, so normal startup performs no downloads.

## Configuration

The application reads `ACCESS_*` environment variables. `.env.example` is a reference file; export values through your shell, service manager, or container environment. Secrets are not stored in source.

| Setting | Default | Purpose |
|---|---:|---|
| `ACCESS_CAMERA` | `0` | Camera index, file, or stream |
| `ACCESS_CAMERA_WIDTH/HEIGHT` | `640/480` | Capture and YuNet input size |
| `ACCESS_DISPLAY_FPS` | `24` | UI target |
| `ACCESS_YUNET_FPS` | `6` | Detection target |
| `ACCESS_DETECTOR_INTERVAL` | `4` | One detector submission per four display frames |
| `ACCESS_TRACKER_MAX_AGE_FRAMES` | `24` | Maximum KCF age without detector confirmation |
| `ACCESS_MAX_FACES` | `1` | Conservative authentication limit |
| `ACCESS_SFACE_THRESHOLD` | `0.363` | Cosine-match threshold |
| `ACCESS_CONFIRMATIONS` | `2` | Distinct fresh detector confirmations |
| `ACCESS_UNLOCK_SECONDS` | `3` | Relay activation duration |
| `ACCESS_COOLDOWN_SECONDS` | `10` | Repeated-unlock protection |
| `ACCESS_HARDWARE_MODE` | `mock` | `mock` or `gpio` |
| `ACCESS_DB_PATH` | `data/device_local.db` | Local SQLite database |
| `ACCESS_CLOUD_URL` | `http://127.0.0.1:8000` | Sync, token, and RAG server |
| `ACCESS_API_HOST/PORT` | `0.0.0.0/8080` | Local kiosk API and cloud callback |
| `ACCESS_DEBUG_METRICS` | `false` | Marks performance statistics as enabled |

Quality, KCF validation, retry, logging, model paths, GPIO polarity, and GUI/audio settings are also documented in `.env.example` and `app/config/settings.py`. For systemd, set the working directory to this folder, load an environment file, and start `python run.py all`. Keep mock hardware enabled until relay wiring and polarity have been verified.

## Run

```sh
python run.py api   # API and biometric runtime only
python run.py ui    # native QML kiosk; API must already be running
python run.py all   # API plus native kiosk
```

Paths resolve from this module, so entry points work from another working directory. The default API listens on the LAN so the cloud can call instant deactivation; the kiosk uses `http://127.0.0.1:8080`.

Useful endpoints include `GET /health`, `/models/status`, `/database/status`, `/sync/status`, `/metrics`, `/kiosk/state`, and `/kiosk/events`; `POST /api/edge/deactivate` accepts JSON such as `{"user_id":7}`. Metrics report measured display/detector/tracker rates, inference latency, forced detections, and dropped frames.

Database sync and chatbot HTTP work run outside the display loop. Sync failures are contained, unsent authentication and surveillance logs remain ordered in SQLite, and retries use bounded backoff. Surveillance logs are sent to `/api/sync/upstream/surveillance-logs`.

## Cloud-managed identities and embeddings

The device has no identity-capture or template-creation API. The cloud is authoritative for users, embedding vectors, and any migration strategy. The SQLite layout matches `edge/facial_recognition/setup_sqlite.sql`, except its embedding model constraint is `opencv_sface` for this device pipeline.

Cloud user payloads can provide templates through `embeddings`, `face_embeddings`, `user_face_embeddings`, or `templates`. Each template should include `model_name` (`opencv_sface`) and either `embedding` or `embedding_b64`; `template_name` is optional. Model version and vector dimension remain runtime compatibility metadata rather than database columns. Only SFace rows with the active probe dimension are considered during matching.

Use `POST /api/edge/trigger-sync` for an immediate pull and inspect `GET /sync/status` and `GET /database/status`. The device does not automatically alter legacy embedding schemas or generate replacement templates.

## Tests and recorded-frame mode

No automated test opens real GPIO hardware.

```sh
python -m unittest discover -s tests -v
python -m pytest tests -q
```

Run the real local models against recorded images while keeping the door mocked:

```sh
python scripts/run_recorded.py path/to/frames --fps 24
```

It accepts image files or directories, uses the bounded newest-frame pipeline, prints decisions and measured statistics, and reports mock unlock calls.

## Raspberry Pi 5 performance

The 640x480, 24 FPS UI timer and four-frame detector interval target approximately 24 display, 6 YuNet, and 18 KCF updates per second. A single worker owns one YuNet/SFace model pair; its queue retains only the newest access frame. Results retain frame IDs and capture timestamps, stale results are rejected, and YuNet immediately replaces KCF.

Use camera MJPEG where available, active cooling, and the 64-bit OS. Inspect `/metrics` under realistic lighting. Tune input size, quality thresholds, and detector interval only after measuring; never increase tracker trust or bypass fresh confirmation to gain speed.

## Troubleshooting

- Model missing: restore files under `models/yunet/` and `models/sface/`, or configure absolute model paths.
- KCF unavailable: remove conflicting OpenCV wheels and reinstall the contrib package.
- Camera unavailable: check permissions and exclusive use; configure `ACCESS_CAMERA` or `ACCESS_GUI_CAMERA_FALLBACKS`.
- Chatbot or sync offline: verify `ACCESS_CLOUD_URL`; access remains local and retries continue.
- Door verified but unavailable: check hardware mode, GPIO pin/polarity, permissions, relay power, and logs. Identity verification and physical unlock are separate results.
- No QML window: verify Qt platform packages and set `ACCESS_GUI_QPA_PLATFORM` for the display session.
