# Detector and Recognizer Replacement Guide

## Scope

This guide covers only the biometric pipeline in `access control/`:

- replacing `YuNetDetector` with another face detector;
- replacing `SFaceRecognizer` with another face recognizer;
- locating where both models are constructed and called;
- preserving frame safety, quality checks, authentication, presence verification, and KCF's display-only role.

Cloud synchronization, persistence, and cloud-side template conversion are intentionally outside this guide.

## Pipeline overview

```text
camera/API image
  -> AppRuntime.packet() creates FramePacket
  -> RealTimeAccessPipeline schedules biometric work
  -> BiometricWorker calls detector.detect(frame)
  -> detector returns FaceDetection objects
  -> access or identity-verification service
  -> FaceQualityEvaluator
  -> recognizer.embed(frame, detection)
  -> match or presence-comparison result
```

KCF is not recognition evidence. It only supplies display boxes between detector frames. Replacing either model must preserve the rule that recognition and unlock decisions use fresh detector output, never a KCF-only box.

## Shared pipeline contracts

The shared types are in `app/domain.py`.

### `FramePacket`

Every detector and recognizer receives:

- `frame_id`: monotonically increasing integer;
- `captured_at`: monotonic capture timestamp;
- `image`: BGR NumPy image;
- `metadata`: optional metadata.

Backends must preserve the source frame ID. Authentication uses frame IDs and timestamps to reject stale or repeated evidence.

### `FaceDetection`

A detector must return `list[FaceDetection]`. Each result contains:

- `box`: `BoundingBox` in original-frame coordinates;
- `landmarks`: finite NumPy array with shape `(5, 2)`;
- `confidence`: detector confidence;
- `frame_id`: copied from the input frame;
- `detected_at`: detector/capture timestamp;
- `inference_ms`: measured latency when available.

The current SFace adapter expects five landmarks in this order:

1. right eye;
2. left eye;
3. nose tip;
4. right mouth corner;
5. left mouth corner.

If another detector uses a different order, convert it inside the detector adapter before returning `FaceDetection`.

The detector must return every valid face. It must not silently select only the highest-confidence face because the pipeline needs the full count to enforce multiple-face rejection.

### `Embedding`

A recognizer returns `Embedding` with:

- a one-dimensional NumPy vector;
- stable `model_name`;
- stable `model_version`;
- exact `dimension`;
- source `frame_id`;
- creation timestamp.

Normalize the vector if the chosen similarity method expects normalized features. Metadata must accurately distinguish incompatible embedding spaces.

## Interfaces

The protocols are defined in `app/interfaces.py`.

### Detector

```python
class FaceDetector(Protocol):
    def detect(self, frame: FramePacket) -> list[FaceDetection]: ...
    def set_input_size(self, width: int, height: int) -> None: ...
```

Current backend: `app/detection/yunet.py::YuNetDetector`.

A replacement detector should:

- load its model once in the constructor;
- process `frame.image`;
- convert outputs to original-frame coordinates;
- clip boxes and landmarks;
- reject invalid, non-finite, or undersized detections;
- retain the input frame ID;
- return all valid faces;
- support resolution changes through `set_input_size()`;
- expose `last_inference_ms` if timing should appear in `/metrics`.

### Recognizer

```python
class FaceRecognizer(Protocol):
    def embed(self, frame: FramePacket, detection: FaceDetection) -> Embedding: ...
    def similarity(self, probe: Embedding, reference: Embedding) -> float: ...
```

Current backend: `app/recognition/sface.py::SFaceRecognizer`.

A replacement recognizer should:

- load its model once in the constructor;
- align or crop from the detector-confirmed `FaceDetection`;
- return a valid one-dimensional embedding;
- attach correct model metadata and source frame ID;
- reject invalid or zero-length features;
- implement the score used by the configured threshold;
- reject incompatible embeddings;
- expose `last_inference_ms` if timing should appear in `/metrics`.

## Where models are constructed

The composition root is `app/bootstrap.py::build_runtime()`.

Current construction:

```python
detector = YuNetDetector(...)
recognizer = SFaceRecognizer(...)
```

The one recognizer instance is shared by both services:

```python
auth = AuthenticationService(recognizer, ...)
verifier = IdentityVerificationService(recognizer, ...)
```

The detector and services are passed to the one worker:

```python
worker = BiometricWorker(detector, auth, verifier)
```

This is the main wiring location to change. Keep one detector and one recognizer instance per runtime. Never construct models inside a per-frame method.

The concrete imports are also in `app/bootstrap.py`:

```python
from .detection import YuNetDetector
from .recognition import SFaceRecognizer
```

Package exports are located in:

- `app/detection/__init__.py`;
- `app/recognition/__init__.py`.

## Where the detector is called

There is one production detector invocation:

- file: `app/services/biometric_worker.py`;
- method: `BiometricWorker._execute()`.

```python
detections = self.detector.detect(frame)
```

Every biometric mode passes through this same call:

| Mode | Next consumer |
|---|---|
| `access` | `AuthenticationService.process_detector_frame()` |
| `identity` | `IdentityVerificationService.verify()` |
| `presence` | `IdentityVerificationService.presence()` |

The worker serializes these operations. Do not add detector calls to the UI, tracker, API endpoints, or authentication services.

## Where the recognizer is called

### Access authentication

File: `app/authentication/service.py`

Method: `AuthenticationService.process_detector_frame()`

Sequence:

1. reject stale frames;
2. reject zero or multiple faces;
3. run the quality gate;
4. call `self.recognizer.embed(frame, detection)`;
5. obtain the configured identity match;
6. require further fresh detector confirmation before unlock.

The recognizer is never called from `process_tracker_frame()`.

### Chatbot-owner identity verification

File: `app/authentication/identity_verification.py`

Method: `IdentityVerificationService.verify()`

After frame, face-count, and quality checks:

```python
embedding = self.recognizer.embed(frame, detection)
```

This mode requires distinct fresh frames according to its verification policy.

### Chatbot-owner presence verification

File: `app/authentication/identity_verification.py`

Method: `IdentityVerificationService.presence()`

It calls both recognizer methods:

```python
embedding = self.recognizer.embed(frame, detection)
score = self.recognizer.similarity(embedding, reference)
```

A replacement recognizer must therefore support direct probe-to-reference comparison, not only extraction.

## Replacing only the detector

1. Add a backend under `app/detection/`, such as `new_detector.py`.
2. Implement the `FaceDetector` protocol.
3. Convert backend output to `FaceDetection`.
4. Convert landmarks to the order required by the active recognizer.
5. Clip coordinates to the original frame.
6. Export the class from `app/detection/__init__.py` if desired.
7. Add model paths and backend thresholds to `AppConfig` and `.env.example`.
8. Replace the detector import and construction in `build_runtime()`.
9. Leave `BiometricWorker`, authentication services, scheduler, KCF, API, and UI unchanged.
10. Run detector conversion, multiple-face, tracker, stale-frame, and fresh-unlock tests.

## Replacing only the recognizer

1. Add a backend under `app/recognition/`, such as `new_recognizer.py`.
2. Implement `embed()` and `similarity()`.
3. Decide whether alignment belongs inside the recognizer or a recognizer-owned helper.
4. Ensure the detector provides the landmarks required by that alignment.
5. Return accurate model metadata, dimension, and frame ID.
6. Export the class from `app/recognition/__init__.py` if desired.
7. Add model path, similarity metric, and threshold settings to `AppConfig` and `.env.example`.
8. Replace the recognizer import and construction in `build_runtime()`.
9. Inject the same instance into `AuthenticationService` and `IdentityVerificationService`.
10. Validate access, identity, presence, stale-frame rejection, and final fresh confirmation.

## Replacing both together

Define the boundary between the new detector and recognizer first:

| Boundary | Decision |
|---|---|
| Image format | BGR/RGB, tensor layout, and normalization |
| Coordinates | Original-frame output and box convention |
| Landmarks | Count, order, coordinate system, and alignment owner |
| Face crop | Box crop versus landmark alignment |
| Embedding | Shape, normalization, name, version, and dimension |
| Similarity | Cosine, distance, or model-specific score direction |
| Threshold | Meaning and calibrated value |
| Multiple faces | Return every valid face |
| Timing | Preserve frame ID and report measured latency |

Recommended order:

1. implement and test detector conversion;
2. implement and test recognizer alignment and embedding;
3. test detector landmarks with recognizer alignment on the same frame;
4. wire both objects in `build_runtime()`;
5. test all four worker modes;
6. test fresh-confirmation and no-unlock invariants;
7. inspect detector, recognizer, and total latency through `/metrics`;
8. tune thresholds and scheduling only after correctness is established.

## Files normally changed

| File | Purpose |
|---|---|
| `app/detection/<backend>.py` | Detector adapter |
| `app/detection/__init__.py` | Detector export |
| `app/recognition/<backend>.py` | Recognizer adapter |
| `app/recognition/__init__.py` | Recognizer export |
| `app/config/settings.py` | Paths and thresholds |
| `.env.example` | Configuration documentation |
| `app/bootstrap.py` | Backend construction and injection |
| `models/<backend>/` | Local model and metadata |
| `tests/` | Backend and pipeline tests |

These files should normally remain backend-agnostic:

- `app/services/biometric_worker.py`;
- `app/processing/pipeline.py`;
- `app/processing/scheduler.py`;
- `app/tracking/kcf.py`;
- `app/tracking/validation.py`;
- `app/authentication/state_machine.py`;
- API endpoints and QML UI.

If a replacement requires edits throughout those modules, backend details are probably leaking past the adapter.

## Existing tests to use as references

- `tests/test_security_core.py`: detector conversion, clipping, incompatible embeddings, tracking safety, and fresh verification.
- `tests/test_authentication_service.py`: state transitions, stale evidence, confidence changes, cooldown, and unlock rules.
- `tests/test_realtime_pipeline.py`: detector-authoritative boxes, tracker failures, and multiple-face behavior.
- `tests/test_biometric_worker.py`: all device biometric modes use one serialized detector path.
- `tests/test_runtime_safety.py`: model-file errors, KCF availability, quality rejection, and configuration.

At minimum, prove:

- one model load per runtime;
- correct detector output for valid, empty, invalid, and multiple-face frames;
- correct landmark order and alignment;
- deterministic embedding shape and metadata;
- expected same-person and different-person scores;
- no recognizer call on tracker-only frames;
- no unlock from stale evidence, cached identity, or a KCF box;
- fresh detector and recognizer confirmation before unlock;
- working access, identity, and presence modes.

## Common mistakes

- Returning resized-model coordinates rather than original-frame coordinates.
- Returning landmarks in the wrong order.
- Hiding additional faces by returning only one detection.
- Running recognition directly on KCF boxes.
- Constructing models for every frame.
- Losing the source frame ID.
- Applying an old result to a newer frame.
- Reusing a threshold calibrated for another model.
- Treating lower-is-better distance as higher-is-better similarity.
- Supporting access mode but forgetting presence verification.
- Putting backend-specific logic in the UI or tracker.

## Final checklist

- [ ] Detector implements `detect()` and `set_input_size()`.
- [ ] Detector returns every valid face as `FaceDetection`.
- [ ] Boxes and landmarks use original-frame coordinates.
- [ ] Landmark order matches the recognizer's alignment contract.
- [ ] Recognizer implements `embed()` and `similarity()`.
- [ ] Embeddings contain correct metadata and frame ID.
- [ ] Models are constructed once in `build_runtime()`.
- [ ] One recognizer instance is shared by both services.
- [ ] `BiometricWorker._execute()` remains the detector call site.
- [ ] Access, identity, and presence modes work.
- [ ] Quality validation happens before embedding extraction.
- [ ] Tracker-only frames cannot recognize or unlock.
- [ ] Multiple faces prevent authentication by default.
- [ ] Fresh detector and recognizer confirmation remains mandatory.
- [ ] Backend settings and local model files are documented.
- [ ] Security and pipeline tests pass.
- [ ] Actual latency is checked through `/metrics`.
