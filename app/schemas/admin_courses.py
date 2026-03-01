from pydantic import BaseModel, Field


class AdminChapterCreate(BaseModel):
    chapter_code: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    order: int = 0
    intro_text: str = ""
    is_active: bool = True


class AdminCourseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    instructor: str = ""
    semester: str = ""
    overview_experience: str = ""
    overview_gains: str = ""
    overview_necessity: str = ""
    overview_journey: str = ""
    is_active: bool = True
    is_public: bool = False
    chapters: list[AdminChapterCreate] = Field(default_factory=list)


class AdminCourseResponse(BaseModel):
    id: str
    course_code: str
    title: str
    description: str
    instructor: str
    semester: str
    invite_code: str | None = None
    overview_experience: str = ""
    overview_gains: str = ""
    overview_necessity: str = ""
    overview_journey: str = ""
    is_active: bool
    is_public: bool
    created_at: str


class AdminChapterResponse(BaseModel):
    id: str
    chapter_code: str
    title: str
    intro_text: str
    order: int
    is_active: bool
    has_bundle: bool
    created_at: str


class AdminCourseWithChaptersResponse(AdminCourseResponse):
    chapters: list[AdminChapterResponse]


class AdminCourseUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    instructor: str | None = None
    semester: str | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    overview_experience: str | None = None
    overview_gains: str | None = None
    overview_necessity: str | None = None
    overview_journey: str | None = None


class AdminChapterUpsertRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    order: int = 0
    intro_text: str = ""
    is_active: bool = True


class AdminChapterIntroUpdateRequest(BaseModel):
    intro_text: str = ""


class AdminCourseSummaryResponse(AdminCourseResponse):
    chapter_count: int


class AdminCourseListResponse(BaseModel):
    courses: list[AdminCourseSummaryResponse]
    total: int
