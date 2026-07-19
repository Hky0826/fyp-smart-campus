"""Cloud JWT issuance after local fresh SFace identity verification."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from typing import Any
import requests
def _parse(value):
    if not value:return None
    parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'));return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
@dataclass(frozen=True,slots=True)
class EdgeAuthToken:
    access_token:str;session_id:int|None;user_id:int;username:str|None=None;roles:tuple[str,...]=();expires_at:datetime|None=None
    @classmethod
    def from_payload(cls,payload:dict[str,Any]):return cls(str(payload['access_token']),int(payload['session_id']) if payload.get('session_id') is not None else None,int(payload['user_id']),str(payload['username']) if payload.get('username') else None,tuple(map(str,payload.get('roles',[]))),_parse(payload.get('expires_at')))
    def is_fresh(self,margin_seconds=60):return self.expires_at is None or datetime.now(timezone.utc)+timedelta(seconds=margin_seconds)<self.expires_at
class EdgeAuthTokenClient:
    def __init__(self,cloud_url,device_id,http=None,timeout=8):self.endpoint=f"{cloud_url.rstrip('/')}/api/edge-auth/token";self.device_id=device_id;self.http=http or requests.Session();self.timeout=timeout
    def issue_token(self,user_id):
        response=self.http.post(self.endpoint,json={'user_id':int(user_id),'device_id':self.device_id},timeout=self.timeout)
        if response.status_code>=400:
            try:detail=response.json().get('detail')
            except Exception:detail=response.text
            raise RuntimeError(f'edge-auth token HTTP {response.status_code}: {detail or "no details"}')
        return EdgeAuthToken.from_payload(response.json())