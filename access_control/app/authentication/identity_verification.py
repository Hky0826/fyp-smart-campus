"""Fresh YuNet/SFace identity operations that never control door hardware."""
from __future__ import annotations
from dataclasses import dataclass
from time import monotonic
from ..domain import Embedding
@dataclass(frozen=True,slots=True)
class VerificationPolicy:
    match_threshold:float=.363;confirmations:int=2;max_result_age_seconds:float=.5;max_faces:int=1
@dataclass(frozen=True,slots=True)
class IdentityVerificationResult:
    verified:bool;status:str;identity_id:str|None=None;display_name:str|None=None;similarity:float|None=None;embedding:Embedding|None=None;detections:tuple=();reason:str|None=None;needs_fresh_frame:bool=False
class IdentityVerificationService:
    def __init__(self,recognizer,quality,repository,policy=VerificationPolicy(),clock=monotonic):
        self.recognizer=recognizer;self.quality=quality;self.repository=repository;self.policy=policy;self.clock=clock;self._candidate=None;self._count=0;self._last_frame=-1
    def verify(self,frame,detections):
        invalid=self._validate_frame(frame,detections)
        if invalid:return invalid
        detection=detections[0];quality=self.quality.evaluate(frame,detection)
        if not quality.passed:self._reset();return self._result(False,quality.status,detections,reason=quality.reasons[0] if quality.reasons else 'quality_failed')
        embedding=self.recognizer.embed(frame,detection);match=self.repository.find_match(embedding,self.policy.match_threshold)
        if match is None:self._reset();return self._result(False,'Access denied',detections,embedding=embedding,reason='no_compatible_match')
        if self._candidate and self._candidate[0]==match.identity_id and frame.frame_id>self._candidate[1]:self._count+=1
        else:self._candidate=(match.identity_id,frame.frame_id);self._count=1
        if self._count<max(2,self.policy.confirmations):return self._result(False,'Fresh detection required',detections,match,embedding,'additional_confirmation_required',True)
        result=self._result(True,'Identity verified',detections,match,embedding);self._reset();return result
    def presence(self,frame,detections,reference):
        invalid=self._validate_frame(frame,detections,track_sequence=False)
        if invalid:return invalid
        detection=detections[0];quality=self.quality.evaluate(frame,detection)
        if not quality.passed:return self._result(False,quality.status,detections,reason='quality_failed')
        embedding=self.recognizer.embed(frame,detection)
        try:score=self.recognizer.similarity(embedding,reference)
        except Exception:return self._result(False,'Owner not present',detections,embedding=embedding,reason='incompatible_owner_embedding')
        return IdentityVerificationResult(score>=self.policy.match_threshold,'Owner present' if score>=self.policy.match_threshold else 'Owner not present',similarity=score,embedding=embedding,detections=tuple(detections),reason=None if score>=self.policy.match_threshold else 'owner_mismatch')
    def _validate_frame(self,frame,detections,track_sequence=True):
        if track_sequence and frame.frame_id<=self._last_frame:return self._result(False,'Stale result rejected',detections,reason='stale_frame_id')
        if track_sequence:self._last_frame=frame.frame_id
        if self.clock()-frame.captured_at>self.policy.max_result_age_seconds:return self._result(False,'Stale result rejected',detections,reason='stale_capture')
        if len(detections)==0:self._reset();return self._result(False,'No face detected',detections,reason='no_face')
        if len(detections)>self.policy.max_faces:self._reset();return self._result(False,'Multiple faces detected',detections,reason='multiple_faces')
        return None
    def _reset(self):self._candidate=None;self._count=0
    @staticmethod
    def _result(verified,status,detections,match=None,embedding=None,reason=None,needs=False):
        return IdentityVerificationResult(verified,status,getattr(match,'identity_id',None),getattr(match,'display_name',None),getattr(match,'similarity',None),embedding,tuple(detections),reason,needs)