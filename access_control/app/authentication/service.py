"""Security orchestration: tracker display state can never produce an unlock."""
from __future__ import annotations
from dataclasses import dataclass
import logging
from time import monotonic
from typing import Any
from .state_machine import AuthenticationEvent as E,AuthenticationState as S,AuthenticationStateMachine
logger=logging.getLogger(__name__)
@dataclass(frozen=True,slots=True)
class AuthenticationPolicy:
    match_threshold:float=.363; consecutive_confirmations:int=2; max_result_age_seconds:float=.5; unlock_seconds:float=3; cooldown_seconds:float=10; max_faces:int=1; max_similarity_drop:float=.20
@dataclass(frozen=True,slots=True)
class AuthenticationOutcome:
    state:S; status:str; access_verified:bool=False; physical_unlock_succeeded:bool=False; identity_id:str|None=None; similarity:float|None=None; face_count:int=0; bbox:tuple[int,int,int,int]|None=None; force_detection:bool=False; reason:str|None=None
class AuthenticationService:
    def __init__(self,recognizer,quality_evaluator,repository,access_controller,policy=AuthenticationPolicy(),clock=monotonic):
        self.recognizer=recognizer;self.quality=quality_evaluator;self.repository=repository;self.access=access_controller;self.policy=policy;self.clock=clock;self.machine=AuthenticationStateMachine();self._candidate=None;self._confirmations=0;self._cooldown_until=0.0;self._last_frame_id=-1;self._reported_state=None
    def start(self):
        if self.machine.state is S.IDLE:self.machine.dispatch(E.START)
    def process_tracker_frame(self,frame,box=None):
        self.start()
        self.machine.dispatch(E.TRACKER_ONLY)
        return AuthenticationOutcome(self.machine.state,'Tracking',face_count=1 if box else 0,bbox=box.as_xyxy() if box else None,force_detection=self.machine.state in {S.CANDIDATE_MATCH,S.FRESH_DETECTION_REQUIRED,S.FINAL_VERIFY},reason='tracker_display_only')
    def process_detector_frame(self,frame,detections):
        self.start();now=self.clock();count=len(detections)
        if frame.frame_id<=self._last_frame_id:return self._out('Stale result rejected',count,reason='stale_frame_id',force=True)
        self._last_frame_id=frame.frame_id
        if self.machine.state in {S.ACCESS_GRANTED,S.ACCESS_DENIED}:self.machine.dispatch(E.DISPLAY_COMPLETE)
        if self.machine.state is S.COOLDOWN:
            if count==0:self.face_left()
            elif now<self._cooldown_until:return self._out('Authentication cooldown',count,reason='cooldown_active')
            else:self.machine.dispatch(E.COOLDOWN_COMPLETE);self._candidate=None;self._confirmations=0
        if now-frame.captured_at>self.policy.max_result_age_seconds:return self._out('Stale result rejected',count,reason='stale_capture',force=True)
        if count==0:
            self._candidate=None;self._confirmations=0;self.machine.dispatch(E.NO_FACE);return self._out('No face detected',0)
        if count>self.policy.max_faces:
            self._candidate=None;self._confirmations=0;self.machine.dispatch(E.MULTIPLE_FACES);self._log(None,'FAILED',None,count,'multiple_faces');return self._out('Multiple faces detected',count,reason='multiple_faces')
        detection=detections[0];self.machine.dispatch(E.FRESH_SINGLE_FACE)
        quality=self.quality.evaluate(frame,detection)
        if not quality.passed:
            self.machine.dispatch(E.QUALITY_FAILED);return self._out(quality.status,1,detection,force=True,reason=quality.reasons[0] if quality.reasons else 'quality_failed')
        if self.machine.state is S.QUALITY_CHECK:self.machine.dispatch(E.QUALITY_PASSED)
        try:embedding=self.recognizer.embed(frame,detection);match=self.repository.find_match(embedding,self.policy.match_threshold)
        except Exception as exc:
            self.machine.dispatch(E.FAILURE);self._log(None,'ERROR',None,1,'recognition_error');return self._out('Recognition error',1,detection,reason=str(exc))
        if match is None:
            self._candidate=None;self._confirmations=0
            if self.machine.state in {S.RECOGNIZING,S.FINAL_VERIFY}:self.machine.dispatch(E.NO_MATCH if self.machine.state is S.RECOGNIZING else E.FINAL_REJECT)
            self._log(None,'FAILED',None,1,'no_compatible_match');return self._out('Access denied',1,detection,reason='no_compatible_match')
        if self._candidate is None:
            self._candidate=(match.identity_id,frame.frame_id,match.similarity);self._confirmations=1
            if self.machine.state is S.RECOGNIZING:self.machine.dispatch(E.CANDIDATE_FOUND);self.machine.dispatch(E.REQUEST_FINAL_VERIFY)
            return self._out('Fresh detection required',1,detection,match,force=True,reason='candidate_requires_fresh_confirmation')
        candidate_id,candidate_frame,candidate_similarity=self._candidate
        confidence_changed=candidate_similarity-match.similarity>self.policy.max_similarity_drop
        if frame.frame_id<=candidate_frame or match.identity_id!=candidate_id or confidence_changed:
            self._candidate=(match.identity_id,frame.frame_id,match.similarity);self._confirmations=1
            return self._out('Fresh detection required',1,detection,match,force=True,reason='recognition_confidence_changed' if confidence_changed else 'candidate_changed')
        if self.machine.state is S.FRESH_DETECTION_REQUIRED:self.machine.dispatch(E.FRESH_SINGLE_FACE)
        self._confirmations+=1
        if self._confirmations<max(2,self.policy.consecutive_confirmations):return self._out('Verifying identity',1,detection,match,force=True,reason='additional_confirmation_required')
        if now<self._cooldown_until:
            self.machine.dispatch(E.FINAL_REJECT);return self._out('Authentication cooldown',1,detection,match,reason='cooldown_active')
        self.machine.dispatch(E.FINAL_FRESH_MATCH);physical=bool(self.access.unlock(match.identity_id,self.policy.unlock_seconds))
        if not physical:self.machine.dispatch(E.FAILURE);self._log(match.identity_id,'ERROR',match.similarity,1,'physical_unlock_failed');return self._out('Identity verified; door unavailable',1,detection,match,verified=True,reason='physical_unlock_failed')
        self._cooldown_until=now+self.policy.cooldown_seconds;self._log(match.identity_id,'SUCCESS',match.similarity,1,'fresh_sface_verified');return self._out('Access granted',1,detection,match,verified=True,physical=True)
    def display_complete(self):
        if self.machine.state in {S.ACCESS_GRANTED,S.ACCESS_DENIED}:self.machine.dispatch(E.DISPLAY_COMPLETE)
    def face_left(self):
        self._candidate=None;self._confirmations=0
        if self.machine.state is S.COOLDOWN:self.machine.dispatch(E.FACE_LEFT)
    def _log(self,user,status,score,count,reason):
        try:self.repository.log_authentication_event(user,status,score,face_count=count,reason=reason,spoofing_checked=False)
        except Exception:pass
    def _out(self,status,count,detection=None,match=None,verified=False,physical=False,force=False,reason=None):
        if self._reported_state is not self.machine.state:
            logger.info('authentication_state_change state=%s reason=%s',self.machine.state.name,reason or status);self._reported_state=self.machine.state
        if verified:logger.info('authentication_final verified=true physical_unlock=%s',physical)
        return AuthenticationOutcome(self.machine.state,status,verified,physical,getattr(match,'identity_id',None),getattr(match,'similarity',None),count,detection.box.as_xyxy() if detection else None,force,reason)