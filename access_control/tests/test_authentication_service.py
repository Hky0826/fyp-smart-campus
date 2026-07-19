import sys,time,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.access_control.controllers import MockAccessController
from app.authentication import AuthenticationPolicy,AuthenticationService,AuthenticationState as S
from app.domain import BoundingBox,Embedding,FaceDetection,FramePacket,IdentityMatch
class Quality:
    class Result:passed=True;status='Verifying identity';reasons=()
    def evaluate(self,frame,detection):return self.Result()
class Recognizer:
    def embed(self,frame,detection):return Embedding(np.array([1,0],np.float32),'opencv_sface','2021dec',2,frame.frame_id,frame.captured_at)
class Repository:
    def __init__(self):self.logs=[]
    def find_match(self,e,threshold):return IdentityMatch('7','Ada',.9,e)
    def log_authentication_event(self,*args,**kwargs):self.logs.append((args,kwargs))
def frame(i,age=0):return FramePacket(i,time.monotonic()-age,np.zeros((100,100,3),np.uint8))
def face(i):return FaceDetection(BoundingBox(20,20,50,50),np.array([[30,35],[60,35],[45,50],[32,65],[58,65]],np.float32),.95,i,time.monotonic())
class AuthenticationSecurityTests(unittest.TestCase):
    def service(self,available=True):
        controller=MockAccessController(available);return AuthenticationService(Recognizer(),Quality(),Repository(),controller,AuthenticationPolicy(consecutive_confirmations=2,max_result_age_seconds=.5,cooldown_seconds=10)),controller
    def test_tracker_only_never_unlocks(self):
        service,door=self.service();out=service.process_tracker_frame(frame(1),BoundingBox(1,1,20,20));self.assertEqual(out.state,S.TRACKING);self.assertFalse(out.access_verified);self.assertEqual(door.unlocks,[])
    def test_candidate_requires_new_detector_frame(self):
        service,door=self.service();first=service.process_detector_frame(frame(1),[face(1)]);self.assertTrue(first.force_detection);self.assertEqual(first.state,S.FRESH_DETECTION_REQUIRED);self.assertEqual(door.unlocks,[])
        repeated=service.process_detector_frame(frame(1),[face(1)]);self.assertEqual(repeated.reason,'stale_frame_id');self.assertEqual(door.unlocks,[])
        final=service.process_detector_frame(frame(2),[face(2)]);self.assertTrue(final.access_verified and final.physical_unlock_succeeded);self.assertEqual(len(door.unlocks),1)
    def test_stale_capture_and_multiple_faces_never_unlock(self):
        service,door=self.service();stale=service.process_detector_frame(frame(1,age=2),[face(1)]);self.assertEqual(stale.reason,'stale_capture')
        service,door=self.service();multiple=service.process_detector_frame(frame(1),[face(1),face(1)]);self.assertEqual(multiple.state,S.ACCESS_DENIED);self.assertEqual(door.unlocks,[])
    def test_hardware_failure_is_distinct_from_identity_verification(self):
        service,door=self.service(False);service.process_detector_frame(frame(1),[face(1)]);out=service.process_detector_frame(frame(2),[face(2)]);self.assertTrue(out.access_verified);self.assertFalse(out.physical_unlock_succeeded);self.assertEqual(out.state,S.ERROR)
    def test_unexpected_similarity_drop_requires_another_fresh_detection(self):
        class Scores(Repository):
            def __init__(self):super().__init__();self.values=iter((.9,.5))
            def find_match(self,e,threshold):return IdentityMatch('7','Ada',next(self.values),e)
        controller=MockAccessController(True)
        service=AuthenticationService(Recognizer(),Quality(),Scores(),controller,AuthenticationPolicy(max_similarity_drop=.2))
        service.process_detector_frame(frame(1),[face(1)])
        changed=service.process_detector_frame(frame(2),[face(2)])
        self.assertEqual(changed.reason,'recognition_confidence_changed')
        self.assertTrue(changed.force_detection)
        self.assertEqual(controller.unlocks,[])
    def test_cooldown_never_retains_granted_state_or_repeats_unlock(self):
        now=[time.monotonic()]
        controller=MockAccessController(True)
        service=AuthenticationService(Recognizer(),Quality(),Repository(),controller,AuthenticationPolicy(consecutive_confirmations=2,max_result_age_seconds=.5,cooldown_seconds=10),clock=lambda:now[0])
        def recent(i):return FramePacket(i,now[0],np.zeros((100,100,3),np.uint8))
        service.process_detector_frame(recent(1),[face(1)])
        granted=service.process_detector_frame(recent(2),[face(2)])
        self.assertEqual(granted.state,S.ACCESS_GRANTED)
        cooldown=service.process_detector_frame(recent(3),[face(3)])
        self.assertEqual(cooldown.state,S.COOLDOWN)
        self.assertEqual(cooldown.reason,'cooldown_active')
        self.assertEqual(len(controller.unlocks),1)
        now[0]+=11
        restarted=service.process_detector_frame(recent(4),[face(4)])
        self.assertEqual(restarted.state,S.FRESH_DETECTION_REQUIRED)
        self.assertEqual(len(controller.unlocks),1)
if __name__=='__main__':unittest.main()