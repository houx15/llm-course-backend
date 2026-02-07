from datetime import datetime

from pydantic import BaseModel, Field


class AnalyticsEventIn(BaseModel):
    event_id: str | None = Field(default=None, max_length=128)
    event_type: str = Field(min_length=1, max_length=128)
    event_time: datetime
    course_id: str | None = None
    chapter_id: str | None = None
    session_id: str | None = None
    payload: dict = {}


class AnalyticsIngestRequest(BaseModel):
    events: list[AnalyticsEventIn]


class AnalyticsIngestResponse(BaseModel):
    accepted: int
    failed: int
