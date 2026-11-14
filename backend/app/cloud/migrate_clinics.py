"""Explicit, non-destructive migration to the Arduino clinic catalogue."""
import argparse
import json
import os
from pathlib import Path

from app.cloud.service import CloudService
from app.cloud.settings import Settings
from app.cloud.store import get_store

CATALOGUE = Path(__file__).with_name('data') / 'clinics.json'


def migrate_clinics(store, *, apply=False, destructive=False):
    catalogue = json.loads(CATALOGUE.read_text(encoding='utf-8'))
    records = [catalogue['main'], *catalogue['clinics']]
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('Duplicate catalogue identifiers')
    service = CloudService(store)
    if not apply:
        return {'apply': False, 'active_clinics': len(records), 'primary_device': 'unoq-fridge-a'}

    def operation(state):
        if 'fridge-a' not in state['locations'] or 'unoq-fridge-a' not in state['devices']:
            raise ValueError('Bootstrap the primary device before migration')
        active_ids = {'fridge-a', *(r['id'] for r in catalogue['clinics'])}
        retired = {key for key in state['locations'] if key not in active_ids}
        for key in retired:
            if destructive:
                del state['locations'][key]
            else:
                state['locations'][key]['active'] = False
                state['locations'][key]['retired_reason'] = 'Replaced by Arduino catalogue; historical records retained'
        if destructive:
            for key in list(state['devices']):
                if state['devices'][key]['id'] != 'unoq-fridge-a':
                    del state['devices'][key]
            for key in list(state['stock']):
                if state['stock'][key]['location_id'] in retired:
                    del state['stock'][key]
            for key in list(state['commands']):
                if state['commands'][key]['device_id'] != 'unoq-fridge-a':
                    del state['commands'][key]
        settings = Settings.load()
        for index, record in enumerate(records):
            identifier = 'fridge-a' if index == 0 else record['id']
            existing = state['locations'].get(identifier)
            if existing is None:
                existing = {'id': identifier, 'min_c': settings.min_c, 'max_c': settings.max_c,
                    'capacity_units': record.get('cold_storage_capacity_units', 20),
                    'power_on': True, 'reported_temp_c': None, 'camera_stock_present': None,
                    'alarm_state': 'NORMAL', 'out_of_range_since': None, 'last_temp_c': None, 'last_reading_at': None}
                state['locations'][identifier] = existing
            existing.update({k: v for k, v in record.items() if k != 'id'})
            existing.update(clinic_id=record['id'], city=record.get('city', 'Espoo'),
                active=True, synthetic=True, monitored=index == 0,
                kind='fridge' if index == 0 else 'partner_site',
                data_source='device_demo_catalogue', operational_values_simulated=True)
            if index:
                existing['capacity_units'] = record['cold_storage_capacity_units']
        for device in state['devices'].values():
            device['active'] = device['id'] == 'unoq-fridge-a'
            if device['active']:
                device['clinic_id'] = catalogue['main']['id']
        return {'apply': True, 'active_clinics': len(records), 'primary_device': 'unoq-fridge-a',
                'history_deleted': False}

    return service.mutate(operation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Commit migration; default is preview only')
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--destructive', action='store_true', help='Delete obsolete catalogue/device/stock records; retain primary and history')
    args = parser.parse_args()
    if args.settings:
        for key, value in json.loads(args.settings.read_text(encoding='utf-8-sig'))['Values'].items():
            os.environ.setdefault(key, value)
    print(json.dumps(migrate_clinics(get_store(), apply=args.apply, destructive=args.destructive)))


if __name__ == '__main__':
    main()
