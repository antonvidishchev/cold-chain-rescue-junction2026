from app.cloud.display_status import latest_display_status


def event(kind, timestamp, data=None, stale=False):
    return {'event': kind, 'ts': timestamp, 'data': data or {}, 'result': {'stale': stale}}


def test_clinic_response_keeps_historical_alarm_separate_from_latest_report():
    from app.cloud.service import CloudService, bootstrap_demo
    from app.cloud.store import MemoryStore
    from app.cloud.watchdog import Telemetry, ingest_watchdog

    store = MemoryStore()
    bootstrap_demo(store)
    service = CloudService(store)
    service.ingest({'device_id': 'unoq-fridge-a', 'status': 'power_outage',
                    'observed_at': '2026-11-14T10:00:00+00:00'}, 'status')
    ingest_watchdog(service, Telemetry.model_validate({
        'device_id': 'unoq-fridge-a', 'event': 'telemetry', 'ts': '2026-11-14T11:00:00+00:00',
        'data': {'temp_c': 4.5, 'alarm': None},
    }))
    clinic = next(c for c in service.inventory() if c['id'] == 'fridge-a')
    assert clinic['display_status'] == 'NORMAL'
    assert clinic['alarm_state'] == 'POWER_LOSS'
    assert clinic['power_on'] is False


def test_latest_resolution_overrides_old_unresolved_history():
    events = [event('power_outage', '2026-11-14T10:00:00+00:00'),
              event('alarm_resolved', '2026-11-14T11:00:00+00:00'),
              event('inventory_changed', '2026-11-14T11:01:00+00:00')]
    assert latest_display_status(events, [], 'POWER_LOSS')[0] == 'NORMAL'


def test_new_alarm_overrides_resolution_and_late_reports_are_ignored():
    events = [event('alarm_resolved', '2026-11-14T11:00:00+00:00'),
              event('fridge_tamper', '2026-11-14T12:00:00+00:00'),
              event('alarm_resolved', '2026-11-14T13:00:00+00:00', stale=True)]
    assert latest_display_status(events, [], 'POWER_LOSS')[0] == 'TAMPER'


def test_no_alarm_telemetry_changes_display_not_physical_state():
    events = [event('telemetry', '2026-11-14T12:00:00+00:00', {'alarm': None})]
    assert latest_display_status(events, [], 'POWER_LOSS')[0] == 'NORMAL'
    assert latest_display_status([event('temperature', '2026-11-14T12:00:00+00:00', {'temp_c': 4})], [], 'POWER_LOSS')[0] == 'POWER_LOSS'


def test_user_completion_and_newer_device_alarm_are_ordered():
    alerts = [{'user_resolved_at': '2026-11-14T12:00:00+00:00'}]
    assert latest_display_status([], alerts, 'TAMPER')[0] == 'NORMAL'
    assert latest_display_status([event('doors_open', '2026-11-14T13:00:00+00:00')], alerts, 'TAMPER')[0] == 'DOORS_OPEN'
