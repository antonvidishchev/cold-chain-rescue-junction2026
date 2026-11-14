import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from app.cloud.migrate_clinics import CATALOGUE, migrate_clinics
from app.cloud.service import CloudService, bootstrap_demo
from app.cloud.store import MemoryStore


def test_catalogue_matches_device_source():
    source = Path(__file__).resolve().parents[2] / 'device/coldchain-watchdog/python/data/clinics.json'
    assert json.loads(CATALOGUE.read_text(encoding='utf-8')) == json.loads(source.read_text(encoding='utf-8'))


def test_migration_preserves_records_and_is_idempotent():
    store = MemoryStore()
    bootstrap_demo(store)
    service = CloudService(store)
    service.ingest({'device_id':'unoq-fridge-a','temp_c':4.5,'event_id':'preserve'},'temperature')
    saved = {k:store.list(k) for k in ('Readings','Stock','Events')}
    assert migrate_clinics(store)['apply'] is False
    assert len(service.inventory()) == 5
    migrate_clinics(store, apply=True)
    sites = service.inventory()
    assert len(sites) == 11
    primary = next(s for s in sites if s['id']=='fridge-a')
    assert primary['clinic_id']=='espoonlahti-main'
    assert primary['last_temp_c']==4.5
    assert primary['lat']==60.1516
    assert service.config('unoq-fridge-a')['clinic_id']=='espoonlahti-main'
    assert all(not s['devices'] and not s['monitored'] for s in sites if s['id']!='fridge-a')
    assert next(s for s in sites if s['id']=='jorvi-hospital')['capacity_units']==60
    assert store.get('Locations','fridge-b')['active'] is False
    assert saved == {k:store.list(k) for k in saved}
    snapshot = {k:store.list(k) for k in ('Locations','Devices')}
    migrate_clinics(store, apply=True)
    assert snapshot == {k:store.list(k) for k in snapshot}
    with pytest.raises(HTTPException):
        service.heartbeat('unoq-fridge-b')
    assert all(r['device_id']=='unoq-fridge-a' for r in service.check_offline())
    plan=service.propose('fridge-a')
    assert all(m['target_location_id'] not in {'fridge-b','clinic-c','clinic-vantaa','clinic-oulu'} for m in plan['moves'])
