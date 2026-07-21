"""Environment-driven safe defaults for Raspberry Pi 5 and portable hosts."""
from __future__ import annotations
import os
from dataclasses import dataclass,field
from pathlib import Path
from ..env import load_dotenv
load_dotenv()
ROOT=Path(__file__).resolve().parents[2]
def env(name,default,cast):
    value=os.getenv(name);return default if value is None else cast(value)
def boolean(name,default=False):return env(name,default,lambda v:v.strip().lower() in {'1','true','yes','on'})
def module_path(name,default):
    value=Path(os.getenv(name,str(default))).expanduser();return value if value.is_absolute() else ROOT/value
def detection_interval():
    return env('ACCESS_DETECTOR_INTERVAL',1,int)
@dataclass(frozen=True,slots=True)
class AppConfig:
    camera:str=field(default_factory=lambda:os.getenv('ACCESS_CAMERA','0'))
    width:int=field(default_factory=lambda:env('ACCESS_CAMERA_WIDTH',640,int));height:int=field(default_factory=lambda:env('ACCESS_CAMERA_HEIGHT',480,int))
    display_fps:int=field(default_factory=lambda:env('ACCESS_DISPLAY_FPS',30,int));yunet_fps:int=field(default_factory=lambda:env('ACCESS_YUNET_FPS',30,int));detector_interval:int=field(default_factory=detection_interval)
    max_tracker_age:int=field(default_factory=lambda:env('ACCESS_TRACKER_MAX_AGE_FRAMES',24,int));tracker_area_change:float=field(default_factory=lambda:env('ACCESS_KCF_MAX_AREA_CHANGE',.6,float));tracker_width_change:float=field(default_factory=lambda:env('ACCESS_KCF_MAX_WIDTH_CHANGE',.45,float));tracker_height_change:float=field(default_factory=lambda:env('ACCESS_KCF_MAX_HEIGHT_CHANGE',.45,float));tracker_aspect_change:float=field(default_factory=lambda:env('ACCESS_KCF_MAX_ASPECT_CHANGE',.35,float));tracker_position_change:float=field(default_factory=lambda:env('ACCESS_KCF_MAX_POSITION_CHANGE',.5,float))
    max_faces:int=field(default_factory=lambda:env('ACCESS_MAX_FACES',1,int));yunet_confidence:float=field(default_factory=lambda:env('ACCESS_YUNET_CONFIDENCE',.7,float));yunet_nms:float=field(default_factory=lambda:env('ACCESS_YUNET_NMS',.3,float));min_face_size:int=field(default_factory=lambda:env('ACCESS_MIN_FACE_SIZE',48,int))
    quality_min_sharpness:float=field(default_factory=lambda:env('ACCESS_QUALITY_MIN_SHARPNESS',35,float));quality_min_brightness:float=field(default_factory=lambda:env('ACCESS_QUALITY_MIN_BRIGHTNESS',45,float));quality_max_brightness:float=field(default_factory=lambda:env('ACCESS_QUALITY_MAX_BRIGHTNESS',215,float))
    quality_min_area_ratio:float=field(default_factory=lambda:env('ACCESS_QUALITY_MIN_AREA_RATIO',.015,float));quality_center_tolerance:float=field(default_factory=lambda:env('ACCESS_QUALITY_CENTER_TOLERANCE',.4,float));quality_boundary_margin:int=field(default_factory=lambda:env('ACCESS_QUALITY_BOUNDARY_MARGIN',2,int));quality_max_eye_tilt:float=field(default_factory=lambda:env('ACCESS_QUALITY_MAX_EYE_TILT_DEGREES',18,float));quality_max_nose_offset:float=field(default_factory=lambda:env('ACCESS_QUALITY_MAX_NOSE_OFFSET_RATIO',.65,float))
    sface_threshold:float=field(default_factory=lambda:env('ACCESS_SFACE_THRESHOLD',.363,float));confirmations:int=field(default_factory=lambda:env('ACCESS_CONFIRMATIONS',2,int));max_result_age_seconds:float=field(default_factory=lambda:env('ACCESS_MAX_RESULT_AGE_SECONDS',.5,float));max_similarity_drop:float=field(default_factory=lambda:env('ACCESS_MAX_SIMILARITY_DROP',.20,float))
    unlock_seconds:float=field(default_factory=lambda:env('ACCESS_UNLOCK_SECONDS',3,float));cooldown_seconds:float=field(default_factory=lambda:env('ACCESS_COOLDOWN_SECONDS',10,float));granted_display_seconds:float=field(default_factory=lambda:env('ACCESS_GRANTED_DISPLAY_SECONDS',4,float));camera_restart_gap_seconds:float=field(default_factory=lambda:env('ACCESS_CAMERA_RESTART_GAP_SECONDS',1.0,float));owner_missing_grace_seconds:int=field(default_factory=lambda:env('ACCESS_OWNER_MISSING_GRACE_SECONDS',10,int));owner_lock_seconds:int=field(default_factory=lambda:env('ACCESS_OWNER_LOCK_SECONDS',10,int));owner_terminate_seconds:int=field(default_factory=lambda:env('ACCESS_OWNER_TERMINATE_SECONDS',10,int))
    database_path:Path=field(default_factory=lambda:module_path('ACCESS_DB_PATH',ROOT/'data'/'device_local.db'))
    cloud_url:str=field(default_factory=lambda:os.getenv('ACCESS_CLOUD_URL','http://127.0.0.1:8000'));device_id:str=field(default_factory=lambda:os.getenv('ACCESS_DEVICE_ID','entry-gate-01'));device_name:str=field(default_factory=lambda:os.getenv('ACCESS_DEVICE_NAME','Entry Gate Kiosk'));local_ip:str=field(default_factory=lambda:os.getenv('ACCESS_LOCAL_IP','127.0.0.1'));api_host:str=field(default_factory=lambda:os.getenv('ACCESS_API_HOST','0.0.0.0'));api_port:int=field(default_factory=lambda:env('ACCESS_API_PORT',8080,int));sync_receiver_port:int=field(default_factory=lambda:env('ACCESS_SYNC_RECEIVER_PORT',8080,int));sync_interval:int=field(default_factory=lambda:env('ACCESS_SYNC_INTERVAL_SECONDS',30,int));offline_retry_max:int=field(default_factory=lambda:env('ACCESS_OFFLINE_RETRY_MAX_SECONDS',300,int))
    hardware_mode:str=field(default_factory=lambda:os.getenv('ACCESS_HARDWARE_MODE','mock').lower());gpio_pin:int=field(default_factory=lambda:env('ACCESS_GPIO_PIN',17,int));gpio_active_high:bool=field(default_factory=lambda:boolean('ACCESS_GPIO_ACTIVE_HIGH',True))
    log_level:str=field(default_factory=lambda:os.getenv('ACCESS_LOG_LEVEL','INFO'));debug_metrics:bool=field(default_factory=lambda:boolean('ACCESS_DEBUG_METRICS',False))
    yunet_model:Path=field(default_factory=lambda:module_path('ACCESS_YUNET_MODEL',ROOT/'models'/'yunet'/'face_detection_yunet_2023mar_int8bq.onnx'));sface_model:Path=field(default_factory=lambda:module_path('ACCESS_SFACE_MODEL',ROOT/'models'/'sface'/'face_recognition_sface_2021dec.onnx'))
