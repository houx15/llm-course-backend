from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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


# ── List users ────────────────────────────────────────────────────────────


class AdminUserSummary(BaseModel):
    id: str
    email: str
    display_name: str
    status: str


class AdminUserListResponse(BaseModel):
    users: list[AdminUserSummary]
    total: int


@router.get("", response_model=AdminUserListResponse)
def list_users(
    status: str = Query(default="active", description="Filter by user status"),
    db: Session = Depends(get_db),
) -> AdminUserListResponse:
    stmt = select(User).where(User.status == status).order_by(User.created_at)
    users = db.execute(stmt).scalars().all()
    return AdminUserListResponse(
        users=[
            AdminUserSummary(
                id=str(u.id), email=u.email, display_name=u.display_name or "", status=u.status
            )
            for u in users
        ],
        total=len(users),
    )


# ── Bulk enroll existing users to a course ────────────────────────────────


class BulkEnrollRequest(BaseModel):
    course_id: str
    user_ids: list[str] | None = None  # None = all active users


class BulkEnrollResponse(BaseModel):
    enrolled: int
    already_enrolled: int
    course_title: str


@router.post("/bulk-enroll", response_model=BulkEnrollResponse)
def bulk_enroll(payload: BulkEnrollRequest, db: Session = Depends(get_db)) -> BulkEnrollResponse:
    course = db.get(Course, payload.course_id)
    if not course:
        from app.core.errors import ApiError, ErrorCode
        raise ApiError(status_code=404, code=ErrorCode.COURSE_NOT_FOUND, message="Course not found")

    if payload.user_ids:
        users = db.execute(select(User).where(User.id.in_(payload.user_ids))).scalars().all()
    else:
        users = db.execute(select(User).where(User.status == "active")).scalars().all()

    enrolled = 0
    already = 0
    for user in users:
        existing = db.execute(
            select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id)
        ).scalars().first()
        if existing:
            already += 1
        else:
            db.add(Enrollment(user_id=user.id, course_id=course.id, status="active"))
            enrolled += 1

    db.commit()
    return BulkEnrollResponse(enrolled=enrolled, already_enrolled=already, course_title=course.title)
