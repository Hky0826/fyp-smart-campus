from pydantic import BaseModel, ConfigDict, Field, EmailStr
from typing import Optional, List, Any
import datetime
from enum import Enum

# ==========================================
# Common Config
# ==========================================
class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

# ==========================================
# Enums
# ==========================================
class EnrollmentStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    GRADUATED = "GRADUATED"
    SUSPENDED = "SUSPENDED"

class StaffTypeEnum(str, Enum):
    ADMINISTRATIVE = "ADMINISTRATIVE"
    TECHNICAL = "TECHNICAL"
    SECURITY = "SECURITY"
    FACILITIES = "FACILITIES"
    OTHER = "OTHER"

class AdminTypeEnum(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    CONTENT_ADMIN = "CONTENT_ADMIN"

class AccessLevelEnum(str, Enum):
    PUBLIC = "PUBLIC"
    STUDENT = "STUDENT"
    LECTURER = "LECTURER"
    ADMIN = "ADMIN"

class DeviceTypeEnum(str, Enum):
    KIOSK = "KIOSK"
    ENTRY_GATE = "ENTRY_GATE"
    CLASSROOM = "CLASSROOM"
    OFFICE = "OFFICE"
    OTHER = "OTHER"

class CourseLevelEnum(str, Enum):
    UNDERGRADUATE = "UNDERGRADUATE"
    POSTGRADUATE = "POSTGRADUATE"

class EnrollmentStatusAcademicEnum(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class DayOfWeekEnum(str, Enum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"

class AppointmentStatusEnum(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"

class AuthStatusEnum(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class ClearanceStatusEnum(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"

# ==========================================
# Auth Schemas
# ==========================================
class LoginRequest(BaseModel):
    email: str
    password: str

class Token(BaseSchema):
    access_token: Optional[str] = None
    token_type: str
    admin_type: str
    email: str
    full_name: str
    admin_id: str
    must_change_password: bool = False

# ==========================================
# Structural Reference Schemas
# ==========================================
class BuildingBase(BaseSchema):
    building_name: str

class BuildingCreate(BuildingBase):
    pass

class BuildingResponse(BuildingBase):
    building_id: int

class FloorplanBase(BaseSchema):
    building_id: int
    floor_level: int
    image_path: Optional[str] = None
    scale_ratio: Optional[float] = None

class FloorplanCreate(FloorplanBase):
    pass

class FloorplanResponse(FloorplanBase):
    floorplan_id: int

class NodeBase(BaseSchema):
    floorplan_id: int
    coord_x: float
    coord_y: float
    room_label: Optional[str] = None
    is_accessible: ClearanceStatusEnum = ClearanceStatusEnum.ALLOW
    node_type: str

class NodeCreate(NodeBase):
    pass

class NodeResponse(NodeBase):
    node_id: int

class EdgeBase(BaseSchema):
    source_node_id: int
    destination_node_id: int
    weight_distance: float
    is_accessible: ClearanceStatusEnum = ClearanceStatusEnum.ALLOW
    is_bidirectional: bool = True
    custom_path: Optional[str] = None

class EdgeCreate(EdgeBase):
    pass

class EdgeResponse(EdgeBase):
    edge_id: int

# ==========================================
# Category 1: IAM Schemas
# ==========================================
class RoleBase(BaseSchema):
    role_name: str
    description: Optional[str] = None

class RoleCreate(RoleBase):
    pass

class RoleResponse(RoleBase):
    role_id: int
    created_at: datetime.datetime

class UserImageResponse(BaseSchema):
    image_id: int
    user_id: int
    template_name: str
    image_path: str
    created_at: datetime.datetime

class UserFaceEmbeddingResponse(BaseSchema):
    embedding_id: int
    user_id: int
    template_name: str
    model_name: str
    created_at: datetime.datetime

class UserBase(BaseSchema):
    given_name: str
    family_name: str
    email: EmailStr
    is_active: bool = True
    last_known_location: Optional[int] = None

class UserCreate(UserBase):
    role_ids: Optional[List[int]] = None
    role_id: Optional[int] = None

class UserUpdate(BaseSchema):
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role_ids: Optional[List[int]] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = None
    last_known_location: Optional[int] = None

class StudentBase(BaseSchema):
    student_id: Optional[str] = None
    program: Optional[str] = None
    faculty: Optional[str] = None
    programme_id: Optional[str] = None
    faculty_id: Optional[str] = None
    intake: int
    enrollment_status: EnrollmentStatusEnum = EnrollmentStatusEnum.ACTIVE
    enrolled_since: datetime.date

class LecturerBase(BaseSchema):
    lecturer_id: Optional[str] = None
    department: Optional[str] = None
    faculty: Optional[str] = None
    department_id: Optional[str] = None
    faculty_id: Optional[str] = None
    position: str
    is_head_of_department: bool = False
    office_node_id: Optional[int] = None

class StaffBase(BaseSchema):
    staff_id: Optional[str] = None
    department: Optional[str] = None
    department_id: Optional[str] = None
    position: str
    staff_type: StaffTypeEnum
    office_node_id: Optional[int] = None

class VisitorBase(BaseSchema):
    visitor_id: Optional[str] = None
    id_number: str
    organization: Optional[str] = None
    visit_purpose: Optional[str] = None
    access_expiry: datetime.datetime
    access_start: Optional[datetime.datetime] = None
    registered_by: int

class AdminBase(BaseSchema):
    admin_id: Optional[str] = None
    admin_type: AdminTypeEnum
    department: Optional[str] = None
    department_id: Optional[str] = None
    office_node_id: Optional[int] = None
    staff_id: Optional[str] = None

class UserResponse(UserBase):
    user_id: int
    full_name: str
    enrolled_at: datetime.datetime
    last_seen: Optional[datetime.datetime] = None
    roles: List[RoleResponse] = []
    imagepath: Optional[str] = None
    face_enrolled: bool = False
    
    student: Optional[StudentBase] = None
    lecturer: Optional[LecturerBase] = None
    staff: Optional[StaffBase] = None
    visitor: Optional[VisitorBase] = None
    admin: Optional[AdminBase] = None

    office_node_id: Optional[int] = None
    staff_id: Optional[str] = None

class UserResponse(UserBase):
    user_id: int
    full_name: str
    enrolled_at: datetime.datetime
    last_seen: Optional[datetime.datetime] = None
    roles: List[RoleResponse] = []
    imagepath: Optional[str] = None
    face_enrolled: bool = False
    
    student: Optional[StudentBase] = None
    lecturer: Optional[LecturerBase] = None
    staff: Optional[StaffBase] = None
    visitor: Optional[VisitorBase] = None
    admin: Optional[AdminBase] = None

class StudentCreate(StudentBase):
    user: Optional[UserCreate] = None
    user_id: Optional[int] = None

class StudentUpdate(BaseSchema):
    student_id: Optional[str] = None
    program: Optional[str] = None
    faculty: Optional[str] = None
    programme_id: Optional[str] = None
    faculty_id: Optional[str] = None
    intake: Optional[int] = None
    enrolled_since: Optional[datetime.date] = None
    enrollment_status: Optional[EnrollmentStatusEnum] = None
    user: Optional[UserUpdate] = None

class StudentResponse(StudentBase):
    user_id: int
    user: UserResponse

class LecturerCreate(LecturerBase):
    user: Optional[UserCreate] = None
    user_id: Optional[int] = None

class LecturerUpdate(BaseSchema):
    lecturer_id: Optional[str] = None
    department: Optional[str] = None
    faculty: Optional[str] = None
    department_id: Optional[str] = None
    faculty_id: Optional[str] = None
    position: Optional[str] = None
    is_head_of_department: Optional[bool] = None
    office_node_id: Optional[int] = None
    user: Optional[UserUpdate] = None

class LecturerResponse(LecturerBase):
    user_id: int
    user: UserResponse

class StaffCreate(StaffBase):
    user: Optional[UserCreate] = None
    user_id: Optional[int] = None

class StaffUpdate(BaseSchema):
    staff_id: Optional[str] = None
    department: Optional[str] = None
    department_id: Optional[str] = None
    position: Optional[str] = None
    staff_type: Optional[StaffTypeEnum] = None
    office_node_id: Optional[int] = None
    user: Optional[UserUpdate] = None

class StaffResponse(StaffBase):
    user_id: int
    user: UserResponse

class VisitorCreate(VisitorBase):
    user: Optional[UserCreate] = None
    user_id: Optional[int] = None

class VisitorUpdate(BaseSchema):
    visitor_id: Optional[str] = None
    id_number: Optional[str] = None
    organization: Optional[str] = None
    visit_purpose: Optional[str] = None
    access_expiry: Optional[datetime.datetime] = None
    access_start: Optional[datetime.datetime] = None
    user: Optional[UserUpdate] = None

class VisitorResponse(VisitorBase):
    user_id: int
    user: UserResponse

class AdminCreate(AdminBase):
    user: Optional[UserCreate] = None
    user_id: Optional[int] = None
    password: str

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    password: str

class AdminUpdate(BaseSchema):
    admin_id: Optional[str] = None
    admin_type: Optional[AdminTypeEnum] = None
    department: Optional[str] = None
    department_id: Optional[str] = None
    office_node_id: Optional[int] = None
    password: Optional[str] = None
    user: Optional[UserUpdate] = None

class AdminResponse(AdminBase):
    user_id: int
    user: Optional[UserResponse] = None

# ==========================================
# Category 2: RAG Schemas
# ==========================================
class UploadedDocumentBase(BaseSchema):
    title: str
    filename: str
    file_path: str
    uploaded_by: int
    access_level: AccessLevelEnum = AccessLevelEnum.PUBLIC
    is_active: bool = True

class UploadedDocumentCreate(UploadedDocumentBase):
    pass

class UploadedDocumentResponse(UploadedDocumentBase):
    document_id: int
    uploaded_at: datetime.datetime
    chunking_status: str


class DocumentChunkBase(BaseSchema):
    document_id: int
    chunk_index: int
    chunk_text: str
    char_count: Optional[int] = None
    access_level: AccessLevelEnum
    is_outdated: bool = False

class DocumentChunkResponse(DocumentChunkBase):
    chunk_id: int
    created_at: datetime.datetime

class EmbeddingVectorBase(BaseSchema):
    chunk_id: int
    embedding: str
    model_version: str

class EmbeddingVectorResponse(EmbeddingVectorBase):
    vector_id: int
    created_at: datetime.datetime

class ChatbotQueryBase(BaseSchema):
    session_id: int
    user_id: Optional[int] = None
    query_text: str
    response_text: Optional[str] = None
    retrieved_chunks: Optional[List[int]] = None
    response_time_ms: Optional[int] = None
    is_navigational: bool = False

class ChatbotQueryResponse(ChatbotQueryBase):
    query_id: int
    timestamp: datetime.datetime

# ==========================================
# Category 3: Infrastructure Schemas
# ==========================================
class DeviceBase(BaseSchema):
    device_id: str
    device_name: str
    node_id: int
    device_type: DeviceTypeEnum
    ip_address: Optional[str] = None
    is_active: bool = True

class DeviceCreate(BaseSchema):
    # The cloud assigns this identifier when a new device is provisioned.
    # Keeping it optional prevents administrators from choosing colliding or
    # misleading hardware identifiers in the dashboard.
    device_id: Optional[str] = None
    device_name: str
    node_id: int
    device_type: DeviceTypeEnum
    ip_address: Optional[str] = None
    is_active: bool = True

class DeviceUpdate(BaseSchema):
    device_name: Optional[str] = None
    node_id: Optional[int] = None
    device_type: Optional[DeviceTypeEnum] = None
    ip_address: Optional[str] = None
    is_active: Optional[bool] = None

class DeviceResponse(DeviceBase):
    last_heartbeat: Optional[datetime.datetime] = None
    installed_at: datetime.datetime
    # Returned only by the provisioning endpoint, never persisted in the
    # response model for normal device reads.
    provisioned_secret: Optional[str] = None

class NodeRBACBase(BaseSchema):
    node_id: int
    role_id: int

class EdgeRBACBase(BaseSchema):
    edge_id: int
    role_id: int

class JWTSessionResponse(BaseSchema):
    session_id: int
    user_id: int
    token_hash: Optional[str] = None
    issued_at: datetime.datetime
    expires_at: datetime.datetime
    device_id: Optional[str] = None
    is_revoked: bool
    session_uuid: Optional[str] = None
    jti: Optional[str] = None
    principal_type: str = "ADMIN"
    
    # Backwards compatibility fields
    created_at: Optional[datetime.datetime] = None
    admin_id: Optional[str] = None

class AuthenticationLogResponse(BaseSchema):
    log_id: int
    sync_key: str
    user_id: Optional[int] = None
    device_id: str
    auth_status: str
    confidence_score: Optional[float] = None
    face_count: int = 1
    reason: Optional[str] = None
    spoofing_checked: bool = True
    spoofing_passed: Optional[bool] = None
    timestamp: datetime.datetime
    image_path: Optional[str] = None
    node_id: Optional[int] = None
    policy_version: Optional[str] = None
    decision_reason: Optional[str] = None
    correlation_id: Optional[str] = None
    
    # Backwards compatibility fields
    email: Optional[str] = None
    status: Optional[AuthStatusEnum] = None
    attempted_at: Optional[datetime.datetime] = None

class AuthenticationLogCreate(BaseSchema):
    sync_key: str
    user_id: Optional[int] = None
    device_id: str
    auth_status: str
    confidence_score: Optional[float] = None
    face_count: int = 1
    reason: Optional[str] = None
    spoofing_checked: bool = True
    spoofing_passed: Optional[bool] = None
    image_path: Optional[str] = None
    node_id: Optional[int] = None
    policy_version: Optional[str] = None
    decision_reason: Optional[str] = None
    correlation_id: Optional[str] = None
    
    # Backwards compatibility fields
    email: Optional[str] = None
    status: Optional[AuthStatusEnum] = None

class SurveillanceLogResponse(BaseSchema):
    log_id: int
    sync_key: str
    user_id: Optional[int] = None
    device_id: str
    recognition_status: str
    confidence_score: Optional[float] = None
    matched_template: Optional[str] = None
    face_count: int = 1
    bbox: Optional[Any] = None
    timestamp: datetime.datetime
    image_path: Optional[str] = None

class LastKnownLocationResponse(BaseSchema):
    user_id: int
    email: str
    full_name: str
    is_active: bool
    last_seen: Optional[datetime.datetime] = None
    last_known_location: Optional[int] = None
    room_label: Optional[str] = None
    floor_level: Optional[int] = None
    building_name: Optional[str] = None

# ==========================================
# Category 4: Academic Schemas
# ==========================================
class CourseBase(BaseSchema):
    course_code: str
    course_name: str
    credit_hours: int
    department: Optional[str] = None
    faculty: Optional[str] = None
    programme_id: Optional[str] = None
    faculty_id: Optional[str] = None
    course_level: CourseLevelEnum
    is_active: bool = True

class CourseCreate(CourseBase):
    pass

class CourseResponse(CourseBase):
    course_id: int

class CourseEnrollmentBase(BaseSchema):
    student_id: str
    course_id: int
    semester: int
    academic_year: str
    status: EnrollmentStatusAcademicEnum = EnrollmentStatusAcademicEnum.ENROLLED

class CourseEnrollmentCreate(CourseEnrollmentBase):
    pass

class CourseEnrollmentResponse(CourseEnrollmentBase):
    enrollment_id: int
    enrolled_at: datetime.datetime
    course_code: Optional[str] = None

class TimetableBase(BaseSchema):
    course_id: int
    lecturer_id: str
    day_of_week: DayOfWeekEnum
    start_time: datetime.time
    end_time: datetime.time
    node_id: int
    semester: int
    academic_year: str

class TimetableCreate(TimetableBase):
    pass

class TimetableResponse(TimetableBase):
    timetable_id: int
    created_at: datetime.datetime
    course_code: Optional[str] = None

class AppointmentBase(BaseSchema):
    guest_user_id: int
    host_user_id: int
    scheduled_at: datetime.datetime
    duration_minutes: int = 30
    node_id: Optional[int] = None
    status: AppointmentStatusEnum = AppointmentStatusEnum.PENDING
    purpose: Optional[str] = None
    host_email: Optional[str] = None

class AppointmentCreate(AppointmentBase):
    pass

class AppointmentUpdate(BaseSchema):
    status: Optional[AppointmentStatusEnum] = None
    scheduled_at: Optional[datetime.datetime] = None
    duration_minutes: Optional[int] = None
    node_id: Optional[int] = None
    purpose: Optional[str] = None
    host_email: Optional[str] = None

class AppointmentResponse(AppointmentBase):
    appointment_id: int
    created_at: datetime.datetime

class NotificationBase(BaseSchema):
    title: str
    body: str
    appointment_id: Optional[int] = None
    recipient_user_id: Optional[int] = None
    event_type: Optional[str] = None
    status: Optional[str] = None
    message_id: Optional[str] = None
    delivery_error: Optional[str] = None
    created_at: Optional[datetime.datetime] = None
    expires_at: Optional[datetime.datetime] = None

class NotificationCreate(NotificationBase):
    pass

class NotificationResponse(NotificationBase):
    notification_id: int
    sent_at: Optional[datetime.datetime] = None

# ==========================================
# Category 5: Structural & Org Schemas
# ==========================================
class FacultyBase(BaseSchema):
    faculty_id: str
    faculty_name: str
    dean_id: str

class FacultyCreate(FacultyBase):
    pass

class FacultyUpdate(BaseSchema):
    faculty_name: Optional[str] = None
    dean_id: Optional[str] = None

class FacultyResponse(FacultyBase):
    pass

class DepartmentBase(BaseSchema):
    department_id: str
    department_name: str
    manager_id: str

class DepartmentCreate(DepartmentBase):
    pass

class DepartmentUpdate(BaseSchema):
    department_name: Optional[str] = None
    manager_id: Optional[str] = None

class DepartmentResponse(DepartmentBase):
    pass

class ProgrammeBase(BaseSchema):
    programme_id: str
    programme_name: str
    faculty_id: str
    hop_id: str

class ProgrammeCreate(ProgrammeBase):
    pass

class ProgrammeUpdate(BaseSchema):
    programme_name: Optional[str] = None
    faculty_id: Optional[str] = None
    hop_id: Optional[str] = None

class ProgrammeResponse(ProgrammeBase):
    pass

# ==========================================
# Category 6: Update Schemas
# ==========================================
class CourseUpdate(BaseSchema):
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    credit_hours: Optional[int] = None
    department: Optional[str] = None
    faculty: Optional[str] = None
    programme_id: Optional[str] = None
    faculty_id: Optional[str] = None
    course_level: Optional[CourseLevelEnum] = None
    is_active: Optional[bool] = None

class CourseEnrollmentUpdate(BaseSchema):
    student_id: Optional[str] = None
    course_id: Optional[int] = None
    semester: Optional[int] = None
    academic_year: Optional[str] = None
    status: Optional[EnrollmentStatusAcademicEnum] = None

class TimetableUpdate(BaseSchema):
    course_id: Optional[int] = None
    lecturer_id: Optional[str] = None
    day_of_week: Optional[DayOfWeekEnum] = None
    start_time: Optional[datetime.time] = None
    end_time: Optional[datetime.time] = None
    node_id: Optional[int] = None
    semester: Optional[int] = None
    academic_year: Optional[str] = None

class RoleUpdate(BaseSchema):
    role_name: Optional[str] = None
    description: Optional[str] = None

