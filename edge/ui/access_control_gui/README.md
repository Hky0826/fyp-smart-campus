# Native Edge Access-Control GUI

PySide6/QML replacement for the previous browser kiosk frontend in
`edge/ui/access_control_frontend`.

The native GUI is still a presentation layer. It reuses the existing FastAPI
kiosk facade and does not change backend authentication, RBAC, face matching,
chatbot behavior, SQLite schema, sync, JWT/session handling, or door access
logic.

## Web-to-Native Migration Map

| Web frontend | Native replacement |
| --- | --- |
| `App.tsx` shell | `qml/Main.qml` |
| Browser `<video>` live camera | `controllers/camera_controller.py` + `qml/CameraView.qml` |
| Face-box overlay | `CameraView.qml` mapped from kiosk API `bboxes` |
| Floating chatbot button | `qml/ChatbotButton.qml` |
| Fullscreen chatbot overlay | `qml/ChatbotView.qml` |
| Access border/result states | `qml/AccessOverlay.qml` and `qml/AccessResultOverlay.qml` |
| Session locked state | `qml/SessionLockedOverlay.qml` |
| Offline/backend error state | `qml/OfflineView.qml` |
| Setup/model/database state | `controllers/device_controller.py` + `qml/SetupView.qml` |
| Device status pills | `qml/DeviceStatusBar.qml` |
| `kioskClient.ts` | `controllers/api_client.py` |
| `kioskStateMachine.ts` | `controllers/access_controller.py` |
| Browser MediaRecorder loop | `controllers/chatbot_controller.py` using existing `edge.audio_io` recorder/player |

## API Contracts Reused

The GUI calls the existing local edge API:

- `GET /kiosk/state`
- `GET /kiosk/events`
- `POST /kiosk/access/frame`
- `POST /kiosk/chat/verify/frame`
- `POST /kiosk/chat/presence/frame`
- `POST /kiosk/chat/message`
- `POST /kiosk/chat/audio`
- `POST /kiosk/chat/lock`
- `POST /kiosk/chat/end`
- `POST /kiosk/chat/audio/stop`
- `GET /database/status`
- `GET /models/status`

## Preserved Runtime Behavior

- Camera frames are submitted every `EDGE_GUI_CAMERA_FRAME_INTERVAL_MS`
  milliseconds, default `500`, matching the web frontend.
- Access verification continues while the chatbot is fullscreen.
- Door access overlays are rendered above the chatbot.
- Chatbot owner verification and owner-presence checks use the same kiosk API.
- If the owner is absent during chat, the same frame is also sent for access
  verification, preserving door-access priority.
- Chatbot JWTs stay server-side in the kiosk API state store.
- Chat history and citations come from the existing session response.
- Audio input/output uses existing edge audio components and the same
  `/kiosk/chat/audio` proxy.
- SQLite setup, cloud sync, RBAC, model thresholds, and unlock behavior remain
  in the backend.

## Installation

From the repository root on the Linux edge device:

```bash
python3 -m pip install -r edge/facial_recognition/requirements.txt
python3 -m pip install -r edge/audio_io/requirements.txt
python3 -m pip install -r edge/ui/access_control_gui/requirements.txt
```

Linux audio backends need ALSA tools:

```bash
sudo apt update
sudo apt install -y alsa-utils
```

## Start the Backend

Run the existing edge API first:

```bash
uvicorn edge.facial_recognition.src.api.main:app --host 0.0.0.0 --port 8080
```

The GUI defaults to `http://127.0.0.1:8080`. Override it if needed:

```bash
export EDGE_GUI_API_BASE_URL=http://127.0.0.1:8080
```

## Start the Native GUI

```bash
python3 -m edge.ui.access_control_gui.main
```

If `/dev/video4` is not opening, list the board cameras and force the one that
can return frames:

```bash
ls -l /dev/video*
export EDGE_GUI_CAMERA=/dev/video4
export EDGE_GUI_CAMERA_NO_FALLBACK=1
python3 -m edge.ui.access_control_gui.main
```

The GUI opens `/dev/video*` devices with OpenCV's V4L2 backend. If another
process owns the camera, stop it first:

```bash
sudo fuser -v /dev/video4
```

Useful environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `EDGE_GUI_API_BASE_URL` | `http://127.0.0.1:8080` | Local edge API base URL |
| `EDGE_GUI_CAMERA` | `EDGE_ACCESS_CAMERA` / `EDGE_CAMERA` / `/dev/video4` | Camera source |
| `EDGE_GUI_CAMERA_FALLBACKS` | `/dev/video0,/dev/video1,/dev/video2,/dev/video3,/dev/video4,/dev/video5,0,1` | Extra camera sources tried when the primary source fails |
| `EDGE_GUI_CAMERA_NO_FALLBACK` | unset | Set to `1` to try only `EDGE_GUI_CAMERA` |
| `EDGE_GUI_CAMERA_FRAME_INTERVAL_MS` | `500` | Frame verification interval |
| `EDGE_GUI_ACCESS_RESULT_HOLD_MS` | `4000` | Local fallback result hold duration |
| `EDGE_GUI_VOICE_RECORDING_MS` | `5500` | Audio chunk duration |
| `EDGE_GUI_VOICE_RESTART_DELAY_MS` | `250` | Delay between audio chunks |
| `EDGE_GUI_TTS_OUTPUT_SAMPLE_RATE` | `24000` | Cloud PCM playback rate |
| `EDGE_GUI_QT_BACKEND` | `software` on Linux | Qt Quick scene graph backend |
| `EDGE_GUI_QPA_PLATFORM` | `linuxfb`, or `wayland` when `WAYLAND_DISPLAY` is set | Optional Qt platform override |

On i.MX/embedded Linux boards, the GUI defaults Qt Quick to the software scene
graph and avoids `xcb` unless explicitly requested. This avoids EGL/OpenGL and
desktop XCB dependency failures such as:

```text
QEGLPlatformContext: Failed to create context: 3004
Failed to initialize graphics backend for OpenGL.
Could not load the Qt platform plugin "xcb"
```

To explicitly force the framebuffer path from the shell:

```bash
export EDGE_GUI_QPA_PLATFORM=linuxfb
export QT_QUICK_BACKEND=software
python3 -m edge.ui.access_control_gui.main
```

If the device is running a Wayland desktop session:

```bash
export EDGE_GUI_QPA_PLATFORM=wayland
export QT_QUICK_BACKEND=software
python3 -m edge.ui.access_control_gui.main
```

If the device image has a working Qt/OpenGL stack, you can opt back into the
hardware path:

```bash
export EDGE_GUI_QPA_PLATFORM=wayland
export EDGE_GUI_QT_BACKEND=opengl
python3 -m edge.ui.access_control_gui.main
```

## Linux Autostart Example

Create `/etc/systemd/system/edge-access-gui.service`:

```ini
[Unit]
Description=Edge native access-control GUI
After=network-online.target edge-face-api.service

[Service]
WorkingDirectory=/path/to/Code_FYP
Environment=EDGE_GUI_API_BASE_URL=http://127.0.0.1:8080
Environment=EDGE_GUI_QPA_PLATFORM=linuxfb
Environment=QT_QUICK_BACKEND=software
ExecStart=/usr/bin/python3 -m edge.ui.access_control_gui.main
Restart=always
RestartSec=3
User=edge

[Install]
WantedBy=graphical.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable edge-access-gui.service
sudo systemctl start edge-access-gui.service
```
