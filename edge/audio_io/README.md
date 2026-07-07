# Edge Audio I/O Terminal

Thin audio terminal for the edge device. Records microphone audio, uploads it
to the cloud chatbot API, receives a text + audio response, and plays the audio
response through the speaker.

There is **no local STT and no local TTS** — all speech understanding and speech
generation happens in the cloud via the Gemini audio pipeline.

```text
space bar -> record 16kHz mono WAV -> multipart POST to cloud -> receive text + base64 PCM -> play 24kHz audio
```

## Architecture

This module is one half of the two-step Gemini audio pipeline. The edge device
handles only the physical I/O:

1. **Record**: Capture 16 kHz mono int16 PCM audio from the microphone using
   sounddevice (PortAudio). Silence detection automatically stops recording
   when the user finishes speaking.
2. **Upload**: Send the recorded WAV file as a multipart HTTP POST to the cloud
   audio API endpoint.
3. **Receive**: Parse the JSON response which contains validated text, optional
   base64-encoded PCM audio (24 kHz mono), cited sources, and a status field.
4. **Play**: Decode the base64 audio and play it through the default output
   device using sounddevice.

The cloud side (in `cloud/RagChatbot/`) handles audio query extraction, prompt
injection detection, RBAC-filtered retrieval, response generation via Gemini,
and response validation.

## Folder Contents

```text
edge/audio_io/
  __init__.py             Exports AudioIOConfig
  config.py               Environment-driven runtime settings (AudioIOConfig dataclass)
  recorder.py             16 kHz mono WAV recording with RMS-based silence detection (sounddevice)
  audio_player.py         PCM and WAV playback through default output device (sounddevice)
  cloud_audio_client.py   Multipart HTTP client for the cloud chatbot audio API
  keyboard_activation.py  Space bar listener for activation
  main.py                 End-to-end orchestrator: AudioInteractionPipeline
  requirements.txt        Python dependencies
  README.md               This file
```

Temporary WAV recording files are stored under `tmp/` (gitignored).

## Dependencies

Python packages (see `requirements.txt`):

- `numpy>=1.26,<2` — PCM audio buffer manipulation
- `requests>=2.31` — HTTP client for cloud API communication
- `sounddevice>=0.4.6` — PortAudio wrapper for microphone capture and speaker playback

On Linux, PortAudio and ALSA must also be installed:

```bash
sudo apt update
sudo apt install -y libportaudio2 portaudio19-dev alsa-utils
```

## Environment Variables

All settings are driven by environment variables, read at startup by
`AudioIOConfig`.

### General

| Variable | Default | Purpose |
|----------|---------|---------|
| `EDGE_AUDIO_LOG_LEVEL` | `INFO` | Logging verbosity |
| `EDGE_AUDIO_TEMP_DIR` | `edge/audio_io/tmp` | Temporary WAV file directory |

### Recording

| Variable | Default | Purpose |
|----------|---------|---------|
| `EDGE_AUDIO_MICROPHONE_DEVICE` | (none) | PortAudio device name or index; `None` = system default |
| `EDGE_AUDIO_SAMPLE_RATE` | `16000` | Recording sample rate in Hz |
| `EDGE_AUDIO_CHANNELS` | `1` | Number of recording channels |
| `EDGE_AUDIO_RECORDING_BLOCK_MS` | `100` | Block size for stream reads (milliseconds) |
| `EDGE_AUDIO_RECORDING_BACKEND` | `sounddevice` | Recording backend (only `sounddevice` is supported) |
| `EDGE_AUDIO_MIN_RECORD_SECONDS` | `0.6` | Minimum recording duration before silence stops capture |
| `EDGE_AUDIO_MAX_RECORD_SECONDS` | `12.0` | Maximum recording duration (hard limit) |
| `EDGE_AUDIO_SILENCE_DURATION_SECONDS` | `1.2` | Consecutive silence required before auto-stop |
| `EDGE_AUDIO_SILENCE_RMS_THRESHOLD` | `500.0` | RMS amplitude below which audio is considered silence |

### Cloud API

| Variable | Default | Purpose |
|----------|---------|---------|
| `EDGE_AUDIO_CLOUD_API_URL` | `{EDGE_SYNC_CLOUD_URL}/api/chatbot/chat/audio` | Cloud audio endpoint URL |
| `EDGE_AUDIO_CLOUD_BEARER_TOKEN` | (none) | JWT bearer token; omitted = visitor/PUBLIC access |
| `EDGE_AUDIO_CLOUD_DEVICE_ID` | `{EDGE_SYNC_DEVICE_ID}` or `entry-gate-01` | Device identifier sent with each request |
| `EDGE_AUDIO_CLOUD_SESSION_ID` | (none) | Existing JWT session ID hint |
| `EDGE_AUDIO_CLOUD_CONNECT_TIMEOUT_SECONDS` | `5.0` | HTTP connection timeout |
| `EDGE_AUDIO_CLOUD_READ_TIMEOUT_SECONDS` | `90.0` | HTTP read timeout (generation can take tens of seconds) |
| `EDGE_AUDIO_CLOUD_RETRIES` | `2` | Number of retries on transient network failure |
| `EDGE_AUDIO_CLOUD_RETRY_BACKOFF_SECONDS` | `1.0` | Base backoff between retries (multiplied by attempt number) |

### Playback

| Variable | Default | Purpose |
|----------|---------|---------|
| `EDGE_AUDIO_OUTPUT_SAMPLE_RATE` | `24000` | Expected output sample rate from cloud audio (Hz) |

Also inherited from the broader edge environment:

- `EDGE_SYNC_CLOUD_URL` — base URL used when `EDGE_AUDIO_CLOUD_API_URL` is not set
- `EDGE_SYNC_DEVICE_ID` — fallback device identifier

## CLI Arguments

```text
python edge/audio_io/main.py [--once] [--skip-activation] [--log-level LEVEL]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--once` | `False` | Run one interaction and exit (useful for testing) |
| `--skip-activation` | `False` | Start recording immediately without waiting for space bar |
| `--log-level` | (env default) | Override `EDGE_AUDIO_LOG_LEVEL` |

## How to Run

Set the cloud endpoint and device identifier:

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

Press the space bar in the terminal to start each chatbot recording. Press `q`
and then space to quit.

For a quick single interaction without waiting for the space bar (useful for
smoke testing):

```bash
python -m edge.audio_io.main --once --skip-activation
```

Alternatively, run directly from the repo root:

```bash
python edge/audio_io/main.py --once
```

## Cloud Endpoint

The edge module expects the cloud FastAPI app to expose:

```text
POST /api/chatbot/chat/audio
Authorization: Bearer <JWT>  # optional; omitted = visitor/PUBLIC access
Content-Type: multipart/form-data

Fields:
  audio       WAV file (16 kHz, mono, 16-bit) — required
  device_id   String identifier — optional
  session_id  Integer session hint — optional
```

Success response (HTTP 200):

```json
{
  "text_response": "The library is open from 8am to 10pm on weekdays.",
  "audio_response": "<base64-encoded 24kHz mono PCM>",
  "sources": [
    {
      "chunk_id": 12,
      "document_id": 3,
      "document_title": "Library Hours",
      "chunk_index": 0,
      "access_level": "PUBLIC",
      "excerpt": "The library is open from 8am to 10pm..."
    }
  ],
  "status": "ok",
  "access_granted": true,
  "error_message": null,
  "response_time_ms": 2400,
  "query_id": 9921
}
```

### Status Field Semantics

| Status | Meaning | Audio Response | Sources |
|--------|---------|----------------|---------|
| `ok` | Normal success | base64 PCM audio | cited chunks |
| `blocked` | Prompt injection detected in extracted query | `null` | `[]` |
| `no_access` | No RBAC access to matching documents | `null` | `[]` |
| `auth_required` | JWT missing/invalid for protected content | `null` | `[]` |
| `validation_failed` | Response text/citations failed validation | `null` | `[]` |
| `error` | Internal failure (Gemini, audio decode, etc.) | `null` | `[]` |

## Error Handling

- **Microphone failure**: If PortAudio or the microphone device is unavailable,
  the pipeline logs the error and exits.
- **Network failure**: The cloud client retries with exponential backoff
  (`EDGE_AUDIO_CLOUD_RETRIES` x `EDGE_AUDIO_CLOUD_RETRY_BACKOFF_SECONDS`).
  After exhausting retries, the error is logged.
- **Cloud error (4xx/5xx)**: Raised as `CloudAudioClientError` with the HTTP
  status code. 401/403 responses trigger the `auth_required_handler` if
  configured.
- **Gemini failure**: The cloud returns `status:"error"` with a generic message;
  the edge logs it and returns to the activation state.
- **Playback failure**: `AudioPlaybackError` is raised and logged.
- **Empty audio response**: If the cloud returns text without audio, the text is
  logged and the pipeline returns to activation.

## Comparison with Legacy Module

The legacy module (`edge/audio_io_legacy/`) used local whisper.cpp STT and Piper
TTS, with SSE streaming from the cloud. The new module removes all local ML
dependencies:

| Aspect | Legacy (`audio_io_legacy`) | New (`audio_io`) |
|--------|---------------------------|------------------|
| Speech-to-text | Local whisper.cpp | Cloud Gemini (audio query extraction) |
| Text-to-speech | Local Piper TTS | Cloud Gemini (response generation) |
| Cloud protocol | SSE streaming | One-shot HTTP multipart |
| Model downloads | Required (whisper + Piper) | None |
| Files | 12 Python files + README | 7 Python files + README |
