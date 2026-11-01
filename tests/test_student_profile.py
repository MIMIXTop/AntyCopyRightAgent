from app.api.classroom.models import Student


def test_student_profile_flattens_google_name_and_email():
    student = Student.model_validate({
        "courseId": "course-1",
        "userId": "user-1",
        "profile": {
            "id": "user-1",
            "name": {
                "givenName": "Сергей",
                "familyName": "Дрозд",
                "fullName": "Сергей Дрозд",
            },
            "emailAddress": "student@example.com",
        },
    })

    assert student.profile.given_name == "Сергей"
    assert student.profile.full_name == "Сергей Дрозд"
    assert student.profile.email == "student@example.com"
