# Edge Audio I/O Pipeline

This package adds local voice interaction for the edge device:

```text
space bar -> record speech -> whisper.cpp STT -> FastAPI RAG stream -> Piper TTS -> local playback
```

It is independent from `edge/facial_recognition/` and can be started on its own.

## Folder Contents

```text
edge/audio_io/
  config.py           Environment-driven runtime settings
  download_models.py  One-step model and binary setup
  keyboard_activation.py  Spacebar listener
  recorder.py         16 kHz mono WAV recording with silence detection
  stt_whisper.py      whisper.cpp tiny multilingual transcription
  cloud_client.py     FastAPI Server-Sent Events client
  tts_piper.py        Piper synthesis with sentence buffering
  audio_player.py     Local WAV playback command wrapper
  main.py             End-to-end orchestrator
  local_audio_test.py Local activation, mic/STT, and TTS hardware test
  smoke_test.py       No-JWT audio and chatbot reachability smoke test
  requirements.txt    Python dependencies
```

Downloaded models, binaries, and temporary WAV files are intentionally ignored by Git.

## Install Dependencies

Linux audio capture and playback require ALSA tools. On Debian or Ubuntu-based
images, install them first:

```bash
sudo apt update
sudo apt install -y alsa-utils
```

Then install the Python dependencies:

```bash
python3 -m pip install -r edge/audio_io/requirements.txt
```

You can list available ALSA capture devices with:

```bash
arecord -l
```

## Download Models And Binaries

Run the setup CLI after installing Python dependencies:

```bash
python -m edge.audio_io.download_models
```

Assets are stored under `edge/audio_io/models/` by default. Override this with:

```bash
export EDGE_AUDIO_MODELS_DIR=/opt/edge-audio-models
```

The setup handles:

- whisper.cpp binary: downloads a platform release archive when the current CPU is supported, preferring the real `whisper-cli` binary over deprecated compatibility stubs, or uses `EDGE_AUDIO_WHISPER_BINARY_URL`.
- Whisper tiny multilingual model: downloads `ggml-tiny.bin` from the whisper.cpp Hugging Face model repository.
- Piper binary: downloads a platform release archive when the current CPU is supported, or uses `EDGE_AUDIO_PIPER_BINARY_URL`.
- Piper voice model: downloads `en_US-lessac-medium.onnx` plus its `.onnx.json` config from the Piper voices repository.

For stricter integrity checks, set SHA-256 variables before running setup:

```bash
export EDGE_AUDIO_WHISPER_MODEL_SHA256=<sha256>
export EDGE_AUDIO_PIPER_BINARY_SHA256=<sha256>
export EDGE_AUDIO_PIPER_VOICE_MODEL_SHA256=<sha256>
```

## Required Cloud Endpoint

The audio client expects the cloud FastAPI app to expose:

```text
POST /api/chatbot/chat/stream
Authorization: Bearer <JWT>  # optional; omitted requests use visitor/PUBLIC access
Accept: text/event-stream
Content-Type: application/json

{"query":"Where is the library?","device_id":"entry-gate-01"}
```

The endpoint streams Server-Sent Events:

```text
event: chunk
data: {"text":"Sentence-sized answer text."}

event: done
data: {"answer":"...","citations":[],"access_granted":true,"status_message":null,"response_time_ms":1234,"query_id":42}
```

The existing non-streaming endpoint remains available at `POST /api/chatbot/chat`.

## Run The Pipeline

Standalone audio can run with or without an explicit JWT. Without
`EDGE_AUDIO_CLOUD_BEARER_TOKEN`, the chatbot uses visitor/PUBLIC access. If a
query needs protected documents, the cloud response asks the edge user to scan
their face. If `EDGE_AUDIO_CLOUD_API_URL` is unset, it defaults to
`${EDGE_SYNC_CLOUD_URL}/api/chatbot/chat/stream`. If `EDGE_AUDIO_CLOUD_DEVICE_ID`
is unset, it defaults to `EDGE_SYNC_DEVICE_ID`.

```bash
export EDGE_SYNC_CLOUD_URL=http://<cloud-host>:8000
export EDGE_SYNC_DEVICE_ID=entry-gate-01
```

Optionally provide a JWT for higher RBAC access:

```bash
export EDGE_AUDIO_CLOUD_BEARER_TOKEN=<face-auth-jwt>
```

Start the normal spacebar-activated loop:

```bash
python -m edge.audio_io.main
```

Press the space bar in the terminal to start each chatbot recording.

For a quick recording test without waiting for spacebar activation:

```bash
python -m edge.audio_io.main --once --skip-activation
```

## Local Audio Hardware Test

Run this on the edge device when you only want to test the local microphone,
spacebar activation, Whisper STT, Piper TTS, and playback. This script does not import the
chatbot client and does not call any cloud endpoint.

```bash
python -m edge.audio_io.local_audio_test
```

The local test defaults to the system's default ALSA capture device and the
`edge/audio_io/models/whisper/whisper-cli` binary. Override those when needed
with `--alsa-capture-device` or `--whisper-binary-path`.

By default, this:

- synthesizes and plays a local Piper TTS prompt
- waits for spacebar activation
- records one microphone utterance
- transcribes that recording with whisper.cpp

Useful flags:

```bash
python -m edge.audio_io.local_audio_test --list-devices
python -m edge.audio_io.local_audio_test --setup-assets
python -m edge.audio_io.local_audio_test --alsa-capture-device plughw:1,0
python -m edge.audio_io.local_audio_test --skip-activation
python -m edge.audio_io.local_audio_test --skip-playback
python -m edge.audio_io.local_audio_test --keep-audio-files
```

## No-JWT Smoke Test

Run this on the edge device to test local audio output and cloud chatbot
reachability without setting `EDGE_AUDIO_CLOUD_BEARER_TOKEN`:

```bash
export EDGE_SYNC_CLOUD_URL=http://<cloud-host>:8000
export EDGE_SYNC_DEVICE_ID=entry-gate-01
python -m edge.audio_io.smoke_test
```

By default, this:

- checks Piper TTS synthesis and local playback
- calls unauthenticated `GET /api/chatbot/health`
- attempts unauthenticated `POST /api/chatbot/chat/stream`

Without JWT, the normal stream should answer from PUBLIC documents. If the
question appears to require protected documents, the response asks for face
authentication and the edge access-control integration retries after a successful
scan.

To also test microphone recording and Whisper STT:

```bash
python -m edge.audio_io.smoke_test --record-stt
```

Useful flags:

```bash
python -m edge.audio_io.smoke_test --skip-playback
python -m edge.audio_io.smoke_test --setup-assets
python -m edge.audio_io.smoke_test --require-unauth-chat-success
```

## Environment Variables

Common settings:

- `EDGE_AUDIO_LOG_LEVEL`: logging level, default `INFO`.
- `EDGE_AUDIO_MODELS_DIR`: model and binary directory, default `edge/audio_io/models`.
- `EDGE_AUDIO_TEMP_DIR`: temporary WAV directory, default `edge/audio_io/tmp`.
- `EDGE_AUDIO_SAMPLE_RATE`: default `16000`.
- `EDGE_AUDIO_PLAYER_COMMAND`: playback command, default `aplay`.

Recording:

- `EDGE_AUDIO_RECORDING_BACKEND`: recording backend, default `arecord` on Linux and `sounddevice` on Windows.
- `EDGE_AUDIO_RECORDER_COMMAND`: recording command for the `arecord` backend, default `arecord`.
- `EDGE_AUDIO_ALSA_CAPTURE_DEVICE`: optional ALSA capture device such as `hw:1,0` or `plughw:1,0`.
- `EDGE_AUDIO_MICROPHONE_DEVICE`: optional PortAudio device name or index, used only with `EDGE_AUDIO_RECORDING_BACKEND=sounddevice`.
- `EDGE_AUDIO_MAX_RECORD_SECONDS`: default `12`.
- `EDGE_AUDIO_MIN_RECORD_SECONDS`: default `0.6`.
- `EDGE_AUDIO_SILENCE_DURATION_SECONDS`: default `1.2`.
- `EDGE_AUDIO_SILENCE_RMS_THRESHOLD`: default `500`.

Whisper:

- `EDGE_AUDIO_WHISPER_BINARY_PATH`: whisper.cpp CLI path.
- `EDGE_AUDIO_WHISPER_BINARY_URL`: archive URL when the platform default is not suitable.
- `EDGE_AUDIO_WHISPER_MODEL_PATH`: `ggml-tiny.bin` path.
- `EDGE_AUDIO_WHISPER_THREADS`: optional thread count.
- `EDGE_AUDIO_WHISPER_TIMEOUT_SECONDS`: default `120`.

Cloud:

- `EDGE_AUDIO_CLOUD_API_URL`: explicit stream URL. If unset, defaults to `${EDGE_SYNC_CLOUD_URL}/api/chatbot/chat/stream`.
- `EDGE_AUDIO_CLOUD_BEARER_TOKEN`: fixed JWT used in `Authorization` for standalone audio runs.
- `EDGE_AUDIO_CLOUD_DEVICE_ID`: device ID sent to the cloud. If unset, defaults to `EDGE_SYNC_DEVICE_ID`.
- `EDGE_AUDIO_CLOUD_SESSION_ID`: optional JWT session id.
- `EDGE_AUDIO_CLOUD_RETRIES`: default `2`.

Piper:

- `EDGE_AUDIO_PIPER_BINARY_PATH`: Piper executable path.
- `EDGE_AUDIO_PIPER_BINARY_URL`: archive URL when the platform default is not suitable.
- `EDGE_AUDIO_PIPER_VOICE_MODEL_PATH`: voice `.onnx` path.
- `EDGE_AUDIO_PIPER_TIMEOUT_SECONDS`: default `60`.
- `EDGE_AUDIO_TTS_MIN_CHUNK_CHARS`: default `40`.
- `EDGE_AUDIO_TTS_MAX_CHUNK_CHARS`: default `240`.

## ARM Cortex-A53 Notes

- Use the tiny multilingual Whisper model; larger models are likely too slow for interactive use.
- Limit Whisper threads to the number of available cores with `EDGE_AUDIO_WHISPER_THREADS` and test thermals under sustained load.
- Piper voices vary in latency; use a low or medium voice first and benchmark before changing voices.
- Local playback uses `aplay` by default. Replace `EDGE_AUDIO_PLAYER_COMMAND` if the target image uses a different audio stack.
