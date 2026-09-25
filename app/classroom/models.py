from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ClassroomModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )


class Course(ClassroomModel):
    id: str
    name: str


class CourseWork(ClassroomModel):
    id: str
    course_id: str = Field(validation_alias="courseId")
    name: str = Field(validation_alias=AliasChoices("title", "name"))


class StudentSubmission(ClassroomModel):
    id: str
    course_id: str = Field(validation_alias="courseId")
    course_work_id: str = Field(validation_alias="courseWorkId")
    name: str
    alternate_link: str | None = Field(
        default=None,
        validation_alias=AliasChoices("alternateLink", "alternate_link"),
    )


class Profile(ClassroomModel):
    id: str
    email: str | None = None
    given_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("given_name", "givenName"),
    )
    full_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("full_name", "fullName"),
    )


class Student(ClassroomModel):
    id: str
    course_id: str = Field(validation_alias="courseId")
    profile: Profile
