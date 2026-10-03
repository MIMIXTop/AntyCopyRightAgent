from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ClassroomModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )

class DriveFolder(ClassroomModel):
    id: str
    title: str | None = None
    alternate_link: str | None = Field(default=None, alias="alternateLink")


class GoogleDate(ClassroomModel):
    year: int
    month: int
    day: int

    def to_string(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"


class GoogleTimeOfDay(ClassroomModel):
    hours: int = 0
    minutes: int = 0
    seconds: int = 0

    def to_string(self) -> str:
        return f"{self.hours:02d}:{self.minutes:02d}"


class DriveFileDetail(ClassroomModel):
    id: str
    title: str | None = None
    alternate_link: str | None = Field(default=None, alias="alternateLink")
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")


class SharedDriveFile(ClassroomModel):
    drive_file: DriveFileDetail = Field(alias="driveFile")
    share_mode: str = Field(default="VIEW", alias="shareMode")


class LinkDetail(ClassroomModel):
    url: str
    title: str | None = None
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")


class YouTubeVideoDetail(ClassroomModel):
    id: str
    title: str | None = None
    alternate_link: str | None = Field(default=None, alias="alternateLink")
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")


class Material(ClassroomModel):

    drive_file: SharedDriveFile | None = Field(default=None, alias="driveFile")
    link: LinkDetail | None = None
    youtube_video: YouTubeVideoDetail | None = Field(default=None, alias="youtubeVideo")

class TeacherFolder(ClassroomModel):
    id: str
    name: str | None = None

class Course(ClassroomModel):
    id: str
    name: str
    section: str | None = None
    description_heading: str | None = Field(default=None, alias="descriptionHeading")
    description: str | None = None
    room: str | None = None
    owner_id: str = Field(alias="ownerId")
    creation_time: datetime | None = Field(default=None, alias="creationTime")
    update_time: datetime | None = Field(default=None, alias="updateTime")
    enrollment_code: str | None = Field(default=None, alias="enrollmentCode")
    course_state: str = Field(alias="courseState")  # ACTIVE, PROVISIONED, ARCHIVED, DECLINED
    alternate_link: str | None = Field(default=None, alias="alternateLink")
    teacher_folder: DriveFolder | None = Field(default=None, alias="teacherFolder")

class Announcement(ClassroomModel):
    id: str
    course_id: str = Field(alias="courseId")
    text: str
    materials: list[Material] = Field(default_factory=list)
    state: str = "PUBLISHED"
    alternate_link: str | None = Field(default=None, alias="alternateLink")
    creation_time: datetime | None = Field(default=None, alias="creationTime")
    update_time: datetime | None = Field(default=None, alias="updateTime")
    creator_user_id: str | None = Field(default=None, alias="creatorUserId")
    assignee_mode: str = Field(default="ALL_STUDENTS", alias="assigneeMode")


class AssignmentFolder(ClassroomModel):
    student_work_folder: DriveFolder | None = Field(default=None, alias="studentWorkFolder")

class CourseWork(ClassroomModel):
    id: str
    course_id: str = Field(alias="courseId")
    title: str
    description: str | None = None
    materials: list[Material] = Field(default_factory=list)
    state: str = "PUBLISHED"
    alternate_link: str | None = Field(default=None, alias="alternateLink")
    creation_time: datetime | None = Field(default=None, alias="creationTime")
    update_time: datetime | None = Field(default=None, alias="updateTime")
    due_date: GoogleDate | None = Field(default=None, alias="dueDate")
    due_time: GoogleTimeOfDay | None = Field(default=None, alias="dueTime")
    max_points: float | None = Field(default=None, alias="maxPoints")
    work_type: str = Field(default="ASSIGNMENT", alias="workType")
    creator_user_id: str | None = Field(default=None, alias="creatorUserId")
    assignment: AssignmentFolder | None = None

    @property
    def deadline_display(self) -> str | None:
        if not self.due_date:
            return None
        date_part = self.due_date.to_string()
        if self.due_time:
            return f"{date_part} {self.due_time.to_string()}"
        return date_part

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

class ResultRequest(ClassroomModel):
    model_config = ConfigDict(extra="ignore")

    status: int
    body: Any


class CreatedCourse(BaseModel):
    id: str
    name: str
    description: str | None = None
    section: str | None = None