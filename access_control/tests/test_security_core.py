import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.authentication.state_machine import AuthenticationEvent as E,AuthenticationState as S,AuthenticationStateMachine
from app.detection.yunet import YuNetDetector
from app.domain import BoundingBox,Embedding
from app.recognition.sface import IncompatibleEmbeddingError,SFaceRecognizer
from app.tracking.validation import TrackerValidationConfig,validate_tracker_box
from app.processing.scheduler import DetectionScheduler
from app.access_control.controllers import MockAccessController
class SecurityCoreTests(unittest.TestCase):
    def test_yunet_rows_are_clipped_and_structured(self):
        row=np.array([[-5,-4,80,90,10,10,40,10,25,30,12,55,39,55,.91]],np.float32);faces=YuNetDetector.convert_rows(row,7,1.25,64,64,min_face_size=20);self.assertEqual(len(faces),1);self.assertEqual(faces[0].box.as_xyxy(),(0,0,64,64))
    def test_invalid_or_timed_out_tracker_forces_detection(self):
        r=validate_tracker_box(True,BoundingBox(240,100,80,80),BoundingBox(100,100,80,80),640,480,24,TrackerValidationConfig());self.assertFalse(r.valid);self.assertTrue({'position_jump','detector_confirmation_timeout'}<=set(r.reasons))
    def test_incompatible_models_are_never_compared(self):
        one=Embedding(np.array([1,0],np.float32),'opencv_sface','2021dec',2,1,1);old=Embedding(np.array([1,0],np.float32),'arcface','legacy',2,1,1)
        with self.assertRaises(IncompatibleEmbeddingError):SFaceRecognizer.similarity(one,old)
    def test_tracker_only_state_cannot_unlock(self):
        m=AuthenticationStateMachine();m.dispatch(E.START);m.dispatch(E.TRACKER_ONLY);self.assertEqual(m.state,S.TRACKING);self.assertFalse(m.may_unlock)
    def test_unlock_requires_fresh_final_detection(self):
        m=AuthenticationStateMachine()
        for e in (E.START,E.FRESH_SINGLE_FACE,E.QUALITY_PASSED,E.CANDIDATE_FOUND,E.REQUEST_FINAL_VERIFY):m.dispatch(e)
        self.assertEqual(m.state,S.FRESH_DETECTION_REQUIRED);self.assertFalse(m.may_unlock);m.dispatch(E.FRESH_SINGLE_FACE);self.assertEqual(m.state,S.FINAL_VERIFY);m.dispatch(E.FINAL_FRESH_MATCH);self.assertTrue(m.may_unlock)
    def test_multiple_faces_denied(self):
        m=AuthenticationStateMachine();m.dispatch(E.START);m.dispatch(E.MULTIPLE_FACES);self.assertEqual(m.state,S.ACCESS_DENIED)
    def test_scheduler_runs_six_fps_and_forces_final_verification(self):
        s=DetectionScheduler(4,24);s.confirmed(0);self.assertEqual([s.decide(i).run_detector for i in range(1,5)],[False,False,False,True]);d=s.decide(5,authentication_pending=True);self.assertTrue(d.run_detector and d.forced)
    def test_mock_controller_unavailable(self):
        c=MockAccessController(False);self.assertFalse(c.unlock('1',3));self.assertEqual(c.unlocks,[])
if __name__=='__main__':unittest.main()