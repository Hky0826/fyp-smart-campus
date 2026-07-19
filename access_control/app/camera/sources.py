"""OpenCV and mock camera sources with monotonic frame identity."""
from __future__ import annotations
import cv2
import logging
from ..domain import FramePacket
logger=logging.getLogger(__name__)
class CameraUnavailableError(RuntimeError):pass
class OpenCVCameraSource:
    def __init__(self,source=0,width=640,height=480):self.source=int(source) if str(source).isdigit() else source;self.width=width;self.height=height;self._capture=None;self._frame_id=0
    def start(self):
        self._capture=cv2.VideoCapture(self.source)
        if not self._capture.isOpened():self._capture.release();self._capture=None;logger.error('camera_initialization_failed source=%s',self.source);raise CameraUnavailableError(f'camera unavailable: {self.source}')
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH,self.width);self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT,self.height);self._capture.set(cv2.CAP_PROP_BUFFERSIZE,1)
    def read(self):
        if self._capture is None:return None
        ok,image=self._capture.read()
        if not ok:logger.warning('camera_frame_capture_failed source=%s',self.source);return None
        self._frame_id+=1;return FramePacket.create(self._frame_id,image)
    def stop(self):
        if self._capture is not None:self._capture.release();self._capture=None
class MockCameraSource:
    def __init__(self,frames):self.frames=iter(frames);self._id=0
    def start(self):pass
    def read(self):
        try:image=next(self.frames)
        except StopIteration:return None
        self._id+=1;return FramePacket.create(self._id,image.copy())
    def stop(self):pass