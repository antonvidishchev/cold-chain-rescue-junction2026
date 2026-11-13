"""Deterministic transfer planner.

Authoritative: any plan (including future AI-suggested ones) must pass these
checks. A target is eligible for a product when
  * it is powered,
  * its temperature range fits inside the product's storage range, and
  * it has enough free capacity for the whole stock item.
Closer kinds of storage are preferred (backup fridge on site before partner sites).
"""

from dataclasses import dataclass, field

from app.domain.thresholds import Range

KIND_PREFERENCE = {"backup_fridge": 0, "fridge": 1, "partner_site": 2}


@dataclass
class Target:
    id: str
    name: str
    kind: str
    range: Range
    free_units: int
    power_on: bool = True


@dataclass(frozen=True)
class Item:
    stock_id: int
    product_id: str
    product_name: str
    product_range: Range
    quantity: int
    units: int


@dataclass
class Plan:
    moves: list[dict] = field(default_factory=list)
    unplaced: list[dict] = field(default_factory=list)


def propose(items: list[Item], targets: list[Target]) -> Plan:
    plan = Plan()
    ordered_targets = sorted(targets, key=lambda t: (KIND_PREFERENCE.get(t.kind, 9), t.id))
    # Place the most constrained (narrowest range), then largest, items first.
    ordered_items = sorted(items, key=lambda i: (i.product_range.max_c - i.product_range.min_c, -i.units))

    for item in ordered_items:
        reasons: list[str] = []
        for t in ordered_targets:
            if not t.power_on:
                reasons.append(f"{t.name}: no power")
                continue
            if not t.range.fits_within(item.product_range):
                reasons.append(f"{t.name}: range {t.range.min_c}-{t.range.max_c} C outside product range")
                continue
            if t.free_units < item.units:
                reasons.append(f"{t.name}: only {t.free_units} free units, need {item.units}")
                continue
            t.free_units -= item.units
            plan.moves.append(
                {
                    "stock_id": item.stock_id,
                    "product_id": item.product_id,
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "units": item.units,
                    "target_location_id": t.id,
                    "target_name": t.name,
                    "target_free_units_after": t.free_units,
                }
            )
            break
        else:
            plan.unplaced.append(
                {"stock_id": item.stock_id, "product_name": item.product_name, "units": item.units, "reasons": reasons}
            )
    return plan
