import pytest

from app.domain.thresholds import Range, effective_range


def test_effective_range_is_intersection_of_products():
    assert effective_range([Range(2, 8), Range(2, 6)]) == Range(2, 6)


def test_no_products_means_no_range():
    assert effective_range([]) is None


def test_incompatible_products_raise():
    with pytest.raises(ValueError):
        effective_range([Range(2, 8), Range(15, 25)])


def test_fits_within():
    assert Range(3, 5).fits_within(Range(2, 8))
    assert not Range(2, 8).fits_within(Range(2, 6))
