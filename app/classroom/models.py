from pydantic import BaseModel
class Course(BaseModel):
    id: str
    name: str

class CourseWork(BaseModel):
    id: str
    course_id: str
    name: str

class StudentSubmission(BaseModel):
    id: str
    course_id: str
    course_work_id: str
    name: str

    alternateLink: str

class Profile(BaseModel):
    id: str
    email: str
    given_name: str
    full_name: str

class Student(BaseModel):
    id: str
    course_id:str

    profile: Profile

