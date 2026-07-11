# Recognition Pipeline Hardening

## Previous weaknesses

- Access decisions used one frame and one embedding, making transient blur, pose error, or detector jitter decisive.
- SCRFD input was stretched to 640 x 640 and decoded with independent X/Y scales.
- Invalid landmarks silently selected a resized bounding-box crop for ArcFace authorization.
- Quality was a Boolean minimum-size plus Laplacian-variance check.
- Motion liveness history had no enforced identity boundary between consecutive faces.
- Detector rows were only partially validated before recognition.
- Capture misses, inconclusive liveness, spoofing, and identity failure had no explicit state model.

## Module structure

- `src/hailo/preprocess.py`: letterboxing and detector-to-frame mapping.
- `src/hailo/postprocess_scrfd.py`: decoding, validation, clipping, expansion, sorting, and NMS.
- `src/face/tracking.py`: timestamp-aware IoU and landmark-continuity tracking.
- `src/face/quality.py`: normalized quality scores and mandatory failure reasons.
- `src/face/alignment.py`: strict five-point validation and affine alignment results.
- `src/face/aggregation.py`: bounded quality-ranked samples, outlier rejection, and candidate voting.
- `src/pipelines/access_control.py`: stable-track gate and explicit authentication state machine.

The Hailo runner, `.hef` files, ArcFace embedder, template matcher, and SQLite repository are unchanged.

## Tensor assumptions

These preserve the existing deployed HEFs and must be verified when a HEF is replaced:

| Model | Channels | Layout | Host dtype/range | Host normalization |
| --- | --- | --- | --- | --- |
| SCRFD | BGR camera converted to RGB | batched NHWC | `float32`, 0..255 | None; assumed compiled into HEF |
| ArcFace | aligned BGR converted to RGB | batched NHWC | `float32`, 0..255 | None; assumed compiled into HEF |

The runtime adapter owns quantization according to the HEF stream format. Do not add `/255`, mean subtraction, or `[-1, 1]` scaling without inspecting and validating a replacement HEF; that would double-normalize when normalization remains in the graph.

SCRFD coordinates are assumed normalized to, or expressed in, the 640 x 640 letterboxed detector input. NMS runs after mapping candidates into original-frame coordinates.

## Migration plan

1. Deploy with the existing HEFs and collect stage metrics without logging images or embeddings.
2. Validate coordinate mapping against every deployed camera resolution.
3. Calibrate detection, quality, pose, liveness, similarity, and outlier limits on held-out site data.
4. Run in shadow mode beside the current decision and compare false rejection/authorization cases.
5. Enable track-level decisions at one kiosk and monitor retry distribution and latency.
6. Roll out gradually using environment-driven configuration.

## Risk reduction

- Letterboxing reduces alignment errors caused by geometric distortion.
- Validation and NMS stop malformed, duplicate, or implausibly sized boxes early.
- Track boundaries prevent liveness or embedding evidence from crossing between people.
- Stable-track and multiple-face gates reduce face switching and mixed identities.
- Structured quality checks reject unstable inputs and rank the best frames.
- Strict landmarks prevent badly aligned crops from entering ArcFace authorization.
- Inlier aggregation suppresses transient noise; candidate voting prevents one-frame identity flips.
- Retry states avoid treating camera misses and warm-up as spoofing or identity failures.
