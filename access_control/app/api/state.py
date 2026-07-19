"""Thread-safe, short-lived kiosk presentation and chatbot ownership state."""
from __future__ import annotations
from datetime import datetime,timezone
from threading import RLock
from uuid import uuid4
import numpy as np
from .schemas import AccessAttemptView,ChatMessage,ChatSessionView,KioskDeviceStatus,KioskStateResponse,KioskTimingConfig
def now_dt():return datetime.now(timezone.utc)
def utcnow():return now_dt().isoformat()
class KioskStateStore:
    def __init__(self,device_id,device_name,cloud_url,timings=None):
        self.device_id=device_id;self.device_name=device_name;self.cloud_url=cloud_url;self.timings=timings or KioskTimingConfig();self._lock=RLock();self._attempt=None;self._chat=None;self._token=None;self._owner_embedding=None;self._owner_absent_at=None
    def state(self,cloud_sync='unknown',cloud_chatbot='unknown'):
        with self._lock:return KioskStateResponse(device=KioskDeviceStatus(cloud_sync=cloud_sync,cloud_chatbot=cloud_chatbot,sync_cloud_url=self.cloud_url,device_id=self.device_id,device_name=self.device_name),timings=self.timings,active_chat_session=self._safe_chat(),active_access_attempt=self._attempt,chat_recoverable=bool(self._chat and self._chat.locked))
    def start_access_attempt(self):
        with self._lock:self._attempt=AccessAttemptView(attempt_id=str(uuid4()),door_id=self.device_id,created_at=utcnow());return self._attempt.model_copy(deep=True)
    def update_access(self,view):
        now=utcnow();out=view.outcome
        with self._lock:
            attempt=self._attempt or AccessAttemptView(attempt_id=str(uuid4()),door_id=self.device_id,created_at=now);box=list(view.box.as_xyxy()) if view.box else None;attempt.bbox=box;attempt.bboxes=[box] if box else [];attempt.face_count=int(getattr(out,'face_count',1 if box else 0));attempt.reason=getattr(out,'reason',None);attempt.similarity=getattr(out,'similarity',None);identity=getattr(out,'identity_id',None);attempt.detected_user_id=int(identity) if identity is not None and str(identity).isdigit() else None;attempt.physical_unlock_succeeded=bool(getattr(out,'physical_unlock_succeeded',False));state=getattr(getattr(out,'state',None),'name','')
            if attempt.physical_unlock_succeeded:attempt.access_decision='GRANTED';attempt.completed_at=now
            elif state=='ERROR':attempt.access_decision='ERROR';attempt.completed_at=now
            elif state=='ACCESS_DENIED':attempt.access_decision='DENIED';attempt.completed_at=now
            else:attempt.access_decision='VERIFYING';attempt.completed_at=None
            self._attempt=attempt;return attempt.model_copy(deep=True)
    def start_chat(self,token=None,full_name=None,owner_embedding=None):
        now=utcnow();user_id=getattr(token,'user_id',None);username=getattr(token,'username',None);roles=list(getattr(token,'roles',()) or ());session_id=getattr(token,'session_id',None);expires=getattr(token,'expires_at',None)
        with self._lock:
            self._token=token;self._owner_embedding=owner_embedding;self._owner_absent_at=None;self._chat=ChatSessionView(session_id=str(uuid4()),authenticated_user_id=user_id,username=username,full_name=full_name,roles=roles,cloud_session_id=session_id,last_owner_seen_at=now,last_interaction_at=now,expires_at=expires.isoformat() if expires else None,conversation_history=[ChatMessage(role='assistant',content='Hi, how may I help you?',created_at=now)]);return self._safe_chat()
    def append_chat(self,query,answer,citations):
        now=utcnow()
        with self._lock:
            if self._chat is None:raise RuntimeError('No active chatbot session')
            if self._chat.locked:raise PermissionError('Chatbot session is locked')
            self._chat.conversation_history.extend([ChatMessage(role='user',content=query,created_at=now),ChatMessage(role='assistant',content=answer,created_at=now,citations=citations)]);self._chat.last_interaction_at=now;return self._safe_chat()
    def lock_chat(self):
        with self._lock:
            if self._chat:self._chat.locked=True;self._chat.presence_state='OWNER_TEMPORARILY_MISSING';self._chat.owner_absent_since=self._chat.owner_absent_since or utcnow();self._owner_absent_at=self._owner_absent_at or now_dt()
            return self._safe_chat()
    def update_owner_presence(self,present):
        with self._lock:
            if not self._chat:return None,True
            now=now_dt()
            if present:self._chat.locked=False;self._chat.presence_state='OWNER_PRESENT';self._chat.owner_absent_since=None;self._chat.last_owner_seen_at=now.isoformat();self._owner_absent_at=None;return self._safe_chat(),False
            self._owner_absent_at=self._owner_absent_at or now;self._chat.owner_absent_since=self._owner_absent_at.isoformat();elapsed=(now-self._owner_absent_at).total_seconds();self._chat.presence_state='OWNER_TEMPORARILY_MISSING'
            lock_after=self.timings.owner_missing_grace_seconds
            terminate_after=lock_after+self.timings.owner_absent_lock_seconds+self.timings.owner_absent_terminate_seconds
            if elapsed>=terminate_after:self._clear_chat();return None,True
            if elapsed>=lock_after:self._chat.locked=True
            return self._safe_chat(),False
    def reopen_chat(self):
        with self._lock:
            if not self._chat:return None
            self._chat.locked=False;self._chat.presence_state='OWNER_PRESENT';self._chat.owner_absent_since=None;self._chat.last_owner_seen_at=utcnow();self._owner_absent_at=None;return self._safe_chat()
    def end_chat(self):
        with self._lock:self._clear_chat()
    def _clear_chat(self):self._chat=None;self._token=None;self._owner_embedding=None;self._owner_absent_at=None
    def current_chat(self):
        with self._lock:return self._safe_chat()
    def current_token(self):
        with self._lock:return self._token
    def owner_embedding(self):
        with self._lock:return self._owner_embedding
    def _safe_chat(self):
        if self._chat is None:return None
        view=self._chat.model_copy(deep=True)
        if view.locked:view.username=None;view.full_name=None;view.roles=[];view.expires_at=None;view.conversation_history=[]
        return view