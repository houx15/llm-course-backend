from datetime import datetime
from pydantic import BaseModel, Field


class ChapterProgressRequest(BaseModel):
    course_id: str
    chapter_id: str
    session_id: str | None = None
    status: str = Field(pattern="^(LOCKED|IN_PROGRESS|COMPLETED)$")
    task_snapshot: dict = {}


class ChapterProgressResponse(BaseModel):
    accepted: bool
    server_time: datetime
