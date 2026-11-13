"""Product-specific thresholds.

A location's effective range is the intersection of the storage ranges of the
products it currently holds: the strictest product governs the fridge.
"""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Range:
    min_c: float
    max_c: float

    def contains(self, temp_c: float) -> bool:
        return self.min_c <= temp_c <= self.max_c

    def fits_within(self, other: "Range") -> bool:
        """True if every temperature in self is also allowed by other."""
        return other.min_c <= self.min_c and self.max_c <= other.max_c


def effective_range(product_ranges: Iterable[Range]) -> Range | None:
    """Intersection of product ranges; None if there are no products.

    Raises ValueError if the ranges do not overlap (incompatible products stored together).
    """
    ranges = list(product_ranges)
    if not ranges:
        return None
    lo = max(r.min_c for r in ranges)
    hi = min(r.max_c for r in ranges)
    if lo > hi:
        raise ValueError(f"Incompatible storage ranges: no temperature satisfies all products ({lo} > {hi})")
    return Range(lo, hi)
