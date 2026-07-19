"""Standalone FastAPI surface consumed by the native QML kiosk."""
from __future__ import annotations
import asyncio,logging
from contextlib import asynccontextmanager
from pathlib import Path
import cv2
import numpy as np
from fastapi import FastAPI,File,HTTPException,UploadFile
from fastapi.responses import StreamingResponse
logger=logging.getLogger(__name__)
from .schemas import AccessRequestResponse,ChatAudioResponse,ChatMessageRequest,ChatMessageResponse,ChatPresenceResponse,ChatVerifyResponse,DeactivateRequest

def _boxes(detections):return [list(d.box.as_xyxy()) for d in detections]
async def _decode(file,max_bytes=10*1024*1024):
    data=await file.read(max_bytes+1)
    if not data:raise HTTPException(400,'Uploaded frame is empty.')
    if len(data)>max_bytes:raise HTTPException(413,'Uploaded frame is too large.')
    image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
    if image is None:raise HTTPException(400,'Uploaded file is not a valid image.')
    return image

def create_app(runtime):
    @asynccontextmanager
    async def lifespan(_app):
        runtime.start()
        try:yield
        finally:runtime.stop()
    app=FastAPI(title='Standalone YuNet/SFace Access Control',version='1.0.0',lifespan=lifespan)
    @app.get('/health')
    def health():return {'status':'ok','pipeline':'yunet-kcf-sface','sync':runtime.sync.status()}
    @app.get('/models/status')
    def models_status():
        rows=[]
        for name,path in [('yunet',runtime.config.yunet_model),('sface',runtime.config.sface_model)]:rows.append({'name':name,'path':str(path),'exists':Path(path).is_file(),'size_bytes':Path(path).stat().st_size if Path(path).is_file() else 0})
        return {'models':rows}
    @app.get('/database/status')
    def database_status():return runtime.repository.status()
    @app.get('/sync/status')
    def sync_status():return {'status':runtime.sync.status(),'last_error':runtime.sync.last_error}
    @app.get('/metrics')
    def metrics():return runtime.metrics.snapshot()
    @app.get('/kiosk/state')
    def kiosk_state():return runtime.kiosk.state(runtime.sync.status(),'unknown')
    @app.get('/kiosk/events')
    async def kiosk_events():
        async def stream():
            while True:
                state=runtime.kiosk.state(runtime.sync.status(),'unknown');yield f'event: state\ndata: {state.model_dump_json()}\n\n';await asyncio.sleep(2)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    @app.post('/kiosk/access/request',response_model=AccessRequestResponse)
    def request_access():return AccessRequestResponse(attempt=runtime.kiosk.start_access_attempt())
    @app.post('/kiosk/access/frame',response_model=AccessRequestResponse)
    async def access_frame(file:UploadFile=File(...)):
        image=await _decode(file);view=await asyncio.to_thread(runtime.process_access,image);return AccessRequestResponse(attempt=runtime.kiosk.update_access(view))
    @app.post('/kiosk/chat/verify/frame',response_model=ChatVerifyResponse)
    async def chat_verify(file:UploadFile=File(...)):
        image=await _decode(file);result=await asyncio.to_thread(runtime.biometric_command,image,'identity');verification=result.outcome
        if not verification.verified:raise HTTPException(401,verification.status)
        token=None
        try:token=await asyncio.to_thread(runtime.token_client.issue_token,verification.identity_id)
        except Exception as exc:logger.warning('edge_auth_token_failure error=%s',type(exc).__name__)
        session=runtime.kiosk.start_chat(token=token,full_name=verification.display_name,owner_embedding=verification.embedding);return ChatVerifyResponse(session=session,bboxes=_boxes(result.detections))
    async def presence_result(file,allow_reopen=False):
        reference=runtime.kiosk.owner_embedding()
        if reference is None:return ChatPresenceResponse(owner_present=False,ended=True)
        image=await _decode(file);result=await asyncio.to_thread(runtime.biometric_command,image,'presence',reference);present=bool(result.outcome.verified)
        if allow_reopen and present:session=runtime.kiosk.reopen_chat();ended=False
        else:session,ended=runtime.kiosk.update_owner_presence(present)
        return ChatPresenceResponse(session=session,owner_present=present,ended=ended,bboxes=_boxes(result.detections))
    @app.post('/kiosk/chat/presence/frame',response_model=ChatPresenceResponse)
    async def chat_presence(file:UploadFile=File(...)):return await presence_result(file)
    @app.post('/kiosk/chat/reopen/frame',response_model=ChatPresenceResponse)
    async def chat_reopen(file:UploadFile=File(...)):return await presence_result(file,True)
    def require_chat():
        session=runtime.kiosk.current_chat()
        if session is None:raise HTTPException(409,'Face verification is required before chatbot use.')
        if session.locked:raise HTTPException(423,'Chatbot session is locked; verify owner presence to reopen.')
        return session
    @app.post('/kiosk/chat/message',response_model=ChatMessageResponse)
    async def chat_message(body:ChatMessageRequest):
        require_chat()
        token=runtime.kiosk.current_token()
        try:response=await asyncio.to_thread(runtime.chatbot.chat,body.query,getattr(token,'access_token',None),runtime.config.device_id,getattr(token,'session_id',None))
        except Exception as exc:logger.warning('chatbot_cloud_failure operation=text status=%s',getattr(exc,'status_code',None));raise HTTPException(getattr(exc,'status_code',None) or 502,str(exc))
        citations=response.get('citations',[]);session=runtime.kiosk.append_chat(body.query,str(response.get('answer') or ''),citations)
        return ChatMessageResponse(session=session,answer=str(response.get('answer') or ''),citations=citations,access_granted=bool(response.get('access_granted')),status_message=response.get('status_message'),response_time_ms=response.get('response_time_ms'),query_id=response.get('query_id'),response_scope=response.get('response_scope','DOCUMENT'),personal_intent=response.get('personal_intent'),navigation_target=response.get('navigation_target'))
    @app.post('/kiosk/chat/audio',response_model=ChatAudioResponse)
    async def chat_audio(audio:UploadFile=File(...)):
        require_chat()
        if audio.content_type and not audio.content_type.startswith('audio/'):raise HTTPException(400,'Expected an audio file.')
        data=await audio.read();token=runtime.kiosk.current_token()
        try:response=await asyncio.to_thread(runtime.chatbot.audio_chat,data,audio.content_type or 'audio/wav',getattr(token,'access_token',None),runtime.config.device_id,getattr(token,'session_id',None))
        except Exception as exc:logger.warning('chatbot_cloud_failure operation=audio status=%s',getattr(exc,'status_code',None));raise HTTPException(getattr(exc,'status_code',None) or 502,str(exc))
        query=str(response.get('transcribed_input') or '[Audio input]');answer=str(response.get('text_response') or response.get('error_message') or '');citations=response.get('sources',[]);session=runtime.kiosk.append_chat(query,answer,citations)
        return ChatAudioResponse(session=session,transcribed_input=response.get('transcribed_input'),answer=answer,audio_response=response.get('audio_response'),citations=citations,access_granted=bool(response.get('access_granted')),status=str(response.get('status') or 'error'),status_message=response.get('error_message'),response_time_ms=response.get('response_time_ms'),query_id=response.get('query_id'),response_scope=response.get('response_scope','DOCUMENT'),personal_intent=response.get('personal_intent'),navigation_target=response.get('navigation_target'))
    @app.post('/kiosk/chat/lock',response_model=ChatVerifyResponse)
    def chat_lock():
        session=runtime.kiosk.lock_chat()
        if session is None:raise HTTPException(404,'No active chatbot session.')
        return ChatVerifyResponse(session=session)
    @app.post('/kiosk/chat/end')
    def chat_end():runtime.kiosk.end_chat();return {'success':True}
    @app.post('/kiosk/chat/audio/stop')
    def chat_audio_stop():return {'success':True}
    @app.post('/api/edge/deactivate')
    def deactivate(body:DeactivateRequest):return {'status':'deactivated' if runtime.sync.deactivate_user(body.user_id) else 'not_found'}
    @app.post('/api/edge/trigger-sync')
    async def trigger_sync():return {'status':'completed' if await asyncio.to_thread(runtime.sync.trigger_immediate_sync) else 'failed'}
    return app