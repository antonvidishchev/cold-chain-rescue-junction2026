import { readFileSync } from 'node:fs';
import type { Clinic } from './api';

type CatalogueSite = { id: string; name: string; city?: string; lat: number; lon: number; cold_storage_capacity_units?: number };
const catalogue: { main: CatalogueSite; clinics: CatalogueSite[] } = JSON.parse(readFileSync('..\\device\\coldchain-watchdog\\python\\data\\clinics.json', 'utf8'));
export const catalogueClinics: Clinic[] = [catalogue.main, ...catalogue.clinics].map((site, index) => ({
  ...site, id: index === 0 ? 'fridge-a' : site.id, clinic_id: site.id,
  city: site.city || 'Espoo', synthetic: true, active: true, monitored: index === 0,
  capacity_units: site.cold_storage_capacity_units ?? 100,
  used_units: 0, free_units: site.cold_storage_capacity_units ?? 100,
  last_temp_c: null, last_reading_at: null, alarm_state: 'NORMAL', power_on: true,
  devices: [], effective_range: { min_c: 2, max_c: 8 },
}));
