"""Latest accepted device report for display, independent of incident history."""
ALARM_KINDS = {'power_outage': 'POWER_LOSS', 'fridge_tamper': 'TAMPER',
               'unfreeze': 'UNFREEZE_CHECK', 'doors_open': 'DOORS_OPEN',
               'overheat': 'OVERHEAT', 'failure': 'FAILURE'}


def latest_display_status(events, alerts, fallback):
    candidates = []
    for event in events:
        if event.get('result', {}).get('stale'):
            continue
        kind = event.get('event', event.get('event_type'))
        data = event.get('data', {})
        status = None
        if kind == 'alarm_resolved':
            status = 'NORMAL'
        elif kind == 'telemetry' and 'alarm' in data:
            status = ALARM_KINDS.get(data['alarm'], 'NORMAL' if data['alarm'] is None else None)
        elif kind == 'status':
            status = ALARM_KINDS.get(data.get('status'), 'NORMAL' if data.get('status') == 'nominal' else None)
        elif kind in ALARM_KINDS:
            status = ALARM_KINDS[kind]
        elif kind == 'unfreeze_check_required':
            status = 'UNFREEZE_CHECK'
        if status is not None and event.get('ts'):
            candidates.append((event['ts'], status))
    for alert in alerts:
        if alert.get('user_resolved_at'):
            candidates.append((alert['user_resolved_at'], 'NORMAL'))
    if not candidates:
        return fallback, None
    timestamp, status = max(candidates, key=lambda value: value[0])
    return status, timestamp
