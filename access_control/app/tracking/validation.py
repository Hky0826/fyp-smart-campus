"""Dedicated validation for untrusted KCF localization output."""
from dataclasses import dataclass
from math import hypot, isfinite
from ..domain import BoundingBox
@dataclass(frozen=True, slots=True)
class TrackerValidationConfig:
    max_area_change_ratio: float=.6; max_width_change_ratio: float=.45; max_height_change_ratio: float=.45
    max_aspect_change_ratio: float=.35; max_center_displacement_ratio: float=.5; max_age_frames: int=24
@dataclass(frozen=True, slots=True)
class TrackerValidationResult:
    valid: bool; force_detection: bool; reasons: tuple[str,...]=()
def _change(a,b): return abs(a-b)/max(abs(b),1e-6)
def validate_tracker_box(success,current,previous,frame_width,frame_height,frames_since_detection,config):
    reasons=[]
    if not success: reasons.append('kcf_update_failed')
    if current is None: reasons.append('missing_box')
    else:
        if not all(isfinite(v) for v in (current.x,current.y,current.width,current.height)): reasons.append('non_finite_box')
        if current.width<=0 or current.height<=0: reasons.append('invalid_dimensions')
        if current.x<0 or current.y<0 or current.x2>frame_width or current.y2>frame_height: reasons.append('box_outside_frame')
        if _change(current.area,previous.area)>config.max_area_change_ratio: reasons.append('area_jump')
        if _change(current.width,previous.width)>config.max_width_change_ratio: reasons.append('width_jump')
        if _change(current.height,previous.height)>config.max_height_change_ratio: reasons.append('height_jump')
        if _change(current.aspect_ratio,previous.aspect_ratio)>config.max_aspect_change_ratio: reasons.append('aspect_ratio_jump')
        displacement=hypot(current.center[0]-previous.center[0],current.center[1]-previous.center[1])
        if displacement/max(previous.width,previous.height,1)>config.max_center_displacement_ratio: reasons.append('position_jump')
    if frames_since_detection>=config.max_age_frames: reasons.append('detector_confirmation_timeout')
    return TrackerValidationResult(not reasons,bool(reasons),tuple(dict.fromkeys(reasons)))