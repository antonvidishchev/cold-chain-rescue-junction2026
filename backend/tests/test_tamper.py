from app.domain.tamper import is_tampered


def test_agreeing_readings_are_not_tamper():
    assert not is_tampered(4.5, 4.0, tolerance_c=2.0)


def test_fridge_lying_is_tamper():
    assert is_tampered(12.3, 4.0, tolerance_c=2.0)


def test_missing_report_is_not_tamper():
    assert not is_tampered(12.3, None, tolerance_c=2.0)
