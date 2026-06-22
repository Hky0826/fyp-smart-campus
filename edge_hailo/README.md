# Edge Hailo Face Recognition

Independent Hailo-based face-recognition pipelines for the EdgeMind device.
This package does not import from the existing `edge` folder at runtime.

## Pipelines

Access control:

- Detector: `models/access_control/scrfd_2.5g.hef`
- Embedder: `models/access_control/arcface_mobilefacenet.hef`
- Uses liveness/spoofing heuristic adapted from the old edge kiosk
- Rejects frames with more than one face:
  `Only one user is allowed within the frame.`
- Denies unknown, low-confidence, inactive, or liveness-failed users

Surveillance:

- Detector: `models/surveillance/scrfd_10g.hef`
- Embedder: `models/surveillance/arcface_r50.hef`
- Supports multiple faces per frame
- Does not run spoofing/liveness checks
- Reports identities, scores, boxes, matched template names, and timestamps

## Models

Expected placement:

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

Run:

```bash
bash edge_hailo/download_models.sh
```

The script can copy HEFs from `HAILO_HEF_SOURCE_DIR` or download from URLs you
provide in `SCRFD_25G_HEF_URL`, `ARCFACE_MOBILEFACENET_HEF_URL`,
`SCRFD_10G_HEF_URL`, and `ARCFACE_R50_HEF_URL`. If your Hailo package requires
authenticated manual download or local compilation, place the files manually at
the paths above.

## Database

The pipeline reads already-created embeddings from SQLite table `device_users`.
Enrollment is intentionally not implemented here.

The existing edge schema is supported:

```sql
device_users(user_id INTEGER PRIMARY KEY, face_vector BLOB, is_active INTEGER)
```

Richer multi-template layouts are also supported when `device_users` contains
multiple rows per user, a `template_name`/`pose` column, or JSON templates in an
embedding column. Template names such as `front`, `left_30`, `right_60`,
`slightly_up`, `slightly_down`, and `low_light` are returned when present.

Set a database path with:

```bash
export EDGE_HAILO_DB_PATH=/path/to/device_local.db
```

If unset, the code uses `edge/device_local.db` when it exists.

## Run

Install Python dependencies and HailoRT on the EdgeMind device:

```bash
pip install -r edge_hailo/requirements.txt
```

Then verify that the same Python interpreter can import the HailoRT bindings:

```bash
python -m edge_hailo.src.hailo.diagnostics
```

If this reports `hailo_platform_importable: false`, HailoRT is not installed in
the Python environment used to start the pipeline. Install the HailoRT runtime
and Python bindings from the EdgeMind/Hailo software package for that exact
Python version, then run the diagnostic again. The package name is not listed in
`requirements.txt` because HailoRT is device/OS/Python-version specific and is
usually distributed with the Hailo/EdgeMind SDK rather than as a normal PyPI
dependency.

Access control:

```bash
python -m edge_hailo.src.pipelines.access_control --camera /dev/video0
```

Surveillance:

```bash
python -m edge_hailo.src.pipelines.surveillance --camera /dev/video1
```

Camera sources can be `/dev/video0`, a numeric OpenCV index, RTSP URL, or video
file path.

## API

Run:

```bash
uvicorn edge_hailo.src.api.main:app --host 0.0.0.0 --port 8080
```

Endpoints:

- `GET /health`
- `POST /access-control/frame`
- `POST /surveillance/frame`
- `GET /models/status`
- `GET /database/status`

Frame endpoints accept multipart upload field `file`. Access control also
accepts optional form field `target_user_id` for strict 1:1 verification.

## Docker

```bash
docker compose -f edge_hailo/docker/docker-compose.face.yml up --build
```

The compose file exposes `/dev/hailo0`, `/dev/video0`, and `/dev/video1`, and
mounts `edge_hailo/models` plus `edge_hailo/data`.

The default Docker image is plain `python:3.11-slim`, so it does not include
`hailo_platform`. Use a HailoRT-enabled base image, or place the HailoRT Python
wheel inside the build context and pass it through `EDGE_HAILO_HAILORT_WHEEL`:

```bash
mkdir -p edge_hailo/vendor
# Copy the HailoRT Python wheel into edge_hailo/vendor first.
export EDGE_HAILO_HAILORT_WHEEL=edge_hailo/vendor/hailort-<version>-cp311-<platform>.whl
docker compose -f edge_hailo/docker/docker-compose.face.yml up --build
```

If EdgeMind provides a container image that already includes HailoRT, use it as
the base image instead:

```bash
export EDGE_HAILO_BASE_IMAGE=<hailort-enabled-image>
docker compose -f edge_hailo/docker/docker-compose.face.yml up --build
```

The container runs `python -m edge_hailo.src.hailo.diagnostics` before starting
the API and exits early if `hailo_platform` is missing. To run the same check
manually:

```bash
docker compose -f edge_hailo/docker/docker-compose.face.yml exec edge-hailo-face \
  python -m edge_hailo.src.hailo.diagnostics
```

For a local API-only smoke test without HailoRT, disable the startup guard:

```bash
EDGE_HAILO_REQUIRE_HAILORT=0 docker compose -f edge_hailo/docker/docker-compose.face.yml up --build
```

## Thresholds

Similarity thresholds are configurable:

```bash
export EDGE_HAILO_ACCESS_RECOGNITION_THRESHOLD=0.75
export EDGE_HAILO_SURVEILLANCE_RECOGNITION_THRESHOLD=0.62
```

These values must be tuned using real camera footage from the target device.
Access control should remain strict. Surveillance can use a separate threshold
to improve recall for angled, non-frontal, up/down, and low-light views while
still returning `unknown` below threshold.
