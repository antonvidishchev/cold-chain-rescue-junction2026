"""Tamper detection: the watchdog's own reading vs the fridge's self-report."""


def is_tampered(device_temp_c: float | None, reported_temp_c: float | None, tolerance_c: float) -> bool:
    """True if the fridge's self-reported temperature disagrees with the independent sensor.

    A compromised controller can report '4 C, all fine' while the fridge warms;
    the watchdog's sensor cannot be spoofed by the fridge.
    """
    if device_temp_c is None or reported_temp_c is None:
        return False
    return abs(device_temp_c - reported_temp_c) > tolerance_c
