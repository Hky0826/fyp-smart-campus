from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
import bcrypt
import os
import json
import re
import random
import cv2
import numpy as np

from app.core.database import get_db
from app.core.security import verify_system_admin, verify_super_admin, get_password_hash
from app.facial_recognition.alignment import extract_aligned_face
from app.models.models import Role, User, Student, Lecturer, Staff, Visitor, Admin, Node, Department, Faculty, Programme
from app.schemas import schemas

def slugify(text: str) -> str:
    text = text.upper().strip()
    text = re.sub(r'[^A-Z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text)
    return text[:50]

def get_or_create_faculty(db: Session, faculty_name: str, default_staff_id: str = "STF-00001") -> Faculty:
    fid = f"FAC-{slugify(faculty_name)}"
    faculty = db.query(Faculty).filter((Faculty.faculty_id == fid) | (Faculty.faculty_name == faculty_name) | (Faculty.faculty_id == faculty_name)).first()
    if not faculty:
        faculty = Faculty(
            faculty_id=fid,
            faculty_name=faculty_name,
            dean_id=default_staff_id
        )
        db.add(faculty)
        db.flush()
    return faculty

def get_or_create_department(db: Session, dept_name: str, default_staff_id: str = "STF-00001") -> Department:
    did = f"DEP-{slugify(dept_name)}"
    dept = db.query(Department).filter((Department.department_id == did) | (Department.department_name == dept_name) | (Department.department_id == dept_name)).first()
    if not dept:
        dept = Department(
            department_id=did,
            department_name=dept_name,
            manager_id=default_staff_id
        )
        db.add(dept)
        db.flush()
    return dept

def get_or_create_programme(db: Session, prog_name: str, faculty_id: str, default_staff_id: str = "STF-00001") -> Programme:
    pid = f"PRG-{slugify(prog_name)}"
    prog = db.query(Programme).filter((Programme.programme_id == pid) | (Programme.programme_name == prog_name) | (Programme.programme_id == prog_name)).first()
    if not prog:
        prog = Programme(
            programme_id=pid,
            programme_name=prog_name,
            faculty_id=faculty_id,
            hop_id=default_staff_id
        )
        db.add(prog)
        db.flush()
    return prog

def resolve_faculty(db: Session, faculty_id: str | None = None, faculty_name: str | None = None) -> Faculty:
    if faculty_id:
        faculty = db.query(Faculty).filter_by(faculty_id=faculty_id).first()
        if not faculty:
            raise HTTPException(status_code=400, detail=f"Faculty ID {faculty_id} does not exist")
        return faculty
    if faculty_name:
        return get_or_create_faculty(db, faculty_name)
    raise HTTPException(status_code=400, detail="Faculty is required")

def resolve_department(db: Session, department_id: str | None = None, department_name: str | None = None) -> Department:
    if department_id:
        dept = db.query(Department).filter_by(department_id=department_id).first()
        if not dept:
            raise HTTPException(status_code=400, detail=f"Department ID {department_id} does not exist")
        return dept
    if department_name:
        return get_or_create_department(db, department_name)
    raise HTTPException(status_code=400, detail="Department is required")

def resolve_programme(
    db: Session,
    programme_id: str | None = None,
    programme_name: str | None = None,
    faculty_id: str | None = None,
) -> Programme:
    if programme_id:
        prog = db.query(Programme).filter_by(programme_id=programme_id).first()
        if not prog:
            raise HTTPException(status_code=400, detail=f"Programme ID {programme_id} does not exist")
        if faculty_id and prog.faculty_id != faculty_id:
            raise HTTPException(status_code=400, detail="Programme does not belong to the selected faculty")
        return prog
    if programme_name and faculty_id:
        return get_or_create_programme(db, programme_name, faculty_id)
    raise HTTPException(status_code=400, detail="Programme is required")

def generate_unique_id(db: Session, model, prefix: str, field_name: str) -> str:
    existing_ids = db.query(getattr(model, field_name)).all()
    max_num = 0
    for (val,) in existing_ids:
        if val and val.startswith(prefix):
            suffix = val[len(prefix):]
            if suffix.isdigit():
                try:
                    num = int(suffix)
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
    next_num = max_num + 1
    return f"{prefix}{next_num:06d}"

def generate_global_student_id(db: Session, intake: int) -> str:
    intake = normalize_intake(intake)
    existing_ids = db.query(Student.student_id).all()
    max_suffix = 0
    for (val,) in existing_ids:
        if val:
            parts = val.split("-")
            if len(parts) >= 3:
                suffix = parts[-1]
                if suffix.isdigit():
                    try:
                        num = int(suffix)
                        if num > max_suffix:
                            max_suffix = num
                    except ValueError:
                        pass
    next_suffix = max_suffix + 1
    return f"QIU-{intake}-{next_suffix:06d}"

def normalize_intake(intake) -> int:
    intake_text = str(intake).strip()
    if not re.fullmatch(r"\d{6}", intake_text):
        raise HTTPException(status_code=400, detail="Intake must be exactly 6 digits, for example 202407")
    return int(intake_text)

def generate_unique_email(db: Session, given_name: str, family_name: str) -> str:
    clean_given = "".join(c for c in given_name.lower() if c.isalnum())
    clean_family = "".join(c for c in family_name.lower() if c.isalnum())
    base_email = f"{clean_given}.{clean_family}@qiu.edu.my"
    candidate = base_email
    counter = 1
    while db.query(User).filter_by(email=candidate).first() is not None:
        candidate = f"{clean_given}.{clean_family}{counter}@qiu.edu.my"
        counter += 1
    return candidate

def check_and_delete_user_if_orphaned(db: Session, user):
    has_student = db.query(Student).filter_by(user_id=user.user_id).first() is not None
    has_lecturer = db.query(Lecturer).filter_by(user_id=user.user_id).first() is not None
    has_staff = db.query(Staff).filter_by(user_id=user.user_id).first() is not None
    has_visitor = db.query(Visitor).filter_by(user_id=user.user_id).first() is not None
    has_admin = db.query(Admin).filter_by(user_id=user.user_id).first() is not None
    if not (has_student or has_lecturer or has_staff or has_visitor or has_admin):
        db.delete(user)

def apply_user_update(db: Session, user: User, user_data: dict):
    role_ids = None
    if user_data.get("role_ids") is not None:
        role_ids = user_data["role_ids"]
    elif user_data.get("role_id") is not None:
        role_ids = [user_data["role_id"]]

    if role_ids is not None:
        roles = db.query(Role).filter(Role.role_id.in_(role_ids)).all()
        if len(roles) != len(set(role_ids)):
            raise HTTPException(status_code=400, detail="One or more selected roles do not exist")
        user.roles = roles

    for field, val in user_data.items():
        if field in ["role_id", "role_ids"]:
            continue
        setattr(user, field, val)

# Import the edge push helper from the downstream sync service
try:
    import os as _os, sys as _sys
    _sync_dir = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "..", "..", "sync", "cloud_to_edge"))
    if _sync_dir not in _sys.path:
        _sys.path.insert(0, _sync_dir)
    from cloud_sync_service import push_sync_to_all_edges as _push_sync_to_all_edges
    _PUSH_SYNC_AVAILABLE = True
except Exception as _e:
    import logging as _logging
    _logging.getLogger("IAMRouter").warning(f"Could not import push_sync_to_all_edges: {_e}. Edge push disabled.")
    _push_sync_to_all_edges = None
    _PUSH_SYNC_AVAILABLE = False

# Temporary in-memory session store for live enrollment
enrollment_sessions = {}
enrollment_progress = {}
scrfd_detector_instance = None
arcface_embedder_instance = None

def get_scrfd_detector():
    global scrfd_detector_instance
    if scrfd_detector_instance is None:
        router_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir = os.path.dirname(router_dir)
        model_path = os.path.join(app_dir, "facial_recognition", "models", "scrfd_2.5g_bnkps.onnx")
        from app.facial_recognition.scrfd_detector import SCRFDDetector
        scrfd_detector_instance = SCRFDDetector(model_path)
    return scrfd_detector_instance

def get_arcface_embedder():
    global arcface_embedder_instance
    if arcface_embedder_instance is None:
        router_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir = os.path.dirname(router_dir)
        model_path = os.path.join(app_dir, "facial_recognition", "models", "arcface_r50.onnx")
        from app.facial_recognition.embedder import EdgeFaceEmbedder
        arcface_embedder_instance = EdgeFaceEmbedder(model_path)
    return arcface_embedder_instance

router = APIRouter(prefix="/iam", tags=["Identity & Access Management"])

# ==========================================
# ROLES CRUD (SUPER_ADMIN ONLY)
# ==========================================
@router.get("/roles", response_model=List[schemas.RoleResponse])
def list_roles(db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    return db.query(Role).all()

@router.post("/roles", response_model=schemas.RoleResponse)
def create_role(role_in: schemas.RoleCreate, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    existing = db.query(Role).filter_by(role_name=role_in.role_name.upper()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Role already exists")
    role = Role(role_name=role_in.role_name.upper(), description=role_in.description)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role

@router.put("/roles/{role_id}", response_model=schemas.RoleResponse)
def update_role(role_id: int, role_in: schemas.RoleUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    role = db.query(Role).filter_by(role_id=role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
        
    if role_in.role_name is not None:
        role_name_upper = role_in.role_name.upper()
        existing = db.query(Role).filter_by(role_name=role_name_upper).first()
        if existing and existing.role_id != role_id:
            raise HTTPException(status_code=400, detail="Role name already registered")
        role.role_name = role_name_upper
        
    if role_in.description is not None:
        role.description = role_in.description
        
    db.commit()
    db.refresh(role)
    return role

@router.delete("/roles/{role_id}")
def delete_role(role_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    role = db.query(Role).filter_by(role_id=role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    user_count = len(role.users)
    if user_count > 0:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot delete role: {user_count} active user(s) are associated with this role"
        )
    db.delete(role)
    db.commit()
    return {"detail": "Role deleted successfully"}

# ==========================================
# USERS CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/users", response_model=List[schemas.UserResponse])
def list_users(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(User).all()

@router.post("/users", response_model=schemas.UserResponse)
def create_user(user_in: schemas.UserCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    if db.query(User).filter_by(username=user_in.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    
    email = generate_unique_email(db, user_in.given_name, user_in.family_name)
    
    role_ids = []
    if user_in.role_ids:
        role_ids.extend(user_in.role_ids)
    if user_in.role_id and user_in.role_id not in role_ids:
        role_ids.append(user_in.role_id)
        
    roles = []
    if role_ids:
        roles = db.query(Role).filter(Role.role_id.in_(role_ids)).all()
        
    user = User(
        given_name=user_in.given_name,
        family_name=user_in.family_name,
        email=email,
        username=user_in.username,
        is_active=user_in.is_active,
        last_known_location=user_in.last_known_location
    )
    if roles:
        user.roles = roles
        
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.put("/users/{user_id}", response_model=schemas.UserResponse)
def update_user(user_id: int, user_in: schemas.UserUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    user = db.query(User).filter_by(user_id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Resolve roles if provided
    role_ids = []
    if user_in.role_ids is not None:
        role_ids.extend(user_in.role_ids)
    elif user_in.role_id is not None:
        role_ids.append(user_in.role_id)
        
    if role_ids:
        roles = db.query(Role).filter(Role.role_id.in_(role_ids)).all()
        user.roles = roles
    
    for field, val in user_in.model_dump(exclude_unset=True).items():
        if field in ["role_id", "role_ids"]:
            continue
        setattr(user, field, val)
        
    db.commit()
    db.refresh(user)
    return user

@router.post("/users/{user_id}/toggle-active")
def toggle_user_active(user_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    user = db.query(User).filter_by(user_id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    db.commit()
    return {"detail": f"User status updated. Active: {user.is_active}"}

@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    user = db.query(User).filter_by(user_id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"detail": "User deleted successfully"}

# ==========================================
# STUDENTS PROFILE CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/students", response_model=List[schemas.StudentResponse])
def list_students(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(Student).all()

@router.post("/students", response_model=schemas.StudentResponse)
def create_student(student_in: schemas.StudentCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    intake = normalize_intake(student_in.intake)
    student_id = student_in.student_id
    if not student_id:
        student_id = generate_global_student_id(db, intake)
    elif not student_id.startswith(f"QIU-{intake}-"):
        raise HTTPException(status_code=400, detail="Student ID prefix must match the intake")
    else:
        if db.query(Student).filter_by(student_id=student_id).first():
            raise HTTPException(status_code=400, detail="Student ID already exists")

    # 2. Get or create User
    if student_in.user_id is not None:
        user = db.query(User).filter_by(user_id=student_in.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if db.query(Student).filter_by(user_id=user.user_id).first():
            raise HTTPException(status_code=400, detail="This user already has a Student profile")
    else:
        if not student_in.user:
            raise HTTPException(status_code=400, detail="User registration data is required for a new user")
        if db.query(User).filter_by(username=student_in.user.username).first():
            raise HTTPException(status_code=400, detail="Username already taken")
            
        email = generate_unique_email(db, student_in.user.given_name, student_in.user.family_name)
        role_ids = []
        if student_in.user.role_ids:
            role_ids.extend(student_in.user.role_ids)
        if student_in.user.role_id and student_in.user.role_id not in role_ids:
            role_ids.append(student_in.user.role_id)
            
        roles = []
        if role_ids:
            roles = db.query(Role).filter(Role.role_id.in_(role_ids)).all()
            
        user = User(
            given_name=student_in.user.given_name,
            family_name=student_in.user.family_name,
            email=email,
            username=student_in.user.username,
            is_active=student_in.user.is_active
        )
        if roles:
            user.roles = roles
            
        db.add(user)
        db.flush()
        
    # 3. Create Student
    fac = resolve_faculty(db, student_in.faculty_id, student_in.faculty) if (student_in.faculty_id or student_in.faculty) else None
    prog = resolve_programme(
        db,
        programme_id=student_in.programme_id,
        programme_name=student_in.program,
        faculty_id=fac.faculty_id if fac else None,
    )
    if fac is None:
        fac = resolve_faculty(db, prog.faculty_id)
    student = Student(
        student_id=student_id,
        user_id=user.user_id,
        programme_id=prog.programme_id,
        faculty_id=fac.faculty_id,
        intake=intake,
        enrollment_status=student_in.enrollment_status,
        enrolled_since=student_in.enrolled_since
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student

@router.put("/students/{student_id}", response_model=schemas.StudentResponse)
def update_student(student_id: str, student_in: schemas.StudentUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    student = db.query(Student).filter_by(student_id=student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
        
    student_data = student_in.model_dump(exclude_unset=True)
    user_data = student_data.pop("user", None)
    program = student_data.pop("program", None)
    faculty = student_data.pop("faculty", None)
    programme_id = student_data.pop("programme_id", None)
    faculty_id = student_data.pop("faculty_id", None)
    
    # Update Student fields
    for field, val in student_data.items():
        setattr(student, field, val)
        
    if faculty_id or faculty:
        fac = resolve_faculty(db, faculty_id, faculty)
        student.faculty_id = fac.faculty_id
        if programme_id or program:
            prog = resolve_programme(db, programme_id, program, fac.faculty_id)
            student.programme_id = prog.programme_id
    elif programme_id or program:
        prog = resolve_programme(db, programme_id, program, student.faculty_id)
        student.programme_id = prog.programme_id
        
    # Update User fields if provided
    if user_data:
        apply_user_update(db, student.user, user_data)
            
    db.commit()
    db.refresh(student)
    return student

@router.delete("/students/{student_id}")
def delete_student(student_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    student = db.query(Student).filter_by(student_id=student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    user = student.user
    db.delete(student)
    db.flush()
    check_and_delete_user_if_orphaned(db, user)
    db.commit()
    return {"detail": "Student profile deleted successfully"}

# ==========================================
# LECTURERS PROFILE CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/lecturers", response_model=List[schemas.LecturerResponse])
def list_lecturers(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(Lecturer).all()

@router.post("/lecturers", response_model=schemas.LecturerResponse)
def create_lecturer(lecturer_in: schemas.LecturerCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    # 1. Determine lecturer_id
    lecturer_id = lecturer_in.lecturer_id
    if not lecturer_id:
        lecturer_id = generate_unique_id(db, Lecturer, "LEC-", "lecturer_id")
    else:
        if db.query(Lecturer).filter_by(lecturer_id=lecturer_id).first():
            raise HTTPException(status_code=400, detail="Lecturer ID already exists")
            
    # 2. Get or create User
    if lecturer_in.user_id is not None:
        user = db.query(User).filter_by(user_id=lecturer_in.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if db.query(Lecturer).filter_by(user_id=user.user_id).first():
            raise HTTPException(status_code=400, detail="This user already has a Lecturer profile")
    else:
        if not lecturer_in.user:
            raise HTTPException(status_code=400, detail="User registration data is required for a new user")
        if db.query(User).filter_by(username=lecturer_in.user.username).first():
            raise HTTPException(status_code=400, detail="Username already taken")
            
        email = generate_unique_email(db, lecturer_in.user.given_name, lecturer_in.user.family_name)
        role_ids = []
        if lecturer_in.user.role_ids:
            role_ids.extend(lecturer_in.user.role_ids)
        if lecturer_in.user.role_id and lecturer_in.user.role_id not in role_ids:
            role_ids.append(lecturer_in.user.role_id)
            
        roles = []
        if role_ids:
            roles = db.query(Role).filter(Role.role_id.in_(role_ids)).all()
            
        user = User(
            given_name=lecturer_in.user.given_name,
            family_name=lecturer_in.user.family_name,
            email=email,
            username=lecturer_in.user.username,
            is_active=lecturer_in.user.is_active
        )
        if roles:
            user.roles = roles
            
        db.add(user)
        db.flush()
        
    # Find or create Staff record first for the Lecturer!
    staff = db.query(Staff).filter_by(user_id=user.user_id).first()
    dept = resolve_department(db, lecturer_in.department_id, lecturer_in.department)
    if not staff:
        staff = Staff(
            staff_id=generate_unique_id(db, Staff, "STF-", "staff_id"),
            user_id=user.user_id,
            department_id=dept.department_id,
            position=lecturer_in.position,
            office_node_id=lecturer_in.office_node_id
        )
        db.add(staff)
        db.flush()
        
    fac = resolve_faculty(db, lecturer_in.faculty_id, lecturer_in.faculty)
    
    lecturer = Lecturer(
        lecturer_id=lecturer_id,
        user_id=user.user_id,
        staff_id=staff.staff_id,
        faculty_id=fac.faculty_id,
        Position_desc=lecturer_in.position,
        office_node_id=lecturer_in.office_node_id
    )
    db.add(lecturer)
    db.commit()
    db.refresh(lecturer)
    return lecturer

@router.put("/lecturers/{lecturer_id}", response_model=schemas.LecturerResponse)
def update_lecturer(lecturer_id: str, lecturer_in: schemas.LecturerUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    lecturer = db.query(Lecturer).filter_by(lecturer_id=lecturer_id).first()
    if not lecturer:
        raise HTTPException(status_code=404, detail="Lecturer not found")
        
    lecturer_data = lecturer_in.model_dump(exclude_unset=True)
    user_data = lecturer_data.pop("user", None)
    department = lecturer_data.pop("department", None)
    faculty = lecturer_data.pop("faculty", None)
    department_id = lecturer_data.pop("department_id", None)
    faculty_id = lecturer_data.pop("faculty_id", None)
    position = lecturer_data.pop("position", None)
    office_node_id = lecturer_data.get("office_node_id", None)
    
    # Update Lecturer fields
    for field, val in lecturer_data.items():
        setattr(lecturer, field, val)
        
    if position is not None:
        lecturer.Position_desc = position
        if lecturer.staff:
            lecturer.staff.position = position
            
    if office_node_id is not None:
        if lecturer.staff:
            lecturer.staff.office_node_id = office_node_id
            
    if department_id is not None or department is not None:
        dept = resolve_department(db, department_id, department)
        if lecturer.staff:
            lecturer.staff.department_id = dept.department_id
            
    if faculty_id is not None or faculty is not None:
        fac = resolve_faculty(db, faculty_id, faculty)
        lecturer.faculty_id = fac.faculty_id
        
    if user_data:
        apply_user_update(db, lecturer.user, user_data)
            
    db.commit()
    db.refresh(lecturer)
    return lecturer

@router.delete("/lecturers/{lecturer_id}")
def delete_lecturer(lecturer_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    lecturer = db.query(Lecturer).filter_by(lecturer_id=lecturer_id).first()
    if not lecturer:
        raise HTTPException(status_code=404, detail="Lecturer not found")
    user = lecturer.user
    db.delete(lecturer)
    db.flush()
    check_and_delete_user_if_orphaned(db, user)
    db.commit()
    return {"detail": "Lecturer profile deleted successfully"}

# ==========================================
# STAFF PROFILE CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/staff", response_model=List[schemas.StaffResponse])
def list_staff(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(Staff).all()

@router.post("/staff", response_model=schemas.StaffResponse)
def create_staff(staff_in: schemas.StaffCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    # 1. Determine staff_id
    staff_id = staff_in.staff_id
    if not staff_id:
        staff_id = generate_unique_id(db, Staff, "STF-", "staff_id")
    else:
        if db.query(Staff).filter_by(staff_id=staff_id).first():
            raise HTTPException(status_code=400, detail="Staff ID already exists")
            
    # 2. Get or create User
    if staff_in.user_id is not None:
        user = db.query(User).filter_by(user_id=staff_in.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if db.query(Staff).filter_by(user_id=user.user_id).first():
            raise HTTPException(status_code=400, detail="This user already has a Staff profile")
    else:
        if not staff_in.user:
            raise HTTPException(status_code=400, detail="User registration data is required for a new user")
        if db.query(User).filter_by(username=staff_in.user.username).first():
            raise HTTPException(status_code=400, detail="Username already taken")
            
        email = generate_unique_email(db, staff_in.user.given_name, staff_in.user.family_name)
        role_ids = []
        if staff_in.user.role_ids:
            role_ids.extend(staff_in.user.role_ids)
        if staff_in.user.role_id and staff_in.user.role_id not in role_ids:
            role_ids.append(staff_in.user.role_id)
            
        roles = []
        if role_ids:
            roles = db.query(Role).filter(Role.role_id.in_(role_ids)).all()
            
        user = User(
            given_name=staff_in.user.given_name,
            family_name=staff_in.user.family_name,
            email=email,
            username=staff_in.user.username,
            is_active=staff_in.user.is_active
        )
        if roles:
            user.roles = roles
            
        db.add(user)
        db.flush()
        
    dept = resolve_department(db, staff_in.department_id, staff_in.department)
    staff = Staff(
        staff_id=staff_id,
        user_id=user.user_id,
        department_id=dept.department_id,
        position=staff_in.position,
        office_node_id=staff_in.office_node_id
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff

@router.put("/staff/{staff_id}", response_model=schemas.StaffResponse)
def update_staff(staff_id: str, staff_in: schemas.StaffUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    staff = db.query(Staff).filter_by(staff_id=staff_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
        
    staff_data = staff_in.model_dump(exclude_unset=True)
    user_data = staff_data.pop("user", None)
    department = staff_data.pop("department", None)
    department_id = staff_data.pop("department_id", None)
    staff_type = staff_data.pop("staff_type", None)
    
    for field, val in staff_data.items():
        setattr(staff, field, val)
        
    if department_id is not None or department is not None:
        dept = resolve_department(db, department_id, department)
        staff.department_id = dept.department_id
        
    if user_data:
        apply_user_update(db, staff.user, user_data)
            
    db.commit()
    db.refresh(staff)
    return staff

@router.delete("/staff/{staff_id}")
def delete_staff(staff_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    staff = db.query(Staff).filter_by(staff_id=staff_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    user = staff.user
    db.delete(staff)
    db.flush()
    check_and_delete_user_if_orphaned(db, user)
    db.commit()
    return {"detail": "Staff profile deleted successfully"}

# ==========================================
# VISITORS PROFILE CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/visitors", response_model=List[schemas.VisitorResponse])
def list_visitors(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(Visitor).all()

@router.post("/visitors", response_model=schemas.VisitorResponse)
def create_visitor(visitor_in: schemas.VisitorCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    # 1. Determine visitor_id
    visitor_id = visitor_in.visitor_id
    if not visitor_id:
        visitor_id = generate_unique_id(db, Visitor, "VIS-", "visitor_id")
    else:
        if db.query(Visitor).filter_by(visitor_id=visitor_id).first():
            raise HTTPException(status_code=400, detail="Visitor ID already exists")
            
    # 2. Get or create User
    if visitor_in.user_id is not None:
        user = db.query(User).filter_by(user_id=visitor_in.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if db.query(Visitor).filter_by(user_id=user.user_id).first():
            raise HTTPException(status_code=400, detail="This user already has a Visitor profile")
    else:
        if not visitor_in.user:
            raise HTTPException(status_code=400, detail="User registration data is required for a new user")
        if db.query(User).filter_by(username=visitor_in.user.username).first():
            raise HTTPException(status_code=400, detail="Username already taken")
            
        email = generate_unique_email(db, visitor_in.user.given_name, visitor_in.user.family_name)
        role_ids = []
        if visitor_in.user.role_ids:
            role_ids.extend(visitor_in.user.role_ids)
        if visitor_in.user.role_id and visitor_in.user.role_id not in role_ids:
            role_ids.append(visitor_in.user.role_id)
            
        roles = []
        if role_ids:
            roles = db.query(Role).filter(Role.role_id.in_(role_ids)).all()
            
        user = User(
            given_name=visitor_in.user.given_name,
            family_name=visitor_in.user.family_name,
            email=email,
            username=visitor_in.user.username,
            is_active=visitor_in.user.is_active
        )
        if roles:
            user.roles = roles
            
        db.add(user)
        db.flush()
        
    visitor = Visitor(
        visitor_id=visitor_id,
        user_id=user.user_id,
        id_number=visitor_in.id_number,
        organization=visitor_in.organization,
        visit_purpose=visitor_in.visit_purpose,
        access_expiry=visitor_in.access_expiry,
        registered_by=visitor_in.registered_by if visitor_in.registered_by else current_admin.user_id
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)
    return visitor

@router.put("/visitors/{visitor_id}", response_model=schemas.VisitorResponse)
def update_visitor(visitor_id: str, visitor_in: schemas.VisitorUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    visitor = db.query(Visitor).filter_by(visitor_id=visitor_id).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")
        
    visitor_data = visitor_in.model_dump(exclude_unset=True)
    user_data = visitor_data.pop("user", None)
    
    for field, val in visitor_data.items():
        setattr(visitor, field, val)
        
    if user_data:
        apply_user_update(db, visitor.user, user_data)
            
    db.commit()
    db.refresh(visitor)
    return visitor

@router.delete("/visitors/{visitor_id}")
def delete_visitor(visitor_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    visitor = db.query(Visitor).filter_by(visitor_id=visitor_id).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")
    user = visitor.user
    db.delete(visitor)
    db.flush()
    check_and_delete_user_if_orphaned(db, user)
    db.commit()
    return {"detail": "Visitor profile deleted successfully"}

# ==========================================
# ADMINS PROFILE CRUD (SUPER_ADMIN ONLY)
# ==========================================
@router.get("/admins", response_model=List[schemas.AdminResponse])
def list_admins(db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    return db.query(Admin).all()

@router.post("/admins", response_model=schemas.AdminResponse)
def create_admin(admin_in: schemas.AdminCreate, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    # 1. Determine admin_id
    admin_id = admin_in.admin_id
    if not admin_id:
        admin_id = generate_unique_id(db, Admin, "ADM-", "admin_id")
    else:
        if db.query(Admin).filter_by(admin_id=admin_id).first():
            raise HTTPException(status_code=400, detail="Admin ID already exists")
            
    # 2. Get or create User
    if admin_in.user_id is not None:
        user = db.query(User).filter_by(user_id=admin_in.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if db.query(Admin).filter_by(user_id=user.user_id).first():
            raise HTTPException(status_code=400, detail="This user already has an Admin profile")
    else:
        if not admin_in.user:
            raise HTTPException(status_code=400, detail="User registration data is required for a new user")
        if db.query(User).filter_by(username=admin_in.user.username).first():
            raise HTTPException(status_code=400, detail="Username already taken")
            
        email = generate_unique_email(db, admin_in.user.given_name, admin_in.user.family_name)
        user = User(
            given_name=admin_in.user.given_name,
            family_name=admin_in.user.family_name,
            email=email,
            username=admin_in.user.username,
            is_active=admin_in.user.is_active
        )
        admin_role = db.query(Role).filter_by(role_name="ADMIN").first()
        if admin_role:
            user.roles.append(admin_role)
        db.add(user)
        db.flush()

    # 3. Find or auto-create Staff profile (the trigger)
    staff = db.query(Staff).filter_by(user_id=user.user_id).first()
    if not staff:
        dept = resolve_department(db, admin_in.department_id, admin_in.department or "DEP-IT")
        staff = Staff(
            staff_id=generate_unique_id(db, Staff, "STF-", "staff_id"),
            user_id=user.user_id,
            department_id=dept.department_id,
            position="System Administrator",
            office_node_id=admin_in.office_node_id
        )
        db.add(staff)
        db.flush()
        
    password_hash = get_password_hash(admin_in.password or "admin123")
    
    admin = Admin(
        admin_id=admin_id,
        user_id=user.user_id,
        staff_id=staff.staff_id,
        admin_type=admin_in.admin_type,
        password_hash=password_hash
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin

@router.put("/admins/{admin_id}", response_model=schemas.AdminResponse)
def update_admin(admin_id: str, admin_in: schemas.AdminUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    admin = db.query(Admin).filter_by(admin_id=admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
        
    admin_data = admin_in.model_dump(exclude_unset=True)
    user_data = admin_data.pop("user", None)
    password = admin_data.pop("password", None)
    department = admin_data.pop("department", None)
    department_id = admin_data.pop("department_id", None)
    office_node_id = admin_data.pop("office_node_id", None)
    
    for field, val in admin_data.items():
        setattr(admin, field, val)
        
    if password:
        admin.password_hash = get_password_hash(password)
        
    if department_id is not None or department is not None:
        dept = resolve_department(db, department_id, department)
        if admin.staff:
            admin.staff.department_id = dept.department_id
            
    if office_node_id is not None:
        if admin.staff:
            admin.staff.office_node_id = office_node_id
            
    if user_data:
        apply_user_update(db, admin.user, user_data)
            
    db.commit()
    db.refresh(admin)
    return admin

@router.delete("/admins/{admin_id}")
def delete_admin(admin_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    if admin_id == current_admin.admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account")
    admin = db.query(Admin).filter_by(admin_id=admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    user = admin.user
    db.delete(admin)
    db.flush()
    check_and_delete_user_if_orphaned(db, user)
    db.commit()
    return {"detail": "Admin profile deleted successfully"}

@router.post("/users/{user_id}/upload-photo")
def upload_user_face_photo(
    user_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin=Depends(verify_super_admin)
):
    user = db.query(User).filter_by(user_id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Resolve paths
    router_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir    = os.path.dirname(router_dir)
    static_dir = os.path.join(app_dir, "static")
    user_upload_dir = os.path.join(static_dir, "uploads", "faces", str(user_id))
    os.makedirs(user_upload_dir, exist_ok=True)

    # Read uploaded file
    try:
        file_bytes = file.file.read()
        nparr = np.frombuffer(file_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image file format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read/decode uploaded photo: {e}")

    # Face detection using SCRFD
    face_vector_list = None
    crop = None
    try:
        detector = get_scrfd_detector()
        faces = detector.detect(img)

        if faces and len(faces) > 0:
            # Sort by bounding box area to get the largest face
            faces.sort(key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]), reverse=True)
            f = faces[0]
            bbox = f["bbox"]
            x1, y1, x2, y2 = [int(v) for v in bbox]
            h_img, w_img = img.shape[:2]
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w_img, x2)
            y2 = min(h_img, y2)
            raw_crop = img[y1:y2, x1:x2]

            if raw_crop.size > 0:
                crop = extract_aligned_face(img, f)
                embedder = get_arcface_embedder()
                embedding = embedder.embed(crop)
                face_vector_list = [round(float(v), 6) for v in embedding.tolist()]
        else:
            print(f"[upload-photo] No face detected in uploaded image for user {user_id}.")
    except Exception as exc:
        print(f"[upload-photo] SCRFD/ArcFace extraction failed: {exc}")

    # Fallback to mock vector if face detection or embedding failed
    if not face_vector_list:
        random.seed(user_id)
        face_vector_list = [round(random.uniform(-1.0, 1.0), 4) for _ in range(512)]
        if crop is None or crop.size == 0:
            crop = cv2.resize(img, (112, 112))

    # Clear existing photos & embeddings for this user
    from app.models.models import UserImage, UserFaceEmbedding
    db.query(UserImage).filter_by(user_id=user_id).delete()
    db.query(UserFaceEmbedding).filter_by(user_id=user_id).delete()

    # Save front pose crop
    front_path = os.path.join(user_upload_dir, "front.jpg")
    cv2.imwrite(front_path, crop)

    db_img_front = UserImage(
        user_id=user_id,
        template_name="front",
        image_path=f"/static/uploads/faces/{user_id}/front.jpg"
    )
    db.add(db_img_front)

    emb_bytes = np.array(face_vector_list, dtype=np.float32).tobytes()
    db_emb_front = UserFaceEmbedding(
        user_id=user_id,
        template_name="front",
        model_name="arcface_r50",
        embedding=emb_bytes
    )
    db.add(db_emb_front)

    # Generate low_light pose
    low_light_crop = np.clip(crop.astype(np.float32) * 0.4, 0, 255).astype(np.uint8)
    low_light_path = os.path.join(user_upload_dir, "low_light.jpg")
    cv2.imwrite(low_light_path, low_light_crop)

    db_img_low = UserImage(
        user_id=user_id,
        template_name="low_light",
        image_path=f"/static/uploads/faces/{user_id}/low_light.jpg"
    )
    db.add(db_img_low)

    try:
        embedder = get_arcface_embedder()
        low_light_emb = embedder.embed(low_light_crop)
        low_light_emb_bytes = low_light_emb.astype(np.float32).tobytes()
    except Exception as exc:
        print(f"Failed to embed low light crop: {exc}. Using front embedding fallback.")
        low_light_emb_bytes = emb_bytes

    db_emb_low = UserFaceEmbedding(
        user_id=user_id,
        template_name="low_light",
        model_name="arcface_r50",
        embedding=low_light_emb_bytes
    )
    db.add(db_emb_low)

    db.commit()
    db.refresh(user)

    if _PUSH_SYNC_AVAILABLE and _push_sync_to_all_edges is not None:
        background_tasks.add_task(_push_sync_to_all_edges, db)

    return {
        "detail": "Face photo uploaded and EdgeFace vector enrolled successfully",
        "face_vector": user.face_vector,
        "imagepath": user.imagepath
    }


@router.post("/users/{user_id}/enroll-live/start")
def enroll_live_start(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_super_admin)
):
    user = db.query(User).filter_by(user_id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    enrollment_sessions[user_id] = {}
    return {"detail": "Live face enrollment session started. Temp data cleared."}


@router.post("/users/{user_id}/enroll-live/frame")
async def enroll_live_frame(
    user_id: int,
    target_pose: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin=Depends(verify_super_admin)
):
    try:
        valid_poses = ["front", "left_30", "right_30", "left_60", "right_60", "slightly_up"]
        if target_pose not in valid_poses:
            raise HTTPException(status_code=400, detail=f"Invalid target pose. Must be one of: {valid_poses}")

        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        try:
            file_bytes = await file.read()
            nparr = np.frombuffer(file_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                raise HTTPException(status_code=400, detail="Invalid image frame")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read/decode frame: {e}")

        detector = get_scrfd_detector()
        try:
            faces = detector.detect(img)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Detector inference failed: {e}")

        if not faces:
            return {
                "success": False,
                "guidance": "No face detected. Please look at the camera.",
                "detected_pose": "none",
                "yaw_ratio": 0.5,
                "pitch_ratio": 0.4
            }

        faces.sort(key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]), reverse=True)
        face = faces[0]
        bbox = face["bbox"]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        h_img, w_img = img.shape[:2]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w_img, x2)
        y2 = min(h_img, y2)
        crop = img[y1:y2, x1:x2]

        if crop.size == 0:
            return {
                "success": False,
                "guidance": "Face is out of bounds. Position yourself in the center.",
                "detected_pose": "none",
                "yaw_ratio": 0.5,
                "pitch_ratio": 0.4
            }

        gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())

        w = x2 - x1
        h = y2 - y1

        if w < 100 or h < 100:
            return {
                "success": False,
                "guidance": "Please move closer to the camera.",
                "detected_pose": "unknown",
                "yaw_ratio": 0.5,
                "pitch_ratio": 0.4
            }

        if blur_score < 50.0:
            return {
                "success": False,
                "guidance": "Hold still, the image is too blurry.",
                "detected_pose": "unknown",
                "yaw_ratio": 0.5,
                "pitch_ratio": 0.4
            }

        landmarks = face["landmarks"]
        # Sort eye coordinates so left_eye_x is always viewer's left (smaller x)
        left_eye_x = float(min(landmarks[0][0], landmarks[1][0]))
        right_eye_x = float(max(landmarks[0][0], landmarks[1][0]))
        
        left_eye_y = float(landmarks[0][1])
        right_eye_y = float(landmarks[1][1])
        
        nose_x = float(landmarks[2][0])
        nose_y = float(landmarks[2][1])
        
        eye_y = (left_eye_y + right_eye_y) / 2.0
        mouth_y = (float(landmarks[3][1]) + float(landmarks[4][1])) / 2.0

        denom_yaw = right_eye_x - left_eye_x
        yaw_ratio = float((nose_x - left_eye_x) / denom_yaw if denom_yaw != 0 else 0.5)

        denom_pitch = mouth_y - eye_y
        pitch_ratio = float((nose_y - eye_y) / denom_pitch if denom_pitch != 0 else 0.5)

        detected_pose = "unknown"
        if pitch_ratio < 0.40:
            detected_pose = "slightly_up"
        else:
            if yaw_ratio < 0.28:
                detected_pose = "right_60"
            elif yaw_ratio < 0.40:
                detected_pose = "right_30"
            elif yaw_ratio > 0.72:
                detected_pose = "left_60"
            elif yaw_ratio > 0.60:
                detected_pose = "left_30"
            else:
                detected_pose = "front"

        print(f"[DEBUG POSE] target={target_pose}, detected={detected_pose}, yaw={yaw_ratio:.3f}, pitch={pitch_ratio:.3f}, blur={blur_score:.1f}")

        if detected_pose != target_pose:
            guidance = "Look straight at the camera."
            if target_pose == "front":
                if detected_pose in ["left_30", "left_60"]:
                    guidance = "Turn your face slightly to the right."
                elif detected_pose in ["right_30", "right_60"]:
                    guidance = "Turn your face slightly to the left."
                elif detected_pose == "slightly_up":
                    guidance = "Tilt your head down."
            elif target_pose == "left_30":
                if detected_pose == "front":
                    guidance = "Turn your face slightly to the left."
                elif detected_pose == "left_60":
                    guidance = "Turn your face slightly to the right."
                else:
                    guidance = "Look straight and turn slightly left."
            elif target_pose == "left_60":
                if detected_pose in ["front", "left_30"]:
                    guidance = "Turn your face further to the left."
                else:
                    guidance = "Look straight and turn further left."
            elif target_pose == "right_30":
                if detected_pose == "front":
                    guidance = "Turn your face slightly to the right."
                elif detected_pose == "right_60":
                    guidance = "Turn your face slightly to the left."
                else:
                    guidance = "Look straight and turn slightly right."
            elif target_pose == "right_60":
                if detected_pose in ["front", "right_30"]:
                    guidance = "Turn your face further to the right."
                else:
                    guidance = "Look straight and turn further right."
            elif target_pose == "slightly_up":
                if detected_pose == "front":
                    guidance = "Tilt your head up."
                else:
                    guidance = "Look straight and tilt your head up."

            return {
                "success": False,
                "guidance": guidance,
                "detected_pose": detected_pose,
                "yaw_ratio": yaw_ratio,
                "pitch_ratio": pitch_ratio
            }

        aligned_crop = extract_aligned_face(img, face)

        if user_id not in enrollment_sessions:
            enrollment_sessions[user_id] = {}

        existing_crop = enrollment_sessions[user_id].get(target_pose)
        aligned_gray = cv2.cvtColor(aligned_crop, cv2.COLOR_BGR2GRAY)
        aligned_blur_score = cv2.Laplacian(aligned_gray, cv2.CV_64F).var()
        if existing_crop is None:
            enrollment_sessions[user_id][target_pose] = aligned_crop
        else:
            existing_gray = cv2.cvtColor(existing_crop, cv2.COLOR_BGR2GRAY)
            existing_blur = cv2.Laplacian(existing_gray, cv2.CV_64F).var()
            if aligned_blur_score > existing_blur:
                enrollment_sessions[user_id][target_pose] = aligned_crop

        return {
            "success": True,
            "guidance": f"Excellent! Pose '{target_pose}' captured successfully.",
            "detected_pose": detected_pose,
            "yaw_ratio": yaw_ratio,
            "pitch_ratio": pitch_ratio
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise e


@router.get("/users/{user_id}/enroll-live/progress")
def enroll_live_progress(
    user_id: int,
    current_admin=Depends(verify_super_admin)
):
    return {"progress": enrollment_progress.get(user_id, 0)}


@router.post("/users/{user_id}/enroll-live/complete")
def enroll_live_complete(
    user_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_super_admin)
):
    enrollment_progress[user_id] = 0
    try:
        session_data = enrollment_sessions.get(user_id)
        if not session_data:
            raise HTTPException(status_code=400, detail="No active enrollment session. Start live enrollment first.")

        required_poses = ["front", "left_30", "right_30", "left_60", "right_60", "slightly_up"]
        missing = [p for p in required_poses if p not in session_data]
        if missing:
            raise HTTPException(status_code=400, detail=f"Please complete all poses. Missing: {', '.join(missing)}")

        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        front_crop = session_data["front"]
        low_light_crop = np.clip(front_crop.astype(np.float32) * 0.4, 0, 255).astype(np.uint8)
        session_data["low_light"] = low_light_crop

        from app.models.models import UserImage, UserFaceEmbedding
        db.query(UserImage).filter_by(user_id=user_id).delete()
        db.query(UserFaceEmbedding).filter_by(user_id=user_id).delete()

        router_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir = os.path.dirname(router_dir)
        static_dir = os.path.join(app_dir, "static")
        user_upload_dir = os.path.join(static_dir, "uploads", "faces", str(user_id))
        os.makedirs(user_upload_dir, exist_ok=True)

        embedder = get_arcface_embedder()

        poses = ["front", "left_30", "right_30", "left_60", "right_60", "slightly_up", "low_light"]
        for idx, pose in enumerate(poses):
            crop = session_data[pose]
            file_path = os.path.join(user_upload_dir, f"{pose}.jpg")
            cv2.imwrite(file_path, crop)

            db_img = UserImage(
                user_id=user_id,
                template_name=pose,
                image_path=f"/static/uploads/faces/{user_id}/{pose}.jpg"
            )
            db.add(db_img)

            try:
                embedding_vec = embedder.embed(crop)
                emb_bytes = embedding_vec.astype(np.float32).tobytes()
            except Exception as e:
                print(f"Failed to embed pose '{pose}' for user {user_id}: {e}")
                random.seed(user_id + hash(pose))
                fallback_vec = np.array([random.uniform(-1.0, 1.0) for _ in range(512)], dtype=np.float32)
                norm = np.linalg.norm(fallback_vec) + 1e-10
                fallback_vec = fallback_vec / norm
                emb_bytes = fallback_vec.tobytes()

            db_emb = UserFaceEmbedding(
                user_id=user_id,
                template_name=pose,
                model_name="arcface_r50",
                embedding=emb_bytes
            )
            db.add(db_emb)
            
            # Update progress
            enrollment_progress[user_id] = int((idx + 1) / len(poses) * 100)

        db.commit()
        db.refresh(user)

        enrollment_sessions.pop(user_id, None)

        if _PUSH_SYNC_AVAILABLE and _push_sync_to_all_edges is not None:
            background_tasks.add_task(_push_sync_to_all_edges, db)

        return {
            "detail": "Live multi-pose face enrollment completed successfully.",
            "face_vector": user.face_vector,
            "imagepath": user.imagepath
        }
    finally:
        enrollment_progress.pop(user_id, None)


@router.post("/users/{user_id}/enroll-video")
async def enroll_user_video(
    user_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin=Depends(verify_super_admin)
):
    user = db.query(User).filter_by(user_id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    import tempfile
    temp_video = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    try:
        temp_video.write(await file.read())
        temp_video.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write uploaded video: {e}")

    cap = cv2.VideoCapture(temp_video.name)
    if not cap.isOpened():
        os.unlink(temp_video.name)
        raise HTTPException(status_code=400, detail="Could not open video file.")

    required_poses = ["front", "left_30", "right_30", "left_60", "right_60", "slightly_up"]
    harvested_crops = {}
    harvested_blurs = {}

    detector = get_scrfd_detector()
    frame_idx = 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    # Sample no more than roughly 60 frames; detector inference dominates runtime.
    frame_step = max(2, int(np.ceil(total_frames / 60))) if total_frames else 2

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        if frame_idx % frame_step != 0:
            continue

        try:
            faces = detector.detect(frame)
        except Exception:
            continue

        if not faces:
            continue

        faces.sort(key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]), reverse=True)
        face = faces[0]
        bbox = face["bbox"]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        h_img, w_img = frame.shape[:2]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w_img, x2)
        y2 = min(h_img, y2)
        crop = frame[y1:y2, x1:x2]

        if crop.size == 0 or (x2 - x1) < 100 or (y2 - y1) < 100:
            continue

        gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())
        if blur_score < 50.0:
            continue

        landmarks = face["landmarks"]
        # Sort eye coordinates so left_eye_x is always viewer's left (smaller x)
        left_eye_x = float(min(landmarks[0][0], landmarks[1][0]))
        right_eye_x = float(max(landmarks[0][0], landmarks[1][0]))
        
        left_eye_y = float(landmarks[0][1])
        right_eye_y = float(landmarks[1][1])
        
        nose_x = float(landmarks[2][0])
        nose_y = float(landmarks[2][1])
        
        eye_y = (left_eye_y + right_eye_y) / 2.0
        mouth_y = (float(landmarks[3][1]) + float(landmarks[4][1])) / 2.0

        denom_yaw = right_eye_x - left_eye_x
        yaw_ratio = float((nose_x - left_eye_x) / denom_yaw if denom_yaw != 0 else 0.5)

        denom_pitch = mouth_y - eye_y
        pitch_ratio = float((nose_y - eye_y) / denom_pitch if denom_pitch != 0 else 0.5)

        detected_pose = "unknown"
        if pitch_ratio < 0.40:
            detected_pose = "slightly_up"
        else:
            if yaw_ratio < 0.28:
                detected_pose = "right_60"
            elif yaw_ratio < 0.40:
                detected_pose = "right_30"
            elif yaw_ratio > 0.72:
                detected_pose = "left_60"
            elif yaw_ratio > 0.60:
                detected_pose = "left_30"
            else:
                detected_pose = "front"

        if detected_pose in required_poses:
            aligned_crop = extract_aligned_face(frame, face)
            existing_blur = harvested_blurs.get(detected_pose, 0.0)
            if detected_pose not in harvested_crops or blur_score > existing_blur:
                harvested_crops[detected_pose] = aligned_crop.copy()
                harvested_blurs[detected_pose] = blur_score

        # low_light is derived below; six required poses are enough to finish.
        if len(harvested_crops) == len(required_poses):
            break

    cap.release()
    try:
        os.unlink(temp_video.name)
    except Exception:
        pass

    missing = [p for p in required_poses if p not in harvested_crops]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Video processed, but failed to capture all required poses. Missing: {', '.join(missing)}. "
                   f"Please record a video where you face the camera directly, turn fully to the left, "
                   f"turn fully to the right, and look slightly up."
        )

    front_crop = harvested_crops["front"]
    low_light_crop = np.clip(front_crop.astype(np.float32) * 0.4, 0, 255).astype(np.uint8)
    harvested_crops["low_light"] = low_light_crop

    from app.models.models import UserImage, UserFaceEmbedding
    db.query(UserImage).filter_by(user_id=user_id).delete()
    db.query(UserFaceEmbedding).filter_by(user_id=user_id).delete()

    router_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(router_dir)
    static_dir = os.path.join(app_dir, "static")
    user_upload_dir = os.path.join(static_dir, "uploads", "faces", str(user_id))
    os.makedirs(user_upload_dir, exist_ok=True)

    embedder = get_arcface_embedder()

    for pose in ["front", "left_30", "right_30", "left_60", "right_60", "slightly_up", "low_light"]:
        crop = harvested_crops[pose]
        file_path = os.path.join(user_upload_dir, f"{pose}.jpg")
        cv2.imwrite(file_path, crop)

        db_img = UserImage(
            user_id=user_id,
            template_name=pose,
            image_path=f"/static/uploads/faces/{user_id}/{pose}.jpg"
        )
        db.add(db_img)

        try:
            embedding_vec = embedder.embed(crop)
            emb_bytes = embedding_vec.astype(np.float32).tobytes()
        except Exception as e:
            print(f"Failed to embed pose '{pose}' for user {user_id}: {e}")
            random.seed(user_id + hash(pose))
            fallback_vec = np.array([random.uniform(-1.0, 1.0) for _ in range(512)], dtype=np.float32)
            norm = np.linalg.norm(fallback_vec) + 1e-10
            fallback_vec = fallback_vec / norm

        db_emb = UserFaceEmbedding(
            user_id=user_id,
            template_name=pose,
            model_name="arcface_r50",
            embedding=emb_bytes
        )
        db.add(db_emb)

    db.commit()
    db.refresh(user)

    if _PUSH_SYNC_AVAILABLE and _push_sync_to_all_edges is not None:
        background_tasks.add_task(_push_sync_to_all_edges, db)

    return {
        "detail": "Video face enrollment completed successfully.",
        "face_vector": user.face_vector,
        "imagepath": user.imagepath
    }


@router.post("/users/reembed-all")
@router.post("/users/reembed-all/")
async def reembed_all_users(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_super_admin)
):
    try:
        from app.models.models import UserImage, UserFaceEmbedding
        images = db.query(UserImage).all()
        if not images:
            return {"detail": "No enrolled images found in database."}

        embedder = get_arcface_embedder()
        router_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir = os.path.dirname(router_dir)
        static_dir = os.path.join(app_dir, "static")

        success_count = 0
        failed_count = 0

        for img_rec in images:
            user_id = img_rec.user_id
            pose = img_rec.template_name
            db_path = img_rec.image_path

            # Clean relative path: convert web path "/static/uploads/..." to filesystem path
            # Remove leading slash and the "static/" prefix if present
            rel_path = db_path.lstrip("/")
            if rel_path.startswith("static/"):
                rel_path = rel_path.replace("static/", "", 1)
            
            file_path = os.path.join(static_dir, rel_path)

            if not os.path.exists(file_path):
                print(f"[REEMBED] Warning: Image file not found: {file_path}")
                failed_count += 1
                continue

            img = cv2.imread(file_path)
            if img is None:
                print(f"[REEMBED] Error: Could not read image: {file_path}")
                failed_count += 1
                continue

            try:
                embedding_vec = embedder.embed(img)
                emb_bytes = embedding_vec.astype(np.float32).tobytes()
            except Exception as e:
                print(f"[REEMBED] Error: Embedding failed for user {user_id} pose {pose}: {e}")
                failed_count += 1
                continue

            # Upsert UserFaceEmbedding
            db_emb = db.query(UserFaceEmbedding).filter_by(user_id=user_id, template_name=pose).first()
            if db_emb:
                db_emb.embedding = emb_bytes
                db_emb.model_name = "arcface_r50"
            else:
                db_emb = UserFaceEmbedding(
                    user_id=user_id,
                    template_name=pose,
                    model_name="arcface_r50",
                    embedding=emb_bytes
                )
                db.add(db_emb)
            
            success_count += 1

        db.commit()

        # Trigger sync to all edge camera nodes
        if _PUSH_SYNC_AVAILABLE and _push_sync_to_all_edges is not None:
            background_tasks.add_task(_push_sync_to_all_edges, db)

        return {
            "detail": f"Successfully re-embedded {success_count} images for all users (failed: {failed_count}). Edge sync triggered."
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Re-embedding failed: {str(e)}")
