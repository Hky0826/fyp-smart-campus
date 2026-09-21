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
| `EDGE_CAMERA` | `auto` | Camera source: `auto` (auto-detects CSI IMX219 on RPi 5, falls back to V4L2), `csi`, `/dev/video4`, `0`, or RTSP URL |
| `EDGE_ACCESS_DETECTOR_MODEL_PATH` | `models/access_control/face_detection_yunet_2023mar_int8bq.onnx` | Path to YuNet ONNX detection model |
| `EDGE_ACCESS_EMBEDDING_MODEL_PATH` | `models/access_control/face_recognition_sface_2021dec.onnx` | Path to SFace ONNX recognition model |
| `EDGE_ACCESS_DETECTION_THRESHOLD` | `0.60` | Detector confidence threshold |
| `EDGE_ACCESS_RECOGNITION_THRESHOLD` | `0.363` | SFace cosine similarity threshold |
| `EDGE_ACCESS_REQUIRE_LIVENESS` | `true` | Enable motion/liveness anti-spoofing |
| `EDGE_ACCESS_AUDIO_ENABLED` | `true` | Enable voice feedback & chatbot |
| `EDGE_SYNC_CLOUD_URL` | `http://127.0.0.1:8000` | Central cloud database sync server |

### Raspberry Pi 5 & CSI Camera Setup (IMX219)

For Sony IMX219 cameras connected to Raspberry Pi 5 via MIPI CSI (`CAM0` or `CAM1`):
1. Connect the 15-pin to 22-pin ribbon cable to either `CAM0` or `CAM1` (ensure contacts face the HDMI ports on Pi 5).
2. Install the official Raspberry Pi camera library:
   ```bash
   sudo apt update && sudo apt install -y python3-picamera2
   ```
3. Verify sensor detection:
   ```bash
   rpicam-hello --list-cameras
   ```
4. Keep `EDGE_CAMERA=auto` (default) to automatically use the CSI camera, or set `EDGE_CAMERA=csi` to force CSI mode. If no CSI camera is attached, the system seamlessly falls back to USB / V4L2 `/dev/video*`.

### Raspberry Pi 5 Relay & Magnetic Door Lock Setup

When a registered face is positively verified, the module activates the GPIO relay to unlock a magnetic door lock for a configurable duration (default: 5.0 seconds).

#### 1. Hardware Dependencies on Raspberry Pi 5 (RP1 GPIO)
Raspberry Pi 5 requires `gpiozero` and `lgpio` (Debian Bookworm):
```bash
sudo apt update && sudo apt install -y python3-gpiozero python3-lgpio
```

#### 2. Physical Pinout Connection (Raspberry Pi 5 to Relay)
Connect female-to-female jumper wires from the Raspberry Pi 40-pin header to the relay module:

| Relay Module Pin | Raspberry Pi 5 Pin | Header Location | Description |
|---|---|---|---|
| **VCC** | **Pin 2** (or Pin 4) | Top-right outer pin | **5V Power** to relay coil/optocoupler |
| **GND** | **Pin 6** (or Pin 9) | Third pin down on outer column | **Ground** common return |
| **IN / Signal** | **Pin 11** | Sixth pin down on inner column | **BCM GPIO 17** (3.3V trigger signal) |

#### 3. Magnetic Door Lock Fail-Safe Wiring
Magnetic door locks are **Fail-Safe** (power cut = unlocked):
1. External Power Supply (+) 12V/5V $\to$ Relay **`COM`** (Common).
2. Relay **`NC`** (Normally Closed) $\to$ Magnetic Lock **(+)**.
3. External Power Supply (-) $\to$ Magnetic Lock **(-)**.

*(When idle, the circuit is closed and the magnet holds the door locked. When access is granted, the relay energizes, opening the `NC` contact and releasing the door magnet).*

#### 4. Environment Configuration
Configurable via `access_control/.env`:
```bash
EDGE_DOOR_RELAY_ENABLED=true
EDGE_DOOR_RELAY_PIN=17
EDGE_DOOR_UNLOCK_DURATION_SECONDS=5.0
EDGE_DOOR_RELAY_ACTIVE_HIGH=false
```

---

## Automated Tests

Run test suite:

```bash
pytest access_control/facial_recognition/tests
```
