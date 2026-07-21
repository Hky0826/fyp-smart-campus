# Recognition Pipeline Hardening

## Module Structure

- `src/face/detection.py`: OpenCV YuNet face detection adapter (`YuNetDetector`).
- `src/face/embedding.py`: OpenCV SFace facial recognition adapter (`SFaceEmbedder`).
- `src/face/tracking.py`: Timestamp-aware IoU and landmark-continuity tracking.
- `src/face/quality.py`: Normalized quality scores and mandatory failure reasons.
- `src/face/alignment.py`: Strict five-point validation and affine alignment results.
- `src/face/aggregation.py`: Bounded quality-ranked samples, outlier rejection, and candidate voting.
- `src/pipelines/access_control.py`: Stable-track gate and explicit authentication state machine.

## Model Assumptions

| Model | Framework | Purpose | Input Size | Output |
| --- | --- | --- | --- | --- |
| YuNet | OpenCV ONNX | Face Detection & Landmarks | Dynamic (e.g. 640x640) | Bounding box + 5 facial landmarks |
| SFace | OpenCV ONNX | Facial Recognition | 112x112 aligned face | 128-dimensional normalized feature vector |
