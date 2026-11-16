from app.api.classroom.models import ResultRequest
from app.api.telegram.callbacks import _created_announcement_ref


def test_created_announcement_ref_reads_result_request_body():
    result = ResultRequest(
        status=200,
        body={
            "id": "ann-1",
            "alternateLink": "https://classroom.google.com/c/x/a/ann-1",
        },
    )

    assert _created_announcement_ref(result) == (
        "ann-1",
        "https://classroom.google.com/c/x/a/ann-1",
    )


def test_created_announcement_ref_tolerates_missing_body():
    assert _created_announcement_ref(ResultRequest(status=200, body=None)) == (
        None,
        None,
    )
    # The callback must never reach for attributes that ResultRequest lacks.
    assert _created_announcement_ref(object()) == (None, None)
