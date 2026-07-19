"""24 FPS display / 6 FPS detection scheduling with security overrides."""
from dataclasses import dataclass
@dataclass(frozen=True,slots=True)
class DetectionDecision:
    run_detector:bool; forced:bool; reason:str
class DetectionScheduler:
    def __init__(self,interval_frames=4,max_tracker_age=24):
        if interval_frames<1 or max_tracker_age<1: raise ValueError('frame intervals must be positive')
        self.interval_frames=interval_frames; self.max_tracker_age=max_tracker_age; self.last_confirmed_frame=None; self.force_reason=None
    def confirmed(self,frame_id): self.last_confirmed_frame=frame_id; self.force_reason=None
    def force(self,reason): self.force_reason=reason or 'security_override'
    def decide(self,frame_id,tracker_valid=True,authentication_pending=False,stream_restarted=False):
        reason=self.force_reason
        if stream_restarted: reason='camera_restarted'
        elif authentication_pending: reason='authentication_final_verify'
        elif not tracker_valid: reason='tracker_invalid'
        elif self.last_confirmed_frame is None: reason='no_detector_confirmation'
        elif frame_id-self.last_confirmed_frame>=self.max_tracker_age: reason='detector_confirmation_timeout'
        if reason: self.force_reason=None; return DetectionDecision(True,True,reason)
        return DetectionDecision(frame_id%self.interval_frames==0,False,'scheduled' if frame_id%self.interval_frames==0 else 'tracker_frame')