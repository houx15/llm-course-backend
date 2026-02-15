from pydantic import BaseModel, Field


class AdminChapterCreate(BaseModel):
    chapter_code: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    order: int = 0
    intro_text: str = ""
    is_active: bool = True


class AdminCourseCreateRequest(BaseModel):
    course_code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    instructor: str = ""
    semester: str = ""
    is_active: bool = True
    chapters: list[AdminChapterCreate] = Field(default_factory=list)


class AdminCourseResponse(BaseModel):
    id: str
    course_code: str
    title: str
    description: str
    instructor: str
    semester: str
    is_active: bool
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


class AdminChapterUpsertRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    order: int = 0
    intro_text: str = ""
    is_active: bool = True


class AdminChapterIntroUpdateRequest(BaseModel):
    intro_text: str = ""
