# Edge Device Pipelines

The edge code is split into independent runtime areas:

```text
edge/
  facial_recognition/   Hailo face-recognition, access-control, surveillance, sync, and local API code
  audio_io/             Spacebar activation, recording, cloud Gemini transcription/RAG/TTS, and playback
  README.md             This folder overview
```

## Facial Recognition

The existing facial-recognition pipeline was moved to `edge/facial_recognition/`.

Install dependencies:

```bash
python3 -m pip install -r edge/facial_recognition/requirements.txt
```

Prepare HailoRT and HEF models:

```bash
bash edge/facial_recognition/install_hailort.sh
bash edge/facial_recognition/download_models.sh
```

Prepare the local SQLite database:

```bash
python edge/facial_recognition/setup_sqlite.py
```

Run the direct pipelines:

```bash
python3 -m access_control.facial_recognition.src.pipelines.run_both
python3 -m access_control.facial_recognition.src.pipelines.access_control
python3 -m access_control.facial_recognition.src.pipelines.surveillance
```

The access-control runner starts the audio I/O chatbot automatically. Press the
space bar while the access-control OpenCV window is focused to start one
chatbot recording.
After a successful face match, it requests a JWT from
`${EDGE_SYNC_CLOUD_URL}/api/edge-auth/token` and shares that token with the
audio chatbot client. Surveillance does not start audio.

Run the optional facial API:

```bash
uvicorn access_control.facial_recognition.src.api.main:app --host 0.0.0.0 --port 8080
```

Detailed facial-recognition setup remains in `edge/facial_recognition/README.md`.

## Audio I/O

The local voice interaction pipeline lives in `edge/audio_io/` and can run independently from facial recognition.

Install dependencies:

```bash
python3 -m pip install -r edge/audio_io/requirements.txt
```

Download local STT and TTS assets:

```bash
python -m edge.audio_io.download_models
```

Run the audio pipeline:

```bash
export EDGE_SYNC_CLOUD_URL=http://<cloud-host>:8000
python -m edge.audio_io.main
```

Press the space bar in the terminal to start each chatbot recording.

Without `EDGE_AUDIO_CLOUD_BEARER_TOKEN`, chatbot queries use visitor/PUBLIC
access. A JWT is only needed when the chatbot needs documents above visitor
access.

For a local smoke run that records immediately instead of waiting for the space bar:

```bash
python -m edge.audio_io.main --once --skip-activation
```

For a local-only hardware test of spacebar activation, microphone, STT, TTS, and playback:

```bash
python -m edge.audio_io.local_audio_test
```

For a no-JWT smoke test of local audio and chatbot reachability:

```bash
export EDGE_SYNC_CLOUD_URL=http://<cloud-host>:8000
python -m edge.audio_io.smoke_test
```

Detailed audio setup, environment variables, and hardware notes are in `edge/audio_io/README.md`.
