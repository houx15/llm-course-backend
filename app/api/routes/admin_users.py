from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin_auth import require_admin_key
from app.core.security import hash_password
from app.db.session import get_db
from app.models import Course, Enrollment, User

router = APIRouter(prefix="/v1/admin/users", tags=["admin"], dependencies=[Depends(require_admin_key)])


class AdminUserCreate(BaseModel):
    email: str = Field(min_length=1)
    display_name: str = ""
    password: str = Field(min_length=8)
    invite_codes: list[str] = Field(default_factory=list)


class AdminBatchCreateRequest(BaseModel):
    users: list[AdminUserCreate]


class AdminUserResult(BaseModel):
    email: str
    display_name: str
    created: bool
    enrolled_in: list[str]


class AdminBatchCreateResponse(BaseModel):
    results: list[AdminUserResult]
    total: int


@router.post("/batch", response_model=AdminBatchCreateResponse, status_code=201)
def batch_create_users(payload: AdminBatchCreateRequest, db: Session = Depends(get_db)) -> AdminBatchCreateResponse:
    # Public active courses — auto-enroll everyone
    public_courses = db.execute(
        select(Course).where(Course.is_active.is_(True), Course.is_public.is_(True))
    ).scalars().all()

    # Collect all invite codes from request
    all_invite_codes = set()
    for u in payload.users:
        all_invite_codes.update(c.strip().upper() for c in u.invite_codes if c.strip())

    invite_course_map: dict[str, Course] = {}
    if all_invite_codes:
        specific_courses = db.execute(
            select(Course).where(Course.invite_code.in_(all_invite_codes), Course.is_active.is_(True))
        ).scalars().all()
        invite_course_map = {c.invite_code: c for c in specific_courses if c.invite_code}

    results: list[AdminUserResult] = []

    for u in payload.users:
        email = u.email.lower().strip()
        display_name = u.display_name.strip() or email.split("@")[0]
        pw_hash = hash_password(u.password)

        # Create or update user
        user = db.execute(select(User).where(User.email == email)).scalars().first()
        if user:
            user.display_name = display_name
            user.password_hash = pw_hash
            user.status = "active"
            created = False
        else:
            user = User(email=email, display_name=display_name, password_hash=pw_hash, status="active")
            db.add(user)
            db.flush()
            created = True

        # Collect courses: public + specific
        target_courses: list[Course] = list(public_courses)
        for code in u.invite_codes:
            c = invite_course_map.get(code.strip().upper())
            if c and c not in target_courses:
                target_courses.append(c)

        enrolled_titles: list[str] = []
        for course in target_courses:
            existing = db.execute(
                select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id)
            ).scalars().first()
            if not existing:
                db.add(Enrollment(user_id=user.id, course_id=course.id, status="active"))
                enrolled_titles.append(course.title)

        results.append(AdminUserResult(email=email, display_name=display_name, created=created, enrolled_in=enrolled_titles))

    db.commit()

    return AdminBatchCreateResponse(results=results, total=len(results))
