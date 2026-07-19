import sys,time,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.domain import BoundingBox,FaceDetection,FramePacket
from app.processing import DetectionScheduler,RealTimeAccessPipeline
from app.services import BiometricResult
from app.tracking.validation import TrackerValidationConfig
class Outcome:
    def __init__(self,status='Verifying identity',force=False):self.status=status;self.force_detection=force
class Worker:
    def __init__(self):self.result=None;self.submitted=[];self.dropped_frames=0
    def start(self):pass
    def stop(self):pass
    def poll(self):r=self.result;self.result=None;return r
    def submit(self,frame):self.submitted.append(frame.frame_id)
class Tracker:
    def __init__(self):self.fail=False;self.box=None;self.resets=0
    def initialize(self,frame,box):self.box=box;return True
    def update(self,frame):return (False,None) if self.fail else (True,self.box)
    def reset(self):self.resets+=1;self.box=None

def packet(i):return FramePacket.create(i,np.zeros((100,100,3),np.uint8))
def detection(i):return FaceDetection(BoundingBox(20,20,40,40),np.zeros((5,2),np.float32),.9,i,time.monotonic())
class PipelineTests(unittest.TestCase):
    def setUp(self):self.worker=Worker();self.tracker=Tracker();self.pipeline=RealTimeAccessPipeline(self.worker,self.tracker,DetectionScheduler(4,24),TrackerValidationConfig(max_age_frames=24))
    def tearDown(self):self.pipeline.stop()
    def test_yunet_box_is_authoritative_for_result_display_frame(self):
        first=packet(1);self.pipeline.process(first);self.worker.result=BiometricResult(first,[detection(1)],Outcome())
        view=self.pipeline.process(packet(2));self.assertEqual(view.box_source,'detector');self.assertEqual(view.box.as_xyxy(),(20,20,60,60))
        next_view=self.pipeline.process(packet(3));self.assertEqual(next_view.box_source,'tracker')
    def test_kcf_failure_clears_stale_box_and_forces_yunet(self):
        first=packet(1);self.worker.result=BiometricResult(first,[detection(1)],Outcome());self.pipeline.process(packet(2));self.tracker.fail=True
        view=self.pipeline.process(packet(3));self.assertIsNone(view.box);self.assertTrue(view.detector_submitted and view.forced_detection)
    def test_multiple_faces_clear_tracker_and_surface_status(self):
        first=packet(1);self.worker.result=BiometricResult(first,[detection(1),detection(1)],Outcome('Multiple faces detected'));view=self.pipeline.process(packet(2));self.assertIsNone(view.box);self.assertEqual(view.status,'Multiple faces detected');self.assertTrue(view.detector_submitted)
if __name__=='__main__':unittest.main()