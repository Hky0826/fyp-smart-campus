from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.core.security import verify_system_admin
from app.models.models import Building, Floorplan, Node, Edge, Faculty, Programme, Department, Staff, Student
from app.schemas import schemas

router = APIRouter(prefix="/refs", tags=["Structural Reference Tables"])

def check_staff_exists(db: Session, staff_id: str):
    staff = db.query(Staff).filter_by(staff_id=staff_id).first()
    if not staff:
        raise HTTPException(status_code=400, detail=f"Staff ID {staff_id} does not exist")

@router.get("/buildings", response_model=List[schemas.BuildingResponse])
def get_buildings(db: Session = Depends(get_db)):
    return db.query(Building).all()

@router.get("/floorplans", response_model=List[schemas.FloorplanResponse])
def get_floorplans(db: Session = Depends(get_db)):
    return db.query(Floorplan).all()

@router.get("/nodes", response_model=List[schemas.NodeResponse])
def get_nodes(db: Session = Depends(get_db)):
    return db.query(Node).all()

@router.get("/edges", response_model=List[schemas.EdgeResponse])
def get_edges(db: Session = Depends(get_db)):
    return db.query(Edge).all()

@router.get("/faculties", response_model=List[schemas.FacultyResponse])
def get_faculties(db: Session = Depends(get_db)):
    return db.query(Faculty).all()

@router.get("/programmes", response_model=List[schemas.ProgrammeResponse])
def get_programmes(db: Session = Depends(get_db)):
    return db.query(Programme).all()

@router.get("/departments", response_model=List[schemas.DepartmentResponse])
def get_departments(db: Session = Depends(get_db)):
    return db.query(Department).all()


# --- Faculty CRUD ---
@router.post("/faculties", response_model=schemas.FacultyResponse)
def create_faculty(faculty_in: schemas.FacultyCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    if db.query(Faculty).filter_by(faculty_id=faculty_in.faculty_id).first():
        raise HTTPException(status_code=400, detail="Faculty ID already exists")
    check_staff_exists(db, faculty_in.dean_id)
    
    faculty = Faculty(
        faculty_id=faculty_in.faculty_id,
        faculty_name=faculty_in.faculty_name,
        dean_id=faculty_in.dean_id
    )
    db.add(faculty)
    db.commit()
    db.refresh(faculty)
    return faculty

@router.put("/faculties/{faculty_id}", response_model=schemas.FacultyResponse)
def update_faculty(faculty_id: str, faculty_in: schemas.FacultyUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    faculty = db.query(Faculty).filter_by(faculty_id=faculty_id).first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty not found")
    
    if faculty_in.dean_id is not None:
        check_staff_exists(db, faculty_in.dean_id)
        faculty.dean_id = faculty_in.dean_id
    if faculty_in.faculty_name is not None:
        faculty.faculty_name = faculty_in.faculty_name
        
    db.commit()
    db.refresh(faculty)
    return faculty

@router.delete("/faculties/{faculty_id}")
def delete_faculty(faculty_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    faculty = db.query(Faculty).filter_by(faculty_id=faculty_id).first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty not found")
    
    prog_count = db.query(Programme).filter_by(faculty_id=faculty_id).count()
    if prog_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete faculty: {prog_count} program(s) are associated with it")
        
    db.delete(faculty)
    db.commit()
    return {"detail": "Faculty deleted successfully"}


# --- Department CRUD ---
@router.post("/departments", response_model=schemas.DepartmentResponse)
def create_department(dept_in: schemas.DepartmentCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    if db.query(Department).filter_by(department_id=dept_in.department_id).first():
        raise HTTPException(status_code=400, detail="Department ID already exists")
    check_staff_exists(db, dept_in.manager_id)
    
    dept = Department(
        department_id=dept_in.department_id,
        department_name=dept_in.department_name,
        manager_id=dept_in.manager_id
    )
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept

@router.put("/departments/{department_id}", response_model=schemas.DepartmentResponse)
def update_department(department_id: str, dept_in: schemas.DepartmentUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    dept = db.query(Department).filter_by(department_id=department_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
        
    if dept_in.manager_id is not None:
        check_staff_exists(db, dept_in.manager_id)
        dept.manager_id = dept_in.manager_id
    if dept_in.department_name is not None:
        dept.department_name = dept_in.department_name
        
    db.commit()
    db.refresh(dept)
    return dept

@router.delete("/departments/{department_id}")
def delete_department(department_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    dept = db.query(Department).filter_by(department_id=department_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
        
    staff_count = db.query(Staff).filter_by(department_id=department_id).count()
    if staff_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete department: {staff_count} staff member(s) are associated with it")
        
    db.delete(dept)
    db.commit()
    return {"detail": "Department deleted successfully"}


# --- Programme CRUD ---
@router.post("/programmes", response_model=schemas.ProgrammeResponse)
def create_programme(prog_in: schemas.ProgrammeCreate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    if db.query(Programme).filter_by(programme_id=prog_in.programme_id).first():
        raise HTTPException(status_code=400, detail="Programme ID already exists")
    check_staff_exists(db, prog_in.hop_id)
    fac = db.query(Faculty).filter_by(faculty_id=prog_in.faculty_id).first()
    if not fac:
        raise HTTPException(status_code=400, detail=f"Faculty ID {prog_in.faculty_id} does not exist")
        
    prog = Programme(
        programme_id=prog_in.programme_id,
        programme_name=prog_in.programme_name,
        faculty_id=prog_in.faculty_id,
        hop_id=prog_in.hop_id
    )
    db.add(prog)
    db.commit()
    db.refresh(prog)
    return prog

@router.put("/programmes/{programme_id}", response_model=schemas.ProgrammeResponse)
def update_programme(programme_id: str, prog_in: schemas.ProgrammeUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    prog = db.query(Programme).filter_by(programme_id=programme_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Programme not found")
        
    if prog_in.hop_id is not None:
        check_staff_exists(db, prog_in.hop_id)
        prog.hop_id = prog_in.hop_id
    if prog_in.faculty_id is not None:
        fac = db.query(Faculty).filter_by(faculty_id=prog_in.faculty_id).first()
        if not fac:
            raise HTTPException(status_code=400, detail=f"Faculty ID {prog_in.faculty_id} does not exist")
        prog.faculty_id = prog_in.faculty_id
    if prog_in.programme_name is not None:
        prog.programme_name = prog_in.programme_name
        
    db.commit()
    db.refresh(prog)
    return prog

@router.delete("/programmes/{programme_id}")
def delete_programme(programme_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    prog = db.query(Programme).filter_by(programme_id=programme_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Programme not found")
        
    student_count = db.query(Student).filter_by(programme_id=programme_id).count()
    if student_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete programme: {student_count} student(s) are associated with it")
        
    db.delete(prog)
    db.commit()
    return {"detail": "Programme deleted successfully"}
