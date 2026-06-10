# Smart Campus Edge Kiosk Setup

This directory contains all components required to run the local edge device, combining camera-based facial recognition, liveness checks, and database synchronization.

---

## 1. Prerequisites

### A. Model Weights
Verify that the following models are located in `edge/models/`:
* `face_detection_yunet_2023mar_int8bq.onnx` (Face detection ONNX network)
* `edgeface_xxs.pt` (Facial feature extraction embedding network)

### B. Hardware requirements
* A connected webcam or external USB camera module.
* OpenCV-compatible GUI display environment (for window rendering).

---

## 2. Configuration (`edge/run_edge.py`)

Open `edge/run_edge.py` and adjust the variables inside the `main()` function:

* **`CLOUD_URL`**: Point this to the central server IP on your LAN network (e.g., `http://192.168.1.50:8000`).
* **`DEVICE_ID`**: Set a unique string representing this specific gate kiosk (e.g., `gate-west-01`).
* **`DEVICE_NAME`**: Set a readable location label (e.g., `West Campus Gateway Kiosk`).
* **`LOCAL_IP`**: Set the local LAN IP address of this edge device (e.g., `192.168.1.110`).
* **`LOCAL_PORT`**: Port to host the push notification receiver (default `8000`).
* **`CAM_INDEX`**: OpenCV webcam index. Change `0` to your external camera index (e.g., `1` or `4`) if the internal feed is not selected.

---

## 3. Running the Edge Kiosk

Run the edge kiosk script from the project root directory (`Code_FYP`):

```powershell
.venv\Scripts\python edge/run_edge.py
```

### What Happens:
1. **Schema Check**: Initializes the local SQLite database file `edge/device_local.db` if it does not exist.
2. **Upstream Daemon**: Starts background threads to register heartbeats to the cloud every 30 seconds and replay offline-buffered verification logs in chronological order.
3. **Downstream Poller**: Starts a polling thread querying cloud changes (profile vectors, node RBAC permissions) and commits them to SQLite.
4. **Push Receiver**: Launches a background Uvicorn server to listen for instant user deactivation push requests from the cloud.
5. **UI Kiosk Main Loop**: Starts the camera rendering frame capture loop, runs spoof checks, and classifies matches on the main thread.

### Camera Shortcuts:
* Press **`q`** while focusing on the "Edge Kiosk" OpenCV camera window to stop the loops and shutdown background workers cleanly.
