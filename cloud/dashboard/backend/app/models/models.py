import datetime
import json
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Text, DateTime, Date, Time, ForeignKey, Enum, Boolean, JSON, Float, UniqueConstraint, LargeBinary
from sqlalchemy.types import UserDefinedType
from sqlalchemy.orm import relationship
from app.core.database import Base

class VECTOR(UserDefinedType):
    def __init__(self, dim):
        self.dim = dim

    def get_col_spec(self, **kw):
        return f"VECTOR({self.dim})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if isinstance(value, list):
                return "[" + ",".join(map(str, value)) + "]"
            return value
        return process

    def bind_expression(self, bindvalue):
        from sqlalchemy import func
        return func.STRING_TO_VECTOR(bindvalue)

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if hasattr(value, "tolist"):
                value = value.tolist()
            if isinstance(value, list):
                return json.dumps(value)
            if isinstance(value, str):
                return value
            return value
        return process

# ==========================================
# Structural Reference Tables
# ==========================================

class Building(Base):
    __tablename__ = "buildings"
    
    building_id = Column(Integer, primary_key=True, autoincrement=True)
    building_name = Column(String(100), nullable=False)
    
    floorplans = relationship("Floorplan", back_populates="building", cascade="all, delete-orphan")

class Floorplan(Base):
    __tablename__ = "floorplans"
    
    floorplan_id = Column(Integer, primary_key=True, autoincrement=True)
    building_id = Column(Integer, ForeignKey("buildings.building_id"), nullable=False)
    floor_level = Column(Integer, nullable=False)
    image_path = Column(String(500), nullable=False)
    scale_ratio = Column(Float, nullable=True)
    
    building = relationship("Building", back_populates="floorplans")
    nodes = relationship("Node", back_populates="floorplan", cascade="all, delete-orphan")

class Node(Base):
    __tablename__ = "nodes"
    
    node_id = Column(Integer, primary_key=True, autoincrement=True)
    floorplan_id = Column(Integer, ForeignKey("floorplans.floorplan_id"), nullable=False)
    cord_x = Column(Float, nullable=False)
    cord_y = Column(Float, nullable=False)
    room_label = Column(String(100), nullable=False)
    is_accessible = Column(Enum("ALLOW", "DENY"), default="ALLOW", nullable=False)
    node_type = Column(Enum('ROOM','CORRIDOR','ENTRANCE','STAIRWELL','ELEVATOR','CAFETERIA','OFFICE','LABORATORY','LECTURE_HALL','RESTROOM','OUTDOOR','OTHER'), nullable=False)
    
    floorplan = relationship("Floorplan", back_populates="nodes")
    
    # Self-referential or circular dependencies: edges refer to nodes.
    # We define primaryjoin explicitly in Edge.

class Edge(Base):
    __tablename__ = "edges"
    
    edge_id = Column(Integer, primary_key=True, autoincrement=True)
    source_node_id = Column(Integer, ForeignKey("nodes.node_id"), nullable=False)
    destination_node_id = Column(Integer, ForeignKey("nodes.node_id"), nullable=False)
    weight_distance = Column(Float, nullable=False)
    is_accessible = Column(Enum("ALLOW", "DENY"), default="ALLOW", nullable=False)
    is_bidirectional = Column(Boolean, default=True, nullable=False)
    
    source_node = relationship("Node", foreign_keys=[source_node_id])
    destination_node = relationship("Node", foreign_keys=[destination_node_id])

# ==========================================
# Category 1: Identity & Access Management (IAM)
# ==========================================

class Role(Base):
    __tablename__ = "roles"
    
    role_id = Column(Integer, primary_key=True, autoincrement=True)
    role_name = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    users = relationship("User", secondary="user_roles", back_populates="roles")
    node_rbac = relationship("NodeRBAC", back_populates="role", cascade="all, delete-orphan")
    edge_rbac = relationship("EdgeRBAC", back_populates="role", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"
    
    user_id = Column(Integer, primary_key=True, autoincrement=True)
    given_name = Column(String(150), nullable=False)
    family_name = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    enrolled_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    last_seen = Column(DateTime, nullable=True)
    last_known_location = Column(Integer, ForeignKey("nodes.node_id"), nullable=True)
    
    roles = relationship("Role", secondary="user_roles", back_populates="users")
    location = relationship("Node", foreign_keys=[last_known_location])
    
    images = relationship("UserImage", back_populates="user", cascade="all, delete-orphan")
    embeddings = relationship("UserFaceEmbedding", back_populates="user", cascade="all, delete-orphan")
    
    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}"
        
    @property
    def imagepath(self) -> Optional[str]:
        for img in self.images:
            if img.template_name == "front":
                return img.image_path
        if self.images:
            return self.images[0].image_path
        return None
        
    @property
    def face_vector(self) -> Optional[str]:
        for emb in self.embeddings:
            if emb.template_name == "front" and emb.model_name == "openvc_sface":
                try:
                    import json
                    import numpy as np
                    arr = np.frombuffer(emb.embedding, dtype=np.float32)
                    return json.dumps([round(float(v), 6) for v in arr.tolist()])
                except Exception:
                    pass
        return None
    
    # Sub-profiles
    student = relationship("Student", back_populates="user", uselist=False, cascade="all, delete-orphan")
    lecturer = relationship("Lecturer", back_populates="user", uselist=False, cascade="all, delete-orphan")
    staff = relationship("Staff", back_populates="user", uselist=False, cascade="all, delete-orphan")
    visitor = relationship("Visitor", foreign_keys="[Visitor.user_id]", back_populates="user", uselist=False, cascade="all, delete-orphan")
    admin = relationship("Admin", back_populates="user", uselist=False, cascade="all, delete-orphan")
    
    uploaded_documents = relationship("UploadedDocument", back_populates="uploader")
    chatbot_queries = relationship("ChatbotQuery", back_populates="user")
    sessions = relationship("JWTSession", back_populates="user", cascade="all, delete-orphan")
    
    # Appointments
    appointments_guest = relationship("Appointment", foreign_keys="[Appointment.guest_user_id]", back_populates="guest")
    appointments_host = relationship("Appointment", foreign_keys="[Appointment.host_user_id]", back_populates="host")

class UserRole(Base):
    __tablename__ = "user_roles"
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.role_id", ondelete="CASCADE"), primary_key=True)

class UserImage(Base):
    __tablename__ = "user_images"
    image_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    template_name = Column(Enum("front", "left_30", "right_30", "left_60", "right_60", "slightly_up", "slightly_down", "low_light"), nullable=False)
    image_path = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User", back_populates="images")
    
    __table_args__ = (
        UniqueConstraint("user_id", "template_name", name="uq_user_images_template"),
    )

class UserFaceEmbedding(Base):
    __tablename__ = "user_face_embeddings"
    embedding_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    template_name = Column(String(50), nullable=False)
    model_name = Column(Enum("arcface_mobilefacenet", "arcface_r50", "openvc_sface", "auraface"), nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User", back_populates="embeddings")
    
    __table_args__ = (
        UniqueConstraint("user_id", "template_name", "model_name", name="uq_user_embeddings_template_model"),
    )

class Department(Base):
    __tablename__ = "departments"
    department_id = Column(String(50), primary_key=True)
    department_name = Column(String(150), nullable=False)
    manager_id = Column(String(50), ForeignKey("staff.staff_id", use_alter=True, name="fk_departments_manager"), unique=True, nullable=False)
    
    manager = relationship("Staff", foreign_keys=[manager_id], post_update=True)

class Faculty(Base):
    __tablename__ = "faculties"
    faculty_id = Column(String(50), primary_key=True)
    faculty_name = Column(String(150), nullable=False)
    dean_id = Column(String(50), ForeignKey("staff.staff_id", use_alter=True, name="fk_faculties_dean"), unique=True, nullable=False)
    
    dean = relationship("Staff", foreign_keys=[dean_id], post_update=True)

class Programme(Base):
    __tablename__ = "programmes"
    programme_id = Column(String(50), primary_key=True)
    programme_name = Column(String(250), nullable=False)
    faculty_id = Column(String(50), ForeignKey("faculties.faculty_id"), nullable=False)
    hop_id = Column(String(50), ForeignKey("staff.staff_id", use_alter=True, name="fk_programmes_hop"), unique=True, nullable=False)
    
    faculty = relationship("Faculty")
    hop = relationship("Staff", foreign_keys=[hop_id], post_update=True)

class Staff(Base):
    __tablename__ = "staff"
    
    staff_id = Column(String(50), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), unique=True, nullable=False)
    department_id = Column(String(50), ForeignKey("departments.department_id", ondelete="RESTRICT"), nullable=False)
    position = Column(String(100), nullable=False)
    office_node_id = Column(Integer, ForeignKey("nodes.node_id", ondelete="SET NULL"), nullable=True)
    
    user = relationship("User", back_populates="staff")
    office = relationship("Node")
    department_rel = relationship("Department", foreign_keys=[department_id])
    
    @property
    def staff_number(self):
        return self.staff_id
        
    @property
    def department(self):
        return self.department_rel.department_name if self.department_rel else ""
        
    @property
    def staff_type(self):
        return "ADMINISTRATIVE"

class Student(Base):
    __tablename__ = "students"
    
    student_id = Column(String(50), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), unique=True, nullable=False)
    programme_id = Column(String(50), ForeignKey("programmes.programme_id", ondelete="RESTRICT"), nullable=False)
    faculty_id = Column(String(50), ForeignKey("faculties.faculty_id", ondelete="RESTRICT"), nullable=False)
    intake = Column(Integer, nullable=False)
    enrollment_status = Column(Enum("ACTIVE", "INACTIVE", "GRADUATED", "SUSPENDED"), default="ACTIVE", nullable=False)
    enrolled_since = Column(Date, nullable=False)
    
    user = relationship("User", back_populates="student")
    programme_rel = relationship("Programme")
    faculty_rel = relationship("Faculty")
    enrollments = relationship("CourseEnrollment", back_populates="student", cascade="all, delete-orphan")
    
    @property
    def program(self):
        return self.programme_rel.programme_name if self.programme_rel else ""
        
    @property
    def faculty(self):
        return self.faculty_rel.faculty_name if self.faculty_rel else ""

class Lecturer(Base):
    __tablename__ = "lecturers"
    
    lecturer_id = Column(String(50), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), unique=True, nullable=False)
    staff_id = Column(String(50), ForeignKey("staff.staff_id", ondelete="RESTRICT"), nullable=False)
    faculty_id = Column(String(50), ForeignKey("faculties.faculty_id", ondelete="RESTRICT"), nullable=False)
    Position_desc = Column(String(100), nullable=False)
    office_node_id = Column(Integer, ForeignKey("nodes.node_id", ondelete="SET NULL"), nullable=True)
    
    user = relationship("User", back_populates="lecturer")
    staff = relationship("Staff")
    faculty_rel = relationship("Faculty")
    office = relationship("Node")
    timetables = relationship("Timetable", back_populates="lecturer", cascade="all, delete-orphan")
    
    @property
    def staff_number(self):
        return self.staff_id
        
    @property
    def department(self):
        return self.staff.department if self.staff else ""

    @property
    def department_id(self):
        return self.staff.department_id if self.staff else None
        
    @property
    def faculty(self):
        return self.faculty_rel.faculty_name if self.faculty_rel else ""
        
    @property
    def position(self):
        return self.Position_desc
        
    @property
    def is_head_of_department(self):
        return False

class Visitor(Base):
    __tablename__ = "visitors"
    
    visitor_id = Column(String(50), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), unique=True, nullable=False)
    id_number = Column(String(50), nullable=False)
    organization = Column(String(150), nullable=True)
    visit_purpose = Column(Text, nullable=True)
    access_expiry = Column(DateTime, nullable=False)
    registered_by = Column(Integer, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False)
    
    user = relationship("User", foreign_keys=[user_id], back_populates="visitor")
    registrar = relationship("User", foreign_keys=[registered_by])

class Admin(Base):
    __tablename__ = "admins"
    
    admin_id = Column(String(50), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), unique=True, nullable=False)
    staff_id = Column(String(50), ForeignKey("staff.staff_id", ondelete="RESTRICT"), nullable=False)
    admin_type = Column(Enum("SUPER_ADMIN", "SYSTEM_ADMIN", "CONTENT_ADMIN"), nullable=False)
    password_hash = Column(String(255), nullable=False)
    
    user = relationship("User", back_populates="admin")
    staff = relationship("Staff")
    
    @property
    def staff_number(self):
        return self.staff_id
        
    @property
    def department(self):
        return self.staff.department if self.staff else ""

    @property
    def department_id(self):
        return self.staff.department_id if self.staff else None
        
    @property
    def office_node_id(self):
        return self.staff.office_node_id if self.staff else None
        
    @property
    def Password_hash(self):
        return self.password_hash
        
    @Password_hash.setter
    def Password_hash(self, val):
        self.password_hash = val

# ==========================================
# Category 2: RAG Knowledge Base & Document Management
# ==========================================

class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"
    
    document_id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    access_level = Column(Enum("PUBLIC", "STUDENT", "LECTURER", "ADMIN"), default="PUBLIC", nullable=False)
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_active = Column(Boolean, default=True, nullable=False)
    
    uploader = relationship("User", back_populates="uploaded_documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    @property
    def is_chunked(self) -> bool:
        return len(self.chunks) > 0


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    
    chunk_id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("uploaded_documents.document_id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    char_count = Column(Integer, nullable=True)
    access_level = Column(Enum("PUBLIC", "STUDENT", "LECTURER", "ADMIN"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_outdated = Column(Boolean, default=False, nullable=False)
    
    document = relationship("UploadedDocument", back_populates="chunks")
    embeddings = relationship("EmbeddingVector", back_populates="chunk", cascade="all, delete-orphan")

class EmbeddingVector(Base):
    __tablename__ = "embedding_vectors"
    
    vector_id = Column(Integer, primary_key=True, autoincrement=True)
    chunk_id = Column(Integer, ForeignKey("document_chunks.chunk_id"), nullable=False)
    embedding = Column(VECTOR(3072), nullable=False) # Stores native 3072-dim float arrays
    model_version = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    chunk = relationship("DocumentChunk", back_populates="embeddings")

class ChatbotQuery(Base):
    __tablename__ = "chatbot_queries"
    
    query_id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("jwt_sessions.session_id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    query_text = Column(Text, nullable=False)
    response_text = Column(Text, nullable=True)
    retrieved_chunks = Column(JSON, nullable=True) # JSON array of chunk IDs
    response_time_ms = Column(Integer, nullable=True)
    is_navigational = Column(Boolean, default=False, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User", back_populates="chatbot_queries")
    session = relationship("JWTSession")

# ==========================================
# Category 3: Infrastructure & Security Management
# ==========================================

class Device(Base):
    __tablename__ = "devices"
    
    device_id = Column(String(100), primary_key=True)
    device_name = Column(String(100), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.node_id"), nullable=False)
    device_type = Column(Enum("KIOSK", "ENTRY_GATE", "CLASSROOM", "OFFICE", "OTHER"), nullable=False)
    ip_address = Column(String(45), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_heartbeat = Column(DateTime, nullable=True)
    installed_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    node = relationship("Node")

class NodeRBAC(Base):
    __tablename__ = "node_rbac"
    
    node_id = Column(Integer, ForeignKey("nodes.node_id"), primary_key=True, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.role_id"), primary_key=True, nullable=False)
    
    node = relationship("Node")
    role = relationship("Role", back_populates="node_rbac")

class EdgeRBAC(Base):
    __tablename__ = "edge_rbac"
    
    edge_id = Column(Integer, ForeignKey("edges.edge_id"), primary_key=True, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.role_id"), primary_key=True, nullable=False)
    
    edge = relationship("Edge")
    role = relationship("Role", back_populates="edge_rbac")

class JWTSession(Base):
    __tablename__ = "jwt_sessions"
    
    session_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(512), nullable=False)
    issued_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    device_id = Column(String(100), ForeignKey("devices.device_id", ondelete="SET NULL"), nullable=True)
    is_revoked = Column(Boolean, default=False, nullable=False)
    
    user = relationship("User")
    device = relationship("Device")
    
    @property
    def created_at(self):
        return self.issued_at
        
    @property
    def admin_id(self):
        # Support backwards compatibility in case anything reads admin_id from session (e.g. if we want to get the user's admin profile id)
        if self.user and self.user.admin:
            return self.user.admin.admin_id
        return ""

class AuthenticationLog(Base):
    __tablename__ = "authentication_logs"
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    sync_key = Column(String(26), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    device_id = Column(String(100), ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False)
    auth_status = Column(Enum("SUCCESS", "FAILED", "SPOOFING"), nullable=False)
    confidence_score = Column(Float, nullable=True)
    face_count = Column(Integer, default=1, nullable=False)
    reason = Column(String(255), nullable=True)
    spoofing_checked = Column(Boolean, default=True, nullable=False)
    spoofing_passed = Column(Boolean, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    image_path = Column(String(500), nullable=True)
    
    user = relationship("User")
    device = relationship("Device")
    
    @property
    def email(self):
        return self.user.email if self.user else ""
        
    @property
    def status(self):
        # Backwards compatibility with AuthStatusEnum in older API
        return self.auth_status
        
    @property
    def attempted_at(self):
        return self.timestamp

class SurveillanceLog(Base):
    __tablename__ = "surveillance_logs"
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    sync_key = Column(String(26), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    device_id = Column(String(100), ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False)
    recognition_status = Column(Enum("RECOGNIZED", "UNKNOWN"), nullable=False)
    confidence_score = Column(Float, nullable=True)
    matched_template = Column(String(50), nullable=True)
    face_count = Column(Integer, default=1, nullable=False)
    bbox = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    image_path = Column(String(500), nullable=True)
    
    user = relationship("User")
    device = relationship("Device")

# ==========================================
# Category 4: Academic & Scheduling Operations
# ==========================================

class Course(Base):
    __tablename__ = "courses"
    
    course_id = Column(Integer, primary_key=True, autoincrement=True)
    course_code = Column(String(20), unique=True, nullable=False)
    course_name = Column(String(200), nullable=False)
    credit_hours = Column(Integer, nullable=False)
    programme_id = Column(String(50), ForeignKey("programmes.programme_id", ondelete="RESTRICT"), nullable=False)
    course_level = Column(Enum("UNDERGRADUATE", "POSTGRADUATE"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    programme_rel = relationship("Programme")
    enrollments = relationship("CourseEnrollment", back_populates="course", cascade="all, delete-orphan")
    timetables = relationship("Timetable", back_populates="course", cascade="all, delete-orphan")
    
    @property
    def department(self):
        return self.programme_rel.programme_name if self.programme_rel else ""
        
    @property
    def faculty(self):
        return self.programme_rel.faculty.faculty_name if (self.programme_rel and self.programme_rel.faculty) else ""

    @property
    def faculty_id(self):
        return self.programme_rel.faculty_id if self.programme_rel else None

class CourseEnrollment(Base):
    __tablename__ = "course_enrollments"
    
    enrollment_id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(50), ForeignKey("students.student_id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.course_id"), nullable=False)
    semester = Column(Integer, nullable=False) # e.g. 202607
    academic_year = Column(String(10), nullable=False) # e.g. '2025/2026'
    status = Column(Enum("ENROLLED", "WITHDRAWN", "COMPLETED", "FAILED"), default="ENROLLED", nullable=False)
    enrolled_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    student = relationship("Student", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")
    
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", "semester", name="uq_student_course_semester"),
    )

class Timetable(Base):
    __tablename__ = "timetables"
    
    timetable_id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("courses.course_id"), nullable=False)
    lecturer_id = Column(String(50), ForeignKey("lecturers.lecturer_id"), nullable=False)
    day_of_week = Column(Enum("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.node_id"), nullable=False)
    semester = Column(Integer, nullable=False)
    academic_year = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    course = relationship("Course", back_populates="timetables")
    lecturer = relationship("Lecturer", back_populates="timetables")
    classroom = relationship("Node")
    
    __table_args__ = (
        UniqueConstraint("node_id", "day_of_week", "start_time", "semester", name="uq_node_time_semester"),
    )

class Appointment(Base):
    __tablename__ = "appointments"
    
    appointment_id = Column(Integer, primary_key=True, autoincrement=True)
    guest_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    host_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=30, nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.node_id"), nullable=True)
    status = Column(Enum("PENDING", "CONFIRMED", "CANCELLED", "COMPLETED"), default="PENDING", nullable=False)
    purpose = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    host_email = Column(String(255), nullable=True)
    
    guest = relationship("User", foreign_keys=[guest_user_id], back_populates="appointments_guest")
    host = relationship("User", foreign_keys=[host_user_id], back_populates="appointments_host")
    location = relationship("Node")
    
    notifications = relationship("Notification", back_populates="appointment", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint("host_user_id", "scheduled_at", name="uq_host_scheduled_time"),
    )

class Notification(Base):
    __tablename__ = "notifications"
    
    notification_id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.appointment_id"), nullable=False)
    sent_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    
    appointment = relationship("Appointment", back_populates="notifications")


class DeletedUser(Base):
    __tablename__ = "deleted_users"
    
    user_id = Column(Integer, primary_key=True)
    deleted_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


from sqlalchemy import event
from sqlalchemy.sql import text

@event.listens_for(User, 'after_delete')
def receive_after_delete(mapper, connection, target):
    try:
        connection.execute(
            text("INSERT INTO deleted_users (user_id, deleted_at) VALUES (:user_id, :deleted_at)"),
            {"user_id": target.user_id, "deleted_at": datetime.datetime.utcnow()}
        )
    except Exception as e:
        import logging
        logging.getLogger("sqlalchemy.event").error(f"Failed to log deleted user {target.user_id}: {e}")

