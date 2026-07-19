"""Explicit state machine enforcing fresh biometric evidence before unlock."""
from dataclasses import dataclass
from enum import Enum,auto
class AuthenticationState(Enum):
    IDLE=auto(); SEARCHING=auto(); TRACKING=auto(); QUALITY_CHECK=auto(); RECOGNIZING=auto(); CANDIDATE_MATCH=auto(); FRESH_DETECTION_REQUIRED=auto(); FINAL_VERIFY=auto(); ACCESS_GRANTED=auto(); ACCESS_DENIED=auto(); COOLDOWN=auto(); ERROR=auto()
class AuthenticationEvent(Enum):
    START=auto(); NO_FACE=auto(); TRACKER_ONLY=auto(); FRESH_SINGLE_FACE=auto(); MULTIPLE_FACES=auto(); QUALITY_PASSED=auto(); QUALITY_FAILED=auto(); CANDIDATE_FOUND=auto(); NO_MATCH=auto(); REQUEST_FINAL_VERIFY=auto(); FINAL_FRESH_MATCH=auto(); FINAL_REJECT=auto(); DISPLAY_COMPLETE=auto(); COOLDOWN_COMPLETE=auto(); FACE_LEFT=auto(); FAILURE=auto()
@dataclass(frozen=True,slots=True)
class Transition: previous:AuthenticationState; current:AuthenticationState; event:AuthenticationEvent
class AuthenticationStateMachine:
    def __init__(self): self.state=AuthenticationState.IDLE
    def dispatch(self,event):
        p=self.state; S=AuthenticationState; E=AuthenticationEvent
        if event is E.FAILURE: self.state=S.ERROR
        elif event is E.MULTIPLE_FACES: self.state=S.ACCESS_DENIED
        elif self.state is S.IDLE and event is E.START: self.state=S.SEARCHING
        elif self.state in {S.SEARCHING,S.TRACKING}:
            if event is E.TRACKER_ONLY: self.state=S.TRACKING
            elif event is E.FRESH_SINGLE_FACE: self.state=S.QUALITY_CHECK
            elif event is E.NO_FACE: self.state=S.SEARCHING
        elif self.state is S.QUALITY_CHECK:
            if event is E.QUALITY_PASSED: self.state=S.RECOGNIZING
            elif event is E.QUALITY_FAILED: self.state=S.SEARCHING
        elif self.state is S.RECOGNIZING:
            if event is E.CANDIDATE_FOUND: self.state=S.CANDIDATE_MATCH
            elif event is E.NO_MATCH: self.state=S.ACCESS_DENIED
        elif self.state is S.CANDIDATE_MATCH and event is E.REQUEST_FINAL_VERIFY: self.state=S.FRESH_DETECTION_REQUIRED
        elif self.state is S.FRESH_DETECTION_REQUIRED and event is E.FRESH_SINGLE_FACE: self.state=S.FINAL_VERIFY
        elif self.state is S.FINAL_VERIFY:
            if event is E.FINAL_FRESH_MATCH: self.state=S.ACCESS_GRANTED
            elif event is E.FINAL_REJECT: self.state=S.ACCESS_DENIED
        elif self.state in {S.ACCESS_GRANTED,S.ACCESS_DENIED} and event is E.DISPLAY_COMPLETE: self.state=S.COOLDOWN
        elif self.state is S.COOLDOWN and event in {E.COOLDOWN_COMPLETE,E.FACE_LEFT}: self.state=S.SEARCHING
        return Transition(p,self.state,event)
    @property
    def may_unlock(self): return self.state is AuthenticationState.ACCESS_GRANTED