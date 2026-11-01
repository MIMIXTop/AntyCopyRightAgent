from app.api.classroom.models import CourseMaterial


def test_course_material_topic_is_optional():
    material = CourseMaterial.model_validate({
        "courseId": "course-1",
        "id": "material-1",
        "title": "Журнал успеваемости",
        "materials": [],
    })

    assert material.topic_id is None
