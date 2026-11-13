from app.domain.planner import Item, Target, propose
from app.domain.thresholds import Range


def test_respects_capacity_and_ranges():
    items = [
        Item(1, "insulin", "Insulin", Range(2, 8), 40, 4),
        Item(2, "pcr", "PCR mix", Range(2, 6), 10, 2),
    ]
    targets = [
        Target("b", "Backup B", "backup_fridge", Range(2, 8), free_units=5),
        Target("c", "Clinic C", "partner_site", Range(3, 5), free_units=10),
    ]
    plan = propose(items, targets)
    where = {m["product_id"]: m["target_location_id"] for m in plan.moves}
    assert where == {"pcr": "c", "insulin": "b"}  # B's 2-8 range is too wide for PCR (2-6)
    assert not plan.unplaced


def test_unplaceable_item_is_reported():
    items = [Item(1, "insulin", "Insulin", Range(2, 8), 40, 50)]
    targets = [Target("b", "Backup B", "backup_fridge", Range(2, 8), free_units=5)]
    plan = propose(items, targets)
    assert not plan.moves and plan.unplaced[0]["stock_id"] == 1


def test_unpowered_target_is_skipped():
    items = [Item(1, "insulin", "Insulin", Range(2, 8), 1, 1)]
    targets = [Target("b", "Backup B", "backup_fridge", Range(2, 8), free_units=5, power_on=False)]
    assert propose(items, targets).unplaced
