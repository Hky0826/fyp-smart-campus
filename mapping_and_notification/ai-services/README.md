# AI Services — Developer Guide

> Campus Navigation System · AI Services · Phase 1.5.3

---

## Contents

1. [Project Overview](#project-overview)
2. [Supported Node Types](#supported-node-types)
3. [Semantic Mapping Configuration](#semantic-mapping-configuration)
4. [Pipeline Overview](#pipeline-overview)
5. [Running the Service](#running-the-service)
6. [Configuration Reference](#configuration-reference)
7. [Debug Image Generation](#debug-image-generation)
8. [Manual Testing Scripts](#manual-testing-scripts)
9. [Automated Tests](#automated-tests)
10. [Adding New Semantic Keywords](#adding-new-semantic-keywords)
11. [Project Structure](#project-structure)

---

## Project Overview

The AI Services component performs automatic floorplan analysis using a 10-stage OCR-first pipeline.
It accepts a floorplan image and returns a list of semantically typed room nodes in canvas coordinates
(800×600) that the frontend map editor can display and review.

---

## Supported Node Types

The following node types are supported by the navigation system.
**The AI classifier only generates these types** — it never produces unsupported values.

| Node Type      | Description                                         |
| -------------- | --------------------------------------------------- |
| `CLASSROOM`    | Lecture rooms, labs, seminar rooms, tutorials       |
| `CORRIDOR`     | Hallways, passages, walkways, concourses            |
| `ENTRANCE`     | Main entrances, lobbies, foyers, atria              |
| `STAIRWELL`    | Stairs, stairwells, staircases                      |
| `ELEVATOR`     | Lifts, elevators                                    |
| `FOOD`         | Kitchens, canteens, restaurants, cafeterias         |
| `OFFICE`       | Offices, administration, HR, reception, staff rooms |
| `FACILITIES`   | Storage, server rooms, electrical, utility, janitor |
| `HALL`         | Meeting rooms, boardrooms, conference, auditoriums  |
| `WASHROOM`     | Toilets, restrooms, WCs, bathrooms                  |
| `OUTDOOR`      | Car parks, gardens, courtyards, open spaces         |
| `SOCIAL SPACES`| Libraries, lounges, study areas, reading rooms      |
| `OTHER`        | Prayer rooms, clinics, medical, unclassified        |

---

## Semantic Mapping Configuration

Node type classification is driven by **keyword rules** defined in:

```
src/config/semantic_rules.yaml
```

### File Structure

```yaml
rules:
  - node_type: "CLASSROOM"
    keywords:
      - "lecture"
      - "lab"
      - ...

  - node_type: "FOOD"
    keywords:
      - "kitchen"
      - "canteen"
      - ...

default_node_type: "OTHER"
```

### How Classification Works

1. The OCR label is lowercased.
2. Rules are evaluated **top to bottom** — the **first match wins**.
3. If no keyword matches, `default_node_type` is used (default: `OTHER`).

### How It Is Loaded

`src/config/semantic_rules_loader.py` loads and validates the YAML once at startup using an `@lru_cache`.

- If a rule contains a **node type not supported by the navigation system**, it is **skipped with a warning**.
- If the YAML file is missing, the service falls back to a minimal built-in ruleset and logs an error.

### Adding New Keywords

Open `src/config/semantic_rules.yaml` and append keywords to the appropriate rule:

```yaml
  - node_type: "CLASSROOM"
    keywords:
      - "lecture"
      - "lab"
      - "your_new_keyword"   # ← add here
```

No Python code change or service restart is required if you're reloading for a new analysis — but if
the service is running, **restart it** to pick up the new YAML (the loader uses `@lru_cache`).

### Adding a New Node Type

1. Confirm the new type is supported by the frontend (`mapConstants.js` / database).
2. Add it to `SUPPORTED_NODE_TYPES` in `src/config/semantic_rules_loader.py`.
3. Add the new rule block to `semantic_rules.yaml`.
4. Restart the service.

---

## Pipeline Overview

```
Stage 1A  Image Preprocessing        (aspect-ratio resize, multi-view creation)
Stage 1B  Wall Detection             (luminance threshold + CCA)
Stage 1C  OCR Detection              (PaddleOCR text extraction)
Stage 1D  OCR Fragment Merging       (multi-line label clustering)
Stage 1E  OCR-First Node Generation  (one node per OCR label, bbox-constrained placement)
Stage 1F  Room Detection             (morphological polygon detection + gap-fill nodes)
Stage 1G  Semantic Deduplication     (label normalise → source priority → spatial cluster)
Stage 1H  Node Validation            (hard/soft checks + automatic wall relocation)
Stage 1I  Coordinate Transformation  (AI space → 800×600 canvas)
Stage 1J  Final AI Result            (FloorplanAnalysisResult JSON)
```

---

## Running the Service

```bash
# Install dependencies
pip install -r requirements.txt

# Start the development server
uvicorn src.main:app --reload --port 8000

# API docs
open http://localhost:8000/docs
```

---

## Configuration Reference

All configurable parameters are in `src/config_settings.py` and can be overridden
via environment variables or the `.env` file.

| Setting | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development` or `production` |
| `ENABLE_DEBUG_IMAGES` | `false` | **Master switch** for debug image generation. Must be `true` in `.env` before `debug_mode=true` from the API has any effect. |
| `DEFAULT_WALL_SENSITIVITY` | `120` | Wall detection threshold (0–255) |
| `DEFAULT_MAX_AI_WIDTH` | `1200` | Max AI analysis image width |
| `DEFAULT_MAX_AI_HEIGHT` | `900` | Max AI analysis image height |
| `DEFAULT_MIN_OCR_CONFIDENCE` | `0.60` | PaddleOCR confidence threshold |
| `DEFAULT_MIN_ROOM_AREA_PX` | `2000` | Min enclosed room area (px²) |
| `DEFAULT_WALL_CLEARANCE_PX` | `8` | Min wall clearance for node positions |
| `DEFAULT_DEDUP_THRESHOLD_PX` | `50.0` | Spatial dedup radius for same-label nodes |

**Example `.env` to enable debug images in development:**

```dotenv
APP_ENV=development
ENABLE_DEBUG_IMAGES=true
```

---

## Debug Image Generation

The AI pipeline can save annotated intermediate images to `debug_output/` for inspection.

### Requirements

1. Set `ENABLE_DEBUG_IMAGES=true` in `.env`.
2. Pass `debug_mode=true` in the API request.

Both conditions must be true. In production (`ENABLE_DEBUG_IMAGES=false`), debug images are **always suppressed** regardless of what the client sends.

### What Is Saved

When enabled, up to 14 images are saved per analysis to `debug_output/{prefix}/`:

| File | Stage | Content |
|---|---|---|
| `01_original.png` | 1A | Raw uploaded floorplan |
| `05b_wall_mask_dilated.png` | 1B | Dilated wall mask |
| `10_ocr_raw_detections.png` | 1C | PaddleOCR bounding boxes |
| `10b_ocr_merged.png` | 1D | Merged OCR fragments |
| `08_room_candidates.png` | 1F | CCA room candidates |
| `09_room_accepted.png` | 1F | Accepted room polygons |
| `12_nodes_final.png` | 1G | All generated nodes (colour-coded by source) |

### Developer CLI Tool

You can also annotate a floorplan manually using an existing analysis JSON:

```bash
# Annotate nodes and rooms
python -m src.utils.debug_images \
    --image floorplan.jpg \
    --analysis result.json \
    --output debug_output/my_test/

# Node overlay only
python -m src.utils.debug_images \
    --image floorplan.jpg \
    --analysis result.json \
    --overlays nodes

# Room overlay only
python -m src.utils.debug_images \
    --image floorplan.jpg \
    --analysis result.json \
    --overlays rooms

# Help
python -m src.utils.debug_images --help
```

---

## Manual Testing Scripts

Located in `tests/` — these are NOT pytest tests and will not run during `pytest`.
They are standalone developer tools for validating AI behaviour on real floorplans.

### `manual_test_floorplan.py`

Runs the full AI analysis pipeline on a local floorplan image and prints a detailed result summary.

```bash
# Basic usage
python tests/manual_test_floorplan.py --image path/to/floorplan.jpg

# Advanced usage with all parameters
python tests/manual_test_floorplan.py \
    --image path/to/floorplan.jpg \
    --sensitivity 110 \
    --min-room-area 1500 \
    --min-ocr-confidence 0.55 \
    --wall-clearance 10 \
    --max-ai-width 1400 \
    --max-ai-height 1050 \
    --debug \
    --output debug_output/manual_run/

# Help
python tests/manual_test_floorplan.py --help
```

**Output includes:**
- Processing time
- Rooms detected / labeled
- OCR texts detected and merged
- Complete node list with: label, type, source, confidence, position, and flag status

---

## Automated Tests

Run the full pytest suite with:

```bash
venv/Scripts/pytest tests/ -v   # Windows
venv/bin/pytest tests/ -v       # macOS / Linux
```

Tests are located in `tests/wall_detection/` and cover:
- Wall detection API endpoint (via FastAPI TestClient)
- Wall detection accuracy against synthetic and real floorplans
- Grid dimensions, binary values, performance thresholds

---

## Project Structure

```
ai-services/
│
├── requirements.txt              Production dependencies
├── requirements-dev.txt          Development/testing dependencies
├── .env.example                  Environment variable template
│
└── src/
    ├── main.py                   FastAPI app, CORS, server entry point
    ├── config_settings.py        Centralised settings (pydantic-settings)
    │
    ├── config/                   Configuration package
    │   ├── semantic_rules.yaml   Node type keyword mapping (edit to add types)
    │   └── semantic_rules_loader.py  YAML loader with validation + lru_cache
    │
    ├── api/
    │   └── v1/
    │       ├── floorplan_analyzer.py   POST /api/v1/analyze/floorplan
    │       └── wall_detection.py       POST /api/v1/wall-detection
    │
    ├── modules/
    │   ├── node_generation/
    │   │   ├── ocr_node_generator.py   Stage 1E: OCR-first node generation
    │   │   └── generator.py            Stage 1F: room-detection gap-fill nodes
    │   ├── ocr/
    │   │   ├── detector.py             Stage 1C: PaddleOCR text extraction
    │   │   └── ocr_merger.py           Stage 1D: multi-line fragment merging
    │   ├── room_detection/
    │   │   └── detector.py             Stage 1F: enclosed space detection
    │   ├── validation/
    │   │   └── node_validator.py       Stage 1H: hard/soft node checks
    │   └── wall_detection/
    │       └── detector.py             Stage 1B: wall mask extraction
    │
    ├── services/
    │   ├── floorplan_analyzer.py       10-stage pipeline orchestrator
    │   └── preprocessor.py            Stage 1A: image resize + multi-view
    │
    ├── shared/
    │   └── models/v1/domain.py         Pydantic models (AiNode, RoomPolygon, etc.)
    │
    └── utils/
        ├── coord_transform.py          Stage 1I: AI space → canvas coordinate mapping
        ├── debug_images.py             Debug overlay writer + CLI developer tool
        ├── grid_utils.py              Wall grid generation for A* pathfinding
        ├── image_loader.py             Image loading from bytes or URL
        └── logging_config.py          Structured JSON/console logging

tests/
    ├── conftest.py                    pytest fixtures (HTTP client, sample images)
    ├── manual_test_floorplan.py       ⟵ Developer CLI: run pipeline on real images
    └── wall_detection/
        ├── test_api.py                Automated API tests
        └── test_detector.py           Automated detector unit tests
```
