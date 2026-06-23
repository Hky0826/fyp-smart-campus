# Edge Face Recognition

Hailo-based face-recognition pipelines for the EdgeMind device. The previous
OpenCV/EdgeFace implementation is kept locally as `edge_legacy/` and is ignored
by Git.

## Step 1: Prepare the Device

Run these commands on the EdgeMind device from the repository root:

```bash
cd /path/to/Code_FYP
python3 --version
```

Install the normal Python dependencies:

```bash
python3 -m pip install -r edge/requirements.txt
```

Install or verify HailoRT with the helper script:

```bash
bash edge/install_hailort.sh
```

The script first runs `python3 -m edge.src.hailo.diagnostics`. If
`hailo_platform_importable` is already `true`, it stops successfully. If it is
`false`, the script tries these installation sources in order:

- system Python HailoRT linked into the active `.venv`, when `/usr/bin/python3` can already import `hailo_platform`
- `HAILORT_WHEEL=/path/to/hailort-...whl`
- `HAILORT_DEB_DIR=/path/to/folder/with/debs`
- apt packages exposed by the EdgeMind image, such as `hailo-all`, `hailort`, or `python3-hailort`

If the diagnostic shows `hailo_device: true` but `hailo_platform_importable: false`
inside `.venv/bin/python3`, the hardware driver is visible but the virtualenv is
missing the Python binding. Rerun the helper while the venv is active; it will
try to link the system HailoRT package into `.venv` automatically.

Examples:

```bash
HAILORT_WHEEL=/path/to/hailort-<version>-cp<python>-<platform>.whl \
  bash edge/install_hailort.sh

HAILORT_DEB_DIR=/path/to/hailort/debs \
  bash edge/install_hailort.sh
```

The Python module is `hailo_platform`; it comes from HailoRT/pyHailoRT, not from
a normal PyPI package named `hailo_platform`. Continue only when the diagnostic
reports:

```text
hailo_platform_importable: true
```

If HailoRT reports a driver/library mismatch, such as driver `4.23.0` with
library `4.22.0`, inspect the stack with:

```bash
bash edge/diagnose_hailort_stack.sh
```

The driver and user-space library must use the same HailoRT version. Prefer
reinstalling the user-space `hailort` package to match the installed driver, or
install matching vendor `.deb` files for both `hailort` and `hailort-pcie-driver`.

If HailoRT reports `failed to create vdevice` or `there are not enough free
devices`, first make sure no other process is holding the accelerator:

```bash
sudo fuser -v /dev/hailo0
ps -ef | grep -E "edge|uvicorn|python" | grep -v grep
```

Stop any old API or pipeline process and rerun the direct pipeline. The direct
pipeline code shares one Hailo VDevice between detector and embedder models, so
this error usually means a previous process is still alive or another service is
using `/dev/hailo0`.

## Step 2: Prepare the HEF Models

Expected model placement:

```text
edge/
  models/
    access_control/
      arcface_mobilefacenet.hef
    surveillance/
      scrfd_10g.hef  # shared detector for access control and surveillance
      arcface_r50.hef
```

Run the model helper:

```bash
bash edge/download_models.sh
```

The script can copy HEFs from `HAILO_HEF_SOURCE_DIR` or download from URLs you
provide in `ARCFACE_MOBILEFACENET_HEF_URL`, `SCRFD_10G_HEF_URL`, and
`ARCFACE_R50_HEF_URL`. If your Hailo package requires authenticated manual
download or local compilation, place the files manually at the paths above.

## Step 3: Prepare the Database

The pipeline reads already-created embeddings from SQLite table
`device_user_face_embeddings`, joined to `device_users` for active/inactive
status. Enrollment is intentionally not implemented here.

Set the database path if needed:

```bash
export EDGE_HAILO_DB_PATH=/path/to/device_local.db
```

If unset, the code uses `edge/data/device_local.db`.

Create or refresh the local schema with:

```bash
python edge/setup_sqlite.py
```

To target a specific file without setting `EDGE_HAILO_DB_PATH`, run:

```bash
python edge/setup_sqlite.py --database /path/to/device_local.db
```

The runtime sync engine also uses the same setup code automatically when it
starts. Each user can have multiple synced embeddings by template and model,
for example `front`, `left_30`, `right_60`, `slightly_up`, `slightly_down`, and
`low_light`.

## Step 4: Configure Synchronization

The direct access-control, surveillance, and combined runners start the sync
engine automatically. The sync engine initializes the local SQLite schema, pulls
cloud deltas into `device_users`, `device_user_face_embeddings`,
`device_user_roles`, and `device_node_rbac`, sends device heartbeats, exposes
the local push endpoints, and replays pending `device_auth_logs` upstream.

Default sync configuration matches the old edge runner and can be overridden:

```bash
export EDGE_SYNC_CLOUD_URL=http://10.178.101.3:8000
export EDGE_SYNC_DEVICE_ID=entry-gate-01
export EDGE_SYNC_DEVICE_NAME="North Entry Gate Kiosk"
export EDGE_SYNC_LOCAL_IP=10.178.101.2
export EDGE_SYNC_LOCAL_PORT=8001
```

Useful optional settings:

```bash
export EDGE_SYNC_DOWNSTREAM_POLL_SECONDS=30
export EDGE_SYNC_LOG_PUSH_INTERVAL_SECONDS=600
export EDGE_SYNC_ENABLED=0  # disable sync for offline tests
```

Local push endpoints exposed by the sync engine:

- `POST /api/edge/deactivate`
- `POST /api/edge/trigger-sync`

## Step 5: Run the Pipeline

Run access control and surveillance together on the default camera `/dev/video4`
with local OpenCV display windows:

```bash
python3 -m edge.src.pipelines.run_both
```

Access control only on the default camera `/dev/video4` with display:

```bash
python3 -m edge.src.pipelines.access_control
```

Surveillance only on the default camera `/dev/video4` with display:

```bash
python3 -m edge.src.pipelines.surveillance
```

To use a different camera or run headless, pass explicit flags:

```bash
python3 -m edge.src.pipelines.run_both --camera /dev/video2 --no-display
```

Camera sources can be `/dev/video4`, a numeric OpenCV index, RTSP URL, or video
file path.
The display window mirrors the camera by default; pass `--no-mirror` to show the
raw camera orientation. Press `q` in an OpenCV window to exit cleanly.

Display mode requires a local GUI session. If running over SSH, Docker, or a
headless service, use `--no-display` or configure X11/Wayland forwarding
first. On the EdgeMind desktop session, `QT_QPA_PLATFORM=xcb` may be required
before launching the pipeline.

## Step 6: Tune Thresholds

Similarity thresholds are configurable:

```bash
export EDGE_ACCESS_RECOGNITION_THRESHOLD=0.75
export EDGE_SURVEILLANCE_RECOGNITION_THRESHOLD=0.62
```

These values must be tuned using real camera footage from the target device.
Access control should remain strict. Surveillance can use a separate threshold
to improve recall for angled, non-frontal, up/down, and low-light views while
still returning `unknown` below threshold.

## Alternative: Run the API

Use the API only if another service needs HTTP endpoints. The direct pipeline
commands above are enough for normal device testing.

Start the API:

```bash
uvicorn edge.src.api.main:app --host 0.0.0.0 --port 8080
```

Useful endpoints:

- `GET /health`
- `POST /access-control/frame`
- `POST /surveillance/frame`
- `GET /models/status`
- `GET /database/status`

Frame endpoints accept multipart upload field `file`. Access control also
accepts optional form field `target_user_id` for strict 1:1 verification.

## Alternative: Run with Docker

Docker is optional. Use it only when you want a containerized deployment. For
simple testing on the EdgeMind device, running the pipeline directly is easier.

The compose file exposes `/dev/hailo0` and `/dev/video4`, and mounts
`edge/models` plus `edge/data`.

The default Docker image is plain `python:3.11-slim`, so it does not include
`hailo_platform`. Use one of the two options below.

### Docker Option A: HailoRT Wheel

Copy the HailoRT Python wheel into the build context, then build and run:

```bash
mkdir -p edge/vendor
# Copy the HailoRT Python wheel into edge/vendor first.
export EDGE_HAILORT_WHEEL=edge/vendor/hailort-<version>-cp311-<platform>.whl
docker compose -f edge/docker/docker-compose.face.yml up --build
```

The wheel must match the container Python version. The default image uses Python
3.11, so the wheel should be a `cp311` wheel.

### Docker Option B: HailoRT Base Image

If EdgeMind provides a container image that already includes HailoRT, use it as
the base image:

```bash
export EDGE_BASE_IMAGE=<hailort-enabled-image>
docker compose -f edge/docker/docker-compose.face.yml up --build
```

### Docker Verification

The container runs this check before starting the API:

```bash
python -m edge.src.hailo.diagnostics
```

To run the same check manually after the container starts:

```bash
docker compose -f edge/docker/docker-compose.face.yml exec edge-face \
  python -m edge.src.hailo.diagnostics
```

For a local API-only smoke test without HailoRT, disable the startup guard:

```bash
EDGE_REQUIRE_HAILORT=0 docker compose -f edge/docker/docker-compose.face.yml up --build
```

## Pipeline Behavior

Access control:

- Detector: `models/surveillance/scrfd_10g.hef`
- Embedder: `models/access_control/arcface_mobilefacenet.hef`
- Uses a liveness/spoofing heuristic for access decisions
- Rejects frames with more than one face: `Only one user is allowed within the frame.`
- Denies unknown, low-confidence, inactive, or liveness-failed users

Surveillance:

- Detector: `models/surveillance/scrfd_10g.hef`
- Embedder: `models/surveillance/arcface_r50.hef`
- Supports multiple faces per frame
- Does not run spoofing/liveness checks
- Reports identities, scores, boxes, matched template names, and timestamps
