"""Cloud RAG client; all network work is invoked from background workers."""
from __future__ import annotations
from typing import Any
import requests
class ChatbotClientError(RuntimeError):
    def __init__(self,message,status_code=None):super().__init__(message);self.status_code=status_code
class ChatbotClient:
    def __init__(self,base_url,http=None,connect_timeout=5,read_timeout=90):
        self.base_url=base_url.rstrip('/');self.http=http or requests.Session();self.timeout=(connect_timeout,read_timeout)
    def health_check(self):return self._request('GET','/api/chatbot/health')
    def chat(self,query,jwt_token=None,device_id=None,session_id=None):
        headers={'Content-Type':'application/json'}
        if jwt_token:headers['Authorization']=f'Bearer {jwt_token}'
        body={'query':query}
        if device_id:body['device_id']=device_id
        if session_id is not None:body['session_id']=session_id
        return self._request('POST','/api/chatbot/chat',json=body,headers=headers)
    def audio_chat(self,audio_bytes,mime_type='audio/wav',jwt_token=None,device_id=None,session_id=None):
        if not audio_bytes:raise ChatbotClientError('Audio recording is empty.',400)
        headers={'Accept':'application/json'}
        if jwt_token:headers['Authorization']=f'Bearer {jwt_token}'
        data={}
        if device_id:data['device_id']=device_id
        if session_id is not None:data['session_id']=session_id
        return self._request('POST','/api/chatbot/chat/audio',files={'audio':('recording.wav',audio_bytes,mime_type)},data=data,headers=headers)
    def _request(self,method,path,**kwargs):
        try:response=self.http.request(method,f'{self.base_url}{path}',timeout=self.timeout,**kwargs)
        except requests.Timeout as exc:raise ChatbotClientError('Cloud chatbot request timed out.') from exc
        except requests.ConnectionError as exc:raise ChatbotClientError('Cannot connect to cloud chatbot service.') from exc
        except requests.RequestException as exc:raise ChatbotClientError(f'Cloud chatbot request failed: {exc}') from exc
        if response.status_code>=400:
            try:detail=response.json().get('detail')
            except Exception:detail=None
            messages={401:'Authentication expired; verify your face again.',403:'Chatbot access denied.',503:'Cloud chatbot unavailable.'}
            raise ChatbotClientError(str(detail or messages.get(response.status_code,f'Cloud chatbot HTTP {response.status_code}')),response.status_code)
        try:return response.json()
        except ValueError as exc:raise ChatbotClientError('Cloud chatbot returned invalid JSON.',response.status_code) from exc