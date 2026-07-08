from otai import envelope


def test_success_wraps_data_in_ok_envelope():
    result = envelope.success({"foo": "bar"})
    assert result == {"ok": True, "data": {"foo": "bar"}}


def test_failure_wraps_error_type_and_message():
    result = envelope.failure("s3_error", "could not reach bucket")
    assert result == {
        "ok": False,
        "error": {"type": "s3_error", "message": "could not reach bucket"},
    }
