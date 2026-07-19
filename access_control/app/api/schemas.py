"""Stable response contracts consumed by the preserved QML kiosk."""
from typing import Any,Literal
from pydantic import BaseModel,Field
class KioskTimingConfig(BaseModel):
    owner_missing_grace_seconds:int=10;owner_absent_lock_seconds:int=10;owner_absent_terminate_seconds:int=10;access_result_hold_seconds:int=4
class KioskDeviceStatus(BaseModel):
    edge_api:str='ok';cloud_sync:str='unknown';cloud_chatbot:str='unknown';sync_cloud_url:str;device_id:str;device_name:str
class ChatMessage(BaseModel):role:Literal['user','assistant','system'];content:str;created_at:str;citations:list[dict[str,Any]]=Field(default_factory=list)
class ChatSessionView(BaseModel):
    session_id:str;authenticated_user_id:int|None=None;username:str|None=None;full_name:str|None=None;roles:list[str]=Field(default_factory=list);cloud_session_id:int|None=None;owner_face_track_id:str|None=None;owner_absent_since:str|None=None;last_owner_seen_at:str|None=None;last_interaction_at:str;presence_state:Literal['OWNER_PRESENT','OWNER_TEMPORARILY_MISSING','OWNER_LEFT']='OWNER_PRESENT';expires_at:str|None=None;locked:bool=False;conversation_history:list[ChatMessage]=Field(default_factory=list)
class AccessAttemptView(BaseModel):
    attempt_id:str;detected_user_id:int|None=None;door_id:str;access_decision:Literal['VERIFYING','GRANTED','DENIED','ERROR']='VERIFYING';reason:str|None=None;similarity:float|None=None;face_count:int=0;bbox:list[int]|None=None;bboxes:list[list[int]]=Field(default_factory=list);created_at:str;completed_at:str|None=None;physical_unlock_succeeded:bool=False
class KioskStateResponse(BaseModel):device:KioskDeviceStatus;timings:KioskTimingConfig;active_chat_session:ChatSessionView|None=None;active_access_attempt:AccessAttemptView|None=None;chat_recoverable:bool=False
class ChatMessageRequest(BaseModel):query:str=Field(min_length=1,max_length=2000)
class AccessRequestResponse(BaseModel):attempt:AccessAttemptView
class ChatVerifyResponse(BaseModel):session:ChatSessionView;bboxes:list[list[int]]=Field(default_factory=list);reopened:bool=False
class ChatPresenceResponse(BaseModel):session:ChatSessionView|None=None;owner_present:bool;ended:bool=False;bboxes:list[list[int]]=Field(default_factory=list)
class ChatMessageResponse(BaseModel):session:ChatSessionView;answer:str;citations:list[dict[str,Any]]=Field(default_factory=list);access_granted:bool=False;status_message:str|None=None;response_time_ms:int|None=None;query_id:int|None=None;response_scope:str='DOCUMENT';personal_intent:str|None=None;navigation_target:dict[str,Any]|None=None
class ChatAudioResponse(BaseModel):session:ChatSessionView;transcribed_input:str|None=None;answer:str;audio_response:str|None=None;citations:list[dict[str,Any]]=Field(default_factory=list);access_granted:bool=False;status:str;status_message:str|None=None;response_time_ms:int|None=None;query_id:int|None=None;response_scope:str='DOCUMENT';personal_intent:str|None=None;navigation_target:dict[str,Any]|None=None
class DeactivateRequest(BaseModel):user_id:int