# Edge Hailo Face Recognition

Independent Hailo-based face-recognition pipelines for the EdgeMind device.
This package does not import from the existing `edge` folder at runtime.

## Step 1: Prepare the Device

Run these commands on the EdgeMind device from the repository root:

```bash
cd /path/to/Code_FYP
python3 --version
```

Install the normal Python dependencies:

```bash
python3 -m pip install -r edge_hailo/requirements.txt
```

Install or verify HailoRT with the helper script:

```bash
bash edge_hailo/install_hailort.sh
```

The script first runs `python3 -m edge_hailo.src.hailo.diagnostics`. If
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
  bash edge_hailo/install_hailort.sh

HAILORT_DEB_DIR=/path/to/hailort/debs \
  bash edge_hailo/install_hailort.sh
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
bash edge_hailo/diagnose_hailort_stack.sh
```

The driver and user-space library must use the same HailoRT version. Prefer
reinstalling the user-space `hailort` package to match the installed driver, or
install matching vendor `.deb` files for both `hailort` and `hailort-pcie-driver`.

## Step 2: Prepare the HEF Models

Expected model placement:

```text
edge_hailo/
  models/
    access_control/
      scrfd_2.5g.hef
      arcface_mobilefacenet.hef
    surveillance/
      scrfd_10g.hef
      arcface_r50.hef
```

Run the model helper:

```bash
bash edge_hailo/download_models.sh
```

The script can copy HEFs from `HAILO_HEF_SOURCE_DIR` or download from URLs you
provide in `SCRFD_25G_HEF_URL`, `ARCFACE_MOBILEFACENET_HEF_URL`,
`SCRFD_10G_HEF_URL`, and `ARCFACE_R50_HEF_URL`. If your Hailo package requires
authenticated manual download or local compilation, place the files manually at
the paths above.

## Step 3: Prepare the Database

The pipeline reads already-created embeddings from SQLite table `device_users`.
Enrollment is intentionally not implemented here.

Set the database path if needed:

```bash
export EDGE_HAILO_DB_PATH=/path/to/device_local.db
```

If unset, the code uses `edge/device_local.db` when it exists, otherwise
`edge_hailo/data/device_local.db`.

Supported basic schema:

```sql
device_users(user_id INTEGER PRIMARY KEY, face_vector BLOB, is_active INTEGER)
```

Richer multi-template layouts are also supported when `device_users` contains
multiple rows per user, a `template_name`/`pose` column, or JSON templates in an
embedding column. Template names such as `front`, `left_30`, `right_60`,
`slightly_up`, `slightly_down`, and `low_light` are returned when present.

## Step 4: Run the Pipeline

Access control on camera `/dev/video0`:

```bash
python3 -m edge_hailo.src.pipelines.access_control --camera /dev/video0
```

Access control with a local OpenCV preview window:

```bash
python3 -m edge_hailo.src.pipelines.access_control --camera /dev/video0 --display
```

Surveillance on camera `/dev/video1`:

```bash
python3 -m edge_hailo.src.pipelines.surveillance --camera /dev/video1
```

Surveillance with a local OpenCV preview window:

```bash
python3 -m edge_hailo.src.pipelines.surveillance --camera /dev/video1 --display
```

Camera sources can be `/dev/video0`, a numeric OpenCV index, RTSP URL, or video
file path.
If the old `edge/run_edge.py` works with `CAM_INDEX = 4`, use `--camera 4` here.
The display window mirrors the camera by default like the old edge kiosk; pass
`--no-mirror` to show the raw camera orientation. Press `q` in the OpenCV window
to exit cleanly.

Display mode requires a local GUI session. If running over SSH, Docker, or a
headless service, keep `--display` disabled or configure X11/Wayland forwarding
first. On the EdgeMind desktop session, `QT_QPA_PLATFORM=xcb` may be required
before launching the pipeline.

## Step 5: Tune Thresholds

Similarity thresholds are configurable:

```bash
export EDGE_HAILO_ACCESS_RECOGNITION_THRESHOLD=0.75
export EDGE_HAILO_SURVEILLANCE_RECOGNITION_THRESHOLD=0.62
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
uvicorn edge_hailo.src.api.main:app --host 0.0.0.0 --port 8080
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

The compose file exposes `/dev/hailo0`, `/dev/video0`, and `/dev/video1`, and
mounts `edge_hailo/models` plus `edge_hailo/data`.

The default Docker image is plain `python:3.11-slim`, so it does not include
`hailo_platform`. Use one of the two options below.

### Docker Option A: HailoRT Wheel

Copy the HailoRT Python wheel into the build context, then build and run:

```bash
mkdir -p edge_hailo/vendor
# Copy the HailoRT Python wheel into edge_hailo/vendor first.
export EDGE_HAILO_HAILORT_WHEEL=edge_hailo/vendor/hailort-<version>-cp311-<platform>.whl
docker compose -f edge_hailo/docker/docker-compose.face.yml up --build
```

The wheel must match the container Python version. The default image uses Python
3.11, so the wheel should be a `cp311` wheel.

### Docker Option B: HailoRT Base Image

If EdgeMind provides a container image that already includes HailoRT, use it as
the base image:

```bash
export EDGE_HAILO_BASE_IMAGE=<hailort-enabled-image>
docker compose -f edge_hailo/docker/docker-compose.face.yml up --build
```

### Docker Verification

The container runs this check before starting the API:

```bash
python -m edge_hailo.src.hailo.diagnostics
```

To run the same check manually after the container starts:

```bash
docker compose -f edge_hailo/docker/docker-compose.face.yml exec edge-hailo-face \
  python -m edge_hailo.src.hailo.diagnostics
```

For a local API-only smoke test without HailoRT, disable the startup guard:

```bash
EDGE_HAILO_REQUIRE_HAILORT=0 docker compose -f edge_hailo/docker/docker-compose.face.yml up --build
```

## Pipeline Behavior

Access control:

- Detector: `models/access_control/scrfd_2.5g.hef`
- Embedder: `models/access_control/arcface_mobilefacenet.hef`
- Uses liveness/spoofing heuristic adapted from the old edge kiosk
- Rejects frames with more than one face: `Only one user is allowed within the frame.`
- Denies unknown, low-confidence, inactive, or liveness-failed users

Surveillance:

- Detector: `models/surveillance/scrfd_10g.hef`
- Embedder: `models/surveillance/arcface_r50.hef`
- Supports multiple faces per frame
- Does not run spoofing/liveness checks
- Reports identities, scores, boxes, matched template names, and timestamps
