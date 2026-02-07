from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.db.session import get_db
from app.models import AnalyticsEvent, Enrollment
from app.schemas.analytics import AnalyticsIngestRequest, AnalyticsIngestResponse

router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


@router.post("/events:ingest", response_model=AnalyticsIngestResponse)
def ingest_events(
    payload: AnalyticsIngestRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> AnalyticsIngestResponse:
    accepted = 0
    failed = 0

    enrolled_course_ids = set(
        str(value)
        for value in db.execute(
            select(Enrollment.course_id).where(
                Enrollment.user_id == current_user.id,
                Enrollment.status == "active",
            )
        ).scalars().all()
    )

    for event in payload.events:
        if event.course_id and event.course_id not in enrolled_course_ids:
            failed += 1
            continue

        try:
            row = AnalyticsEvent(
                event_id=event.event_id,
                user_id=current_user.id,
                course_id=event.course_id,
                chapter_id=event.chapter_id,
                session_id=event.session_id,
                event_type=event.event_type,
                event_time=event.event_time,
                payload_json=event.payload,
            )
            db.add(row)
            db.commit()
            accepted += 1
        except IntegrityError:
            db.rollback()
            failed += 1

    return AnalyticsIngestResponse(accepted=accepted, failed=failed)
