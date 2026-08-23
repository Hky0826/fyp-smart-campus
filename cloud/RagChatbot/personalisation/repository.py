"""Read-only ownership-filtered queries for chatbot personalisation."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from RagChatbot.personalisation.schemas import AuthenticatedChatContext, SafeAppointment, SafeCourse, SafeLocation, SafeProfile, SafeTimetableEntry


class PersonalDataRepository:
    """All methods scope through the trusted authenticated user context."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _location(node) -> SafeLocation:
        if node is None:
            return SafeLocation()
        floorplan = getattr(node, "floorplan", None)
        building = getattr(floorplan, "building", None)
        return SafeLocation(room=getattr(node, "room_label", None), building=getattr(building, "building_name", None), floor=getattr(floorplan, "floor_level", None))

    def profiles(self, context: AuthenticatedChatContext) -> list[SafeProfile]:
        from app.models.models import User
        user = self.db.query(User).filter_by(user_id=context.user_id, is_active=True).first()
        if not user:
            return []
        name = getattr(user, "full_name", "").strip() or f"{getattr(user, 'given_name', '')} {getattr(user, 'family_name', '')}".strip() or "User"
        profiles: list[SafeProfile] = []
        
        # 1. Student profile
        student = getattr(user, "student", None)
        if student or context.student_id or "STUDENT" in context.roles:
            prog = getattr(student, "program", None) or context.program
            fac = getattr(student, "faculty", None) or context.faculty
            profiles.append(SafeProfile(name=name, role="STUDENT", programme=prog, faculty=fac))
            
        # 2. Lecturer profile
        lecturer = getattr(user, "lecturer", None)
        if lecturer or context.lecturer_id or "LECTURER" in context.roles:
            fac = getattr(lecturer, "faculty", None) or context.faculty
            dept = getattr(lecturer, "department", None) or context.department
            pos = getattr(lecturer, "position", None) or getattr(lecturer, "Position_desc", None) or context.position_desc
            off = self._location(getattr(lecturer, "office", None)).display if lecturer else None
            profiles.append(SafeProfile(name=name, role="LECTURER", faculty=fac, department=dept, position=pos, office=off or None))
            
        # 3. Staff profile
        staff = getattr(user, "staff", None)
        if (staff or context.staff_id or "STAFF" in context.roles) and not lecturer:
            dept = getattr(staff, "department", None) or context.department
            pos = getattr(staff, "position", None) or getattr(staff, "Position_desc", None) or context.position_desc
            off = self._location(getattr(staff, "office", None)).display if staff else None
            profiles.append(SafeProfile(name=name, role="STAFF", department=dept, position=pos, office=off or None))
            
        # 4. Admin profile
        admin = getattr(user, "admin", None)
        if admin or context.admin_id or "ADMIN" in context.roles:
            adm_type = getattr(admin, "admin_type", None) or context.admin_type or "ADMINISTRATOR"
            profiles.append(SafeProfile(name=name, role="ADMINISTRATOR", position=adm_type))
            
        # 5. Visitor profile
        visitor = getattr(user, "visitor", None)
        if visitor or context.visitor_id or "VISITOR" in context.roles:
            if not visitor or not self._visitor_expired(getattr(visitor, "access_expiry", None)):
                org = getattr(visitor, "organization", None) or context.organization
                profiles.append(SafeProfile(name=name, role="VISITOR", department=org))
                
        if not profiles:
            role_name = context.roles[0] if context.roles else "USER"
            profiles.append(SafeProfile(name=name, role=role_name))
        return profiles

    def profile(self, context: AuthenticatedChatContext) -> Optional[SafeProfile]:
        """Backward-compatible primary profile accessor."""
        profiles = self.profiles(context)
        return profiles[0] if profiles else None

    def courses(self, context: AuthenticatedChatContext, term: Optional[tuple[int, str]] = None) -> list[SafeCourse]:
        from app.models.models import Course, CourseEnrollment, Student
        base_query = (self.db.query(CourseEnrollment)
            .join(Course, Course.course_id == CourseEnrollment.course_id)
            .join(Student, Student.student_id == CourseEnrollment.student_id)
            .options(joinedload(CourseEnrollment.course))
            .filter(
                Student.user_id == context.user_id,
                CourseEnrollment.status == "ENROLLED",
                Course.is_active.is_(True),
            ))

        rows = []
        if term is not None:
            rows = base_query.filter(
                CourseEnrollment.semester == term[0],
                CourseEnrollment.academic_year == term[1],
            ).all()

        # Course enrolments use a compound semester value in this project
        # (for example, 202607), while older configuration may contain a
        # simple semester number such as 1. If the configured term has no
        # rows, use the user's latest enrolled term instead of returning a
        # misleading empty result.
        if not rows:
            all_rows = base_query.order_by(
                CourseEnrollment.semester.desc(),
                CourseEnrollment.academic_year.desc(),
                Course.course_code,
            ).all()
            if all_rows:
                latest_term = (all_rows[0].semester, all_rows[0].academic_year)
                rows = [row for row in all_rows if (row.semester, row.academic_year) == latest_term]

        seen_course_ids = set()
        courses = []
        for row in rows:
            if row.course_id in seen_course_ids:
                continue
            seen_course_ids.add(row.course_id)
            courses.append(SafeCourse(code=row.course.course_code, name=row.course.course_name, credits=getattr(row.course, "credit_hours", None)))
        return courses

    def student_timetable(self, context: AuthenticatedChatContext, term: Optional[tuple[int, str]] = None) -> list[SafeTimetableEntry]:
        from app.models.models import Course, CourseEnrollment, Student, Timetable, Node, Floorplan
        base_query = (self.db.query(Timetable)
            .join(Course, Course.course_id == Timetable.course_id)
            .join(CourseEnrollment, CourseEnrollment.course_id == Timetable.course_id)
            .join(Student, Student.student_id == CourseEnrollment.student_id)
            .options(joinedload(Timetable.course), joinedload(Timetable.classroom).joinedload(Node.floorplan).joinedload(Floorplan.building))
            .filter(Student.user_id == context.user_id, CourseEnrollment.status == "ENROLLED", Course.is_active.is_(True))
            .distinct())
        rows = []
        if term is not None:
            rows = base_query.filter(
                CourseEnrollment.semester == term[0],
                CourseEnrollment.academic_year == term[1],
                Timetable.semester == term[0],
                Timetable.academic_year == term[1],
            ).order_by(Timetable.day_of_week, Timetable.start_time).all()
        if not rows:
            # The configured semester may use the legacy value ``1`` while
            # timetable rows use a compound live value such as ``202607``.
            # Resolve the latest term owned by this student instead of
            # discarding an otherwise authorized timetable.
            all_rows = base_query.order_by(
                Timetable.semester.desc(), Timetable.academic_year.desc(),
                Timetable.day_of_week, Timetable.start_time,
            ).all()
            if all_rows:
                latest_term = (all_rows[0].semester, all_rows[0].academic_year)
                rows = [row for row in all_rows if (row.semester, row.academic_year) == latest_term]
        return [self._timetable_dto(row) for row in rows]

    def lecturer_timetable(self, context: AuthenticatedChatContext, term: Optional[tuple[int, str]] = None) -> list[SafeTimetableEntry]:
        from app.models.models import Course, Lecturer, Timetable, Node, Floorplan
        base_query = (self.db.query(Timetable)
            .join(Lecturer, Lecturer.lecturer_id == Timetable.lecturer_id)
            .join(Course, Course.course_id == Timetable.course_id)
            .options(joinedload(Timetable.course), joinedload(Timetable.classroom).joinedload(Node.floorplan).joinedload(Floorplan.building))
            .filter(Lecturer.user_id == context.user_id, Course.is_active.is_(True)))
        rows = []
        if term is not None:
            rows = base_query.filter(
                Timetable.semester == term[0],
                Timetable.academic_year == term[1],
            ).order_by(Timetable.day_of_week, Timetable.start_time).all()
        if not rows:
            all_rows = base_query.order_by(
                Timetable.semester.desc(), Timetable.academic_year.desc(),
                Timetable.day_of_week, Timetable.start_time,
            ).all()
            if all_rows:
                latest_term = (all_rows[0].semester, all_rows[0].academic_year)
                rows = [row for row in all_rows if (row.semester, row.academic_year) == latest_term]
        return [self._timetable_dto(row) for row in rows]

    def appointments(self, context: AuthenticatedChatContext, start: Optional[dt.datetime] = None, end: Optional[dt.datetime] = None) -> list[SafeAppointment]:
        from app.models.models import Appointment, Visitor, Node, Floorplan
        if context.visitor_id:
            visitor = self.db.query(Visitor).filter_by(visitor_id=context.visitor_id, user_id=context.user_id).first()
            if not visitor or self._visitor_expired(getattr(visitor, "access_expiry", None)):
                return []
            filters = [Appointment.guest_user_id == context.user_id]
        else:
            filters = [or_(Appointment.guest_user_id == context.user_id, Appointment.host_user_id == context.user_id)]
        if start is not None:
            filters.append(Appointment.scheduled_at >= start.replace(tzinfo=None))
        if end is not None:
            filters.append(Appointment.scheduled_at < end.replace(tzinfo=None))
        rows = (self.db.query(Appointment).options(joinedload(Appointment.guest), joinedload(Appointment.host), joinedload(Appointment.location).joinedload(Node.floorplan).joinedload(Floorplan.building)).filter(and_(*filters)).order_by(Appointment.scheduled_at).all())
        result = []
        for row in rows:
            if str(getattr(row, "status", "")).upper() == "CANCELLED":
                continue
            participant = row.host if row.guest_user_id == context.user_id else row.guest
            result.append(SafeAppointment(participant_name=getattr(participant, "full_name", "campus participant"), scheduled_at=row.scheduled_at, duration_minutes=int(row.duration_minutes or 0), status=str(row.status), location=self._location(row.location)))
        return result

    @staticmethod
    def _visitor_expired(expiry) -> bool:
        if expiry is None:
            return True
        return expiry.replace(tzinfo=None) < dt.datetime.utcnow()

    def _timetable_dto(self, row) -> SafeTimetableEntry:
        course = row.course
        return SafeTimetableEntry(course=SafeCourse(code=course.course_code, name=course.course_name, credits=getattr(course, "credit_hours", None)), weekday=str(row.day_of_week), start=row.start_time, end=row.end_time, location=self._location(row.classroom))
