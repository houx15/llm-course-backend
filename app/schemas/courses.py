from pydantic import BaseModel, Field


class CourseSummary(BaseModel):
    id: str
    title: str
    course_code: str
    instructor: str
    semester: str
    description: str = ""
    joined_at: str


class CoursesMyResponse(BaseModel):
    courses: list[CourseSummary]


class JoinCourseRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=8)


class JoinCourseResponse(BaseModel):
    course: CourseSummary


class CourseOverview(BaseModel):
    experience: str = ""
    gains: str = ""
    necessity: str = ""
    journey: str = ""


class CourseDetailResponse(BaseModel):
    id: str
    title: str
    description: str
    instructor: str
    overview: CourseOverview


class ChapterItem(BaseModel):
    id: str
    chapter_code: str
    title: str
    intro_text: str = ""
    status: str
    locked: bool
    order: int
    bundle_url: str | None = None
    bundle_version: str | None = None
    bundle_sha256: str | None = None
    bundle_size_bytes: int | None = None


class CourseChaptersResponse(BaseModel):
    course_id: str
    chapters: list[ChapterItem]
