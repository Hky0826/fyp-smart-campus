# Access Control Facial Recognition

OpenCV YuNet & SFace face-recognition pipeline for access control and kiosk authentication.

## Architecture Overview

- **Face Detection**: OpenCV `YuNet` (`face_detection_yunet_2023mar_int8bq.onnx`)
- **Face Alignment**: 5-landmark affine alignment
- **Face Recognition**: OpenCV `SFace` (`face_recognition_sface_2021dec.onnx`) generating 128D feature vectors
- **Cloud Synchronization**: Downstream sync pulls `openvc_sface` templates from cloud backend (`module=access_control`)
- **Voice Feedback**: Prerecorded `access_granted.wav` and `access_denied.wav` spoken audio

---

## Directory Structure

```text
access_control/facial_recognition/
├── data/                    Local SQLite database storage (device_local.db)
├── models/
│   └── access_control/      YuNet and SFace ONNX models
├── setup_sqlite.py          Database setup and migration script
├── setup_sqlite.sql         SQLite schema definition for openvc_sface embeddings
├── src/
│   ├── config.py            Loads settings from access_control/.env on startup
│   ├── sync.py              Cloud synchronization worker & API
│   ├── api/                 FastAPI server and kiosk facade endpoints
│   ├── camera/              Threaded OpenCV camera reader
│   ├── face/                YuNet detector, SFace embedder, tracker, quality & spoofing checks
│   └── pipelines/           AccessControlPipeline & AccessControlAudioCoordinator
└── tests/                   Pytest unit test suite
```

---

## Setup & Running

### 1. Database Setup

To create or refresh the local SQLite database schema:

```bash
python access_control/facial_recognition/setup_sqlite.py
```

### 2. Direct Pipeline Execution

Run access control pipeline with display:

```bash
python -m access_control.facial_recognition.src.pipelines.access_control
```

To run without camera window display:

```bash
python -m access_control.facial_recognition.src.pipelines.access_control --no-display
```

To run without audio/chatbot:

```bash
python -m access_control.facial_recognition.src.pipelines.access_control --no-audio
```

### 3. FastAPI Service Execution

Start the REST API server:

```bash
uvicorn access_control.facial_recognition.src.api.main:app --host 0.0.0.0 --port 8080
```

Key Endpoints:
- `POST /access-control/frame`: Process single BGR image frame
- `GET /health`: Service health check
- `GET /sync/status`: Synchronization status
- `GET /models/status`: Verify ONNX model paths
- `POST /chatbot/chat`: Proxy user queries to RAG chatbot backend

---

## Running Tests

Run the test suite:

```bash
pytest access_control/facial_recognition/tests
```
