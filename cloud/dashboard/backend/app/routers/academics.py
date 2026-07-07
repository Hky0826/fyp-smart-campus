from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, time

from app.core.database import get_db
from app.core.security import verify_system_admin
from app.models.models import Course, CourseEnrollment, Timetable, Appointment, Notification, User, Student, Lecturer, Staff, Node, Role
from app.schemas import schemas
from app.routers.iam import get_or_create_faculty, get_or_create_programme

router = APIRouter(prefix="/academics", tags=["Academic & Scheduling Operations"])

# ==========================================
# COURSE REGISTRY CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/courses", response_model=List[schemas.CourseResponse])
def list_courses(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(Course).all()

@router.post("/courses", response_model=schemas.CourseResponse)
def create_course(course_in: schemas.CourseCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    existing = db.query(Course).filter_by(course_code=course_in.course_code.upper()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Course code already registered")
        
    fac = get_or_create_faculty(db, course_in.faculty)
    prog = get_or_create_programme(db, course_in.department, fac.faculty_id)
    course = Course(
        course_code=course_in.course_code.upper(),
        course_name=course_in.course_name,
        credit_hours=course_in.credit_hours,
        programme_id=prog.programme_id,
        course_level=course_in.course_level,
        is_active=course_in.is_active
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course

@router.delete("/courses/{course_id}")
def delete_course(course_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    course = db.query(Course).filter_by(course_id=course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    # Verify course enrollments
    enroll_count = db.query(CourseEnrollment).filter_by(course_id=course_id).count()
    if enroll_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete course: {enroll_count} active enrollment(s) exist"
        )
    db.delete(course)
    db.commit()
    return {"detail": "Course deleted successfully"}

@router.put("/courses/{course_id}", response_model=schemas.CourseResponse)
def update_course(course_id: int, course_in: schemas.CourseUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    course = db.query(Course).filter_by(course_id=course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
        
    course_data = course_in.model_dump(exclude_unset=True)
    
    faculty_name = course_data.pop("faculty", None)
    dept_name = course_data.pop("department", None)
    
    if faculty_name is not None or dept_name is not None:
        current_fac_name = course.faculty
        current_dept_name = course.department
        
        fac_name = faculty_name if faculty_name is not None else current_fac_name
        dep_name = dept_name if dept_name is not None else current_dept_name
        
        fac = get_or_create_faculty(db, fac_name)
        prog = get_or_create_programme(db, dep_name, fac.faculty_id)
        course.programme_id = prog.programme_id
        
    for field, val in course_data.items():
        setattr(course, field, val)
        
    db.commit()
    db.refresh(course)
    return course

# ==========================================
# COURSE ENROLLMENTS CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/enrollments", response_model=List[schemas.CourseEnrollmentResponse])
def list_enrollments(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(CourseEnrollment).all()

@router.post("/enrollments", response_model=schemas.CourseEnrollmentResponse)
def enroll_student(enroll_in: schemas.CourseEnrollmentCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    # Verify student exists
    student = db.query(Student).filter_by(student_id=enroll_in.student_id).first()
    if not student:
        raise HTTPException(status_code=400, detail="Student does not exist")
        
    # Verify course exists
    course = db.query(Course).filter_by(course_id=enroll_in.course_id).first()
    if not course or not course.is_active:
        raise HTTPException(status_code=400, detail="Course does not exist or is inactive")
        
    # Check unique constraint
    existing = db.query(CourseEnrollment).filter_by(
        student_id=enroll_in.student_id,
        course_id=enroll_in.course_id,
        semester=enroll_in.semester
    ).first()
    if existing:
        raise HTTPException(
            status_code=400, 
            detail="Student is already enrolled in this course for the specified semester"
        )
        
    enrollment = CourseEnrollment(
        student_id=enroll_in.student_id,
        course_id=enroll_in.course_id,
        semester=enroll_in.semester,
        academic_year=enroll_in.academic_year,
        status=enroll_in.status
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment

@router.delete("/enrollments/{enrollment_id}")
def delete_enrollment(enrollment_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    enrollment = db.query(CourseEnrollment).filter_by(enrollment_id=enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    db.delete(enrollment)
    db.commit()
    return {"detail": "Enrollment deleted successfully"}

@router.put("/enrollments/{enrollment_id}", response_model=schemas.CourseEnrollmentResponse)
def update_enrollment(enrollment_id: int, enroll_in: schemas.CourseEnrollmentUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    enrollment = db.query(CourseEnrollment).filter_by(enrollment_id=enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
        
    if enroll_in.student_id is not None:
        student = db.query(Student).filter_by(student_id=enroll_in.student_id).first()
        if not student:
            raise HTTPException(status_code=400, detail="Student does not exist")
            
    if enroll_in.course_id is not None:
        course = db.query(Course).filter_by(course_id=enroll_in.course_id).first()
        if not course or not course.is_active:
            raise HTTPException(status_code=400, detail="Course does not exist or is inactive")
            
    student_id = enroll_in.student_id if enroll_in.student_id is not None else enrollment.student_id
    course_id = enroll_in.course_id if enroll_in.course_id is not None else enrollment.course_id
    semester = enroll_in.semester if enroll_in.semester is not None else enrollment.semester
    
    if student_id != enrollment.student_id or course_id != enrollment.course_id or semester != enrollment.semester:
        existing = db.query(CourseEnrollment).filter_by(
            student_id=student_id,
            course_id=course_id,
            semester=semester
        ).first()
        if existing and existing.enrollment_id != enrollment_id:
            raise HTTPException(
                status_code=400,
                detail="Student is already enrolled in this course for the specified semester"
            )
            
    for field, val in enroll_in.model_dump(exclude_unset=True).items():
        setattr(enrollment, field, val)
        
    db.commit()
    db.refresh(enrollment)
    return enrollment

# ==========================================
# TIMETABLES CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/timetables", response_model=List[schemas.TimetableResponse])
def list_timetables(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(Timetable).all()

@router.post("/timetables", response_model=schemas.TimetableResponse)
def create_timetable(time_in: schemas.TimetableCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    # 1. Verify foreign keys
    course = db.query(Course).filter_by(course_id=time_in.course_id).first()
    if not course:
        raise HTTPException(status_code=400, detail="Course not found")
    lecturer = db.query(Lecturer).filter_by(lecturer_id=time_in.lecturer_id).first()
    if not lecturer:
        raise HTTPException(status_code=400, detail="Lecturer not found")
    node = db.query(Node).filter_by(node_id=time_in.node_id).first()
    if not node:
        raise HTTPException(status_code=400, detail="Location Node not found")
        
    # 2. Check overlap safety check
    # Check if this classroom (node_id) is booked at an overlapping time on the same day in the same semester.
    # Overlap formula: start1 < end2 AND end1 > start2
    overlapping = db.query(Timetable).filter(
        Timetable.node_id == time_in.node_id,
        Timetable.day_of_week == time_in.day_of_week,
        Timetable.semester == time_in.semester,
        Timetable.start_time < time_in.end_time,
        Timetable.end_time > time_in.start_time
    ).first()
    
    if overlapping:
        raise HTTPException(
            status_code=400, 
            detail=f"Double-booking detected: Room is already occupied by Course ID {overlapping.course_id} on {time_in.day_of_week} between {overlapping.start_time} and {overlapping.end_time}"
        )
        
    timetable = Timetable(
        course_id=time_in.course_id,
        lecturer_id=time_in.lecturer_id,
        day_of_week=time_in.day_of_week,
        start_time=time_in.start_time,
        end_time=time_in.end_time,
        node_id=time_in.node_id,
        semester=time_in.semester,
        academic_year=time_in.academic_year
    )
    db.add(timetable)
    db.commit()
    db.refresh(timetable)
    return timetable

@router.delete("/timetables/{timetable_id}")
def delete_timetable(timetable_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    timetable = db.query(Timetable).filter_by(timetable_id=timetable_id).first()
    if not timetable:
        raise HTTPException(status_code=404, detail="Timetable slot not found")
    db.delete(timetable)
    db.commit()
    return {"detail": "Timetable slot deleted successfully"}

@router.put("/timetables/{timetable_id}", response_model=schemas.TimetableResponse)
def update_timetable(timetable_id: int, time_in: schemas.TimetableUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    timetable = db.query(Timetable).filter_by(timetable_id=timetable_id).first()
    if not timetable:
        raise HTTPException(status_code=404, detail="Timetable slot not found")
        
    if time_in.course_id is not None:
        course = db.query(Course).filter_by(course_id=time_in.course_id).first()
        if not course:
            raise HTTPException(status_code=400, detail="Course not found")
            
    if time_in.lecturer_id is not None:
        lecturer = db.query(Lecturer).filter_by(lecturer_id=time_in.lecturer_id).first()
        if not lecturer:
            raise HTTPException(status_code=400, detail="Lecturer not found")
            
    if time_in.node_id is not None:
        node = db.query(Node).filter_by(node_id=time_in.node_id).first()
        if not node:
            raise HTTPException(status_code=400, detail="Location Node not found")
            
    node_id = time_in.node_id if time_in.node_id is not None else timetable.node_id
    day_of_week = time_in.day_of_week if time_in.day_of_week is not None else timetable.day_of_week
    semester = time_in.semester if time_in.semester is not None else timetable.semester
    start_time = time_in.start_time if time_in.start_time is not None else timetable.start_time
    end_time = time_in.end_time if time_in.end_time is not None else timetable.end_time
    
    overlapping = db.query(Timetable).filter(
        Timetable.timetable_id != timetable_id,
        Timetable.node_id == node_id,
        Timetable.day_of_week == day_of_week,
        Timetable.semester == semester,
        Timetable.start_time < end_time,
        Timetable.end_time > start_time
    ).first()
    
    if overlapping:
        raise HTTPException(
            status_code=400,
            detail=f"Double-booking detected: Room is already occupied by Course ID {overlapping.course_id} on {day_of_week} between {overlapping.start_time} and {overlapping.end_time}"
        )
        
    for field, val in time_in.model_dump(exclude_unset=True).items():
        setattr(timetable, field, val)
        
    db.commit()
    db.refresh(timetable)
    return timetable

# ==========================================
# APPOINTMENTS CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/appointments", response_model=List[schemas.AppointmentResponse])
def list_appointments(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(Appointment).all()

@router.post("/appointments", response_model=schemas.AppointmentResponse)
def create_appointment(appt_in: schemas.AppointmentCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    # 1. Verify Guest (STUDENT or VISITOR)
    guest = db.query(User).filter_by(user_id=appt_in.guest_user_id).first()
    if not guest:
        raise HTTPException(status_code=400, detail="Guest user not found")
    # Verify role
    guest_role = guest.role.role_name
    if guest_role not in ["STUDENT", "VISITOR"]:
        raise HTTPException(status_code=400, detail=f"Invalid Guest: User has role {guest_role}, must be STUDENT or VISITOR")
        
    # 2. Verify Host (LECTURER or STAFF)
    host = db.query(User).filter_by(user_id=appt_in.host_user_id).first()
    if not host:
        raise HTTPException(status_code=400, detail="Host user not found")
    # Verify role
    host_role = host.role.role_name
    if host_role not in ["LECTURER", "STAFF", "ADMIN"]: # allow admin as host too
        raise HTTPException(status_code=400, detail=f"Invalid Host: User has role {host_role}, must be LECTURER or STAFF")
        
    # 3. Check Host double-booking (UNIQUE(host_user_id, scheduled_at))
    duplicate = db.query(Appointment).filter_by(
        host_user_id=appt_in.host_user_id,
        scheduled_at=appt_in.scheduled_at
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=400, 
            detail="Host is already booked at this exact scheduled date and time"
        )
        
    appt = Appointment(
        guest_user_id=appt_in.guest_user_id,
        host_user_id=appt_in.host_user_id,
        scheduled_at=appt_in.scheduled_at,
        duration_minutes=appt_in.duration_minutes,
        node_id=appt_in.node_id,
        status=appt_in.status,
        purpose=appt_in.purpose,
        host_email=appt_in.host_email or host.email
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    
    # 4. Auto-generate notification for the appointment host/guest
    notif = Notification(
        title="New Appointment Scheduled",
        body=f"You have a new appointment scheduled at {appt.scheduled_at} regarding: {appt.purpose or 'General Inquiry'}.",
        appointment_id=appt.appointment_id
    )
    db.add(notif)
    db.commit()
    
    return appt

@router.put("/appointments/{appointment_id}", response_model=schemas.AppointmentResponse)
def update_appointment(appointment_id: int, appt_in: schemas.AppointmentUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    appt = db.query(Appointment).filter_by(appointment_id=appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
        
    appt_data = appt_in.model_dump(exclude_unset=True)
    for field, val in appt_data.items():
        setattr(appt, field, val)
        
    db.commit()
    db.refresh(appt)
    return appt

@router.delete("/appointments/{appointment_id}")
def delete_appointment(appointment_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    appt = db.query(Appointment).filter_by(appointment_id=appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    db.delete(appt)
    db.commit()
    return {"detail": "Appointment deleted successfully"}

# ==========================================
# NOTIFICATIONS CRUD
# ==========================================
@router.get("/notifications", response_model=List[schemas.NotificationResponse])
def list_notifications(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(Notification).all()
