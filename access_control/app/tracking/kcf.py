"""KCF localization backend. Its output is never authentication evidence."""
import cv2

from ..domain import BoundingBox


class KCFTracker:
    @staticmethod
    def available():
        return hasattr(cv2, 'TrackerKCF_create') or (hasattr(cv2, 'legacy') and hasattr(cv2.legacy, 'TrackerKCF_create'))

    def __init__(self):
        if not self.available():
            raise RuntimeError('KCF requires opencv-contrib-python-headless; remove conflicting OpenCV wheels')
        self._tracker = None

    @staticmethod
    def _create():
        if hasattr(cv2, 'TrackerKCF_create'):
            return cv2.TrackerKCF_create()
        if hasattr(cv2, 'legacy') and hasattr(cv2.legacy, 'TrackerKCF_create'):
            return cv2.legacy.TrackerKCF_create()
        raise RuntimeError('KCF requires an OpenCV contrib build')

    def initialize(self, frame, box):
        self._tracker = self._create()
        result = self._tracker.init(frame.image, box.as_xywh())
        return True if result is None else bool(result)

    def update(self, frame):
        if self._tracker is None:
            return False, None
        ok, raw = self._tracker.update(frame.image)
        return bool(ok), BoundingBox(*map(float, raw)) if ok else None

    def reset(self):
        self._tracker = None
