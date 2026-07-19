"""Run recorded images through the real standalone pipeline with a mock door."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path, help='Image files or directories containing JPG/PNG frames.')
    parser.add_argument('--fps', type=float, default=24.0, help='Playback rate; defaults to 24 FPS.')
    return parser.parse_args()


def image_paths(inputs):
    allowed = {'.jpg', '.jpeg', '.png', '.bmp'}
    found = []
    for item in inputs:
        if item.is_dir():
            found.extend(path for path in item.rglob('*') if path.suffix.lower() in allowed)
        elif item.suffix.lower() in allowed:
            found.append(item)
    return sorted(set(path.resolve() for path in found))


def main():
    args = arguments()
    paths = image_paths(args.inputs)
    if not paths:
        raise SystemExit('No readable JPG, PNG, or BMP frames were found.')
    os.environ['ACCESS_HARDWARE_MODE'] = 'mock'
    os.environ.setdefault('ACCESS_DEBUG_METRICS', 'true')
    from app.bootstrap import build_runtime

    runtime = build_runtime()
    delay = 1.0 / max(1.0, args.fps)
    try:
        for path in paths:
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None:
                print(f'skip unreadable frame: {path}')
                continue
            view = runtime.process_access(frame)
            outcome = view.outcome
            print(f'{path.name}: source={view.box_source} status={view.status} state={getattr(getattr(outcome, "state", None), "name", "pending")} forced={view.forced_reason or "-"}')
            time.sleep(delay)
        for _ in range(3):
            view = runtime.process_access(frame)
            time.sleep(delay)
        print(runtime.metrics.snapshot())
        print(f'mock unlocks: {len(runtime.access_controller.unlocks)}')
    finally:
        runtime.pipeline.stop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
