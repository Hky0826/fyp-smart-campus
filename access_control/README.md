# Standalone Access Control Module

The `access_control` directory is a standalone module extracted for edge access control, voice chatbot interactions, PySide6 GUI interface, and cloud synchronization. It uses OpenCV **YuNet** (face detection) and **SFace** (facial recognition), loading configuration directly from `.env` on every startup.

```text
access_control/
├── .env                     Active environment configuration file (loaded automatically on start)
├── .env.example             Configuration template with descriptions
├── audio_io/                Voice chatbot recording, Gemini cloud RAG proxy, audio feedback, and playback
│   └── sounds/              Prerecorded voice feedback (access_granted.wav, access_denied.wav)
├── facial_recognition/      Face detection (YuNet), recognition (SFace), sync, database, and FastAPI endpoints
│   ├── models/
│   │   └── access_control/  ONNX models (face_detection_yunet_2023mar_int8bq.onnx, face_recognition_sface_2021dec.onnx)
│   ├── src/
│   │   ├── api/             FastAPI server (main.py) & kiosk facade (kiosk.py)
│   │   ├── face/            YuNet detector, SFace embedder, tracking, quality & spoofing checks
│   │   ├── pipelines/       Access control pipeline (access_control.py) & audio coordinator (access_audio.py)
│   │   └── sync.py          Cloud synchronization engine for openvc_sface embeddings
│   └── tests/               Pytest automated test suite
├── ui/
│   └── access_control_gui/       PySide6 / QML native desktop GUI application
└── test/                    Evaluation & benchmarking framework
```

---

## Quick Start

### 1. Environment & Dependencies

Install required Python dependencies:

```bash
pip install -r access_control/facial_recognition/requirements.txt
```

Create `.env` from `.env.example`:

```bash
cp access_control/.env.example access_control/.env
```

### 2. Initialize Database

Setup local SQLite database (`device_local.db`):

```bash
python access_control/facial_recognition/setup_sqlite.py
```

### 3. Unified Launcher (`run.py`)

Run both the FastAPI backend server and the PySide6 QML GUI together with a single command:

```bash
python access_control/run.py
```

Other available modes:

```bash
# Run API server only
python access_control/run.py api

# Run GUI only
python access_control/run.py gui
```

### 4. Direct Pipeline Execution

Run direct access control pipeline with camera display and voice feedback:

```bash
python -m access_control.facial_recognition.src.pipelines.access_control
```

*Press spacebar while the window is focused to initiate a voice chatbot interaction.*

### 5. Run Kiosk API Server Manually

Start FastAPI kiosk backend server:

```bash
uvicorn access_control.facial_recognition.src.api.main:app --host 0.0.0.0 --port 8080
```

---

## Configuration (`.env`)

All parameters are configurable via `access_control/.env`. Key parameters include:

| Setting | Default | Description |
|---|---|---|
| `EDGE_CAMERA` | `0` | Camera device index or RTSP stream URL |
| `EDGE_ACCESS_DETECTOR_MODEL_PATH` | `models/access_control/face_detection_yunet_2023mar_int8bq.onnx` | Path to YuNet ONNX detection model |
| `EDGE_ACCESS_EMBEDDING_MODEL_PATH` | `models/access_control/face_recognition_sface_2021dec.onnx` | Path to SFace ONNX recognition model |
| `EDGE_ACCESS_DETECTION_THRESHOLD` | `0.60` | Detector confidence threshold |
| `EDGE_ACCESS_RECOGNITION_THRESHOLD` | `0.363` | SFace cosine similarity threshold |
| `EDGE_ACCESS_REQUIRE_LIVENESS` | `true` | Enable motion/liveness anti-spoofing |
| `EDGE_ACCESS_AUDIO_ENABLED` | `true` | Enable voice feedback & chatbot |
| `EDGE_SYNC_CLOUD_URL` | `http://127.0.0.1:8000` | Central cloud database sync server |

---

## Automated Tests

Run test suite:

```bash
pytest access_control/facial_recognition/tests
```
