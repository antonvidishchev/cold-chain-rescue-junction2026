export interface Device { id: string; last_seen: string | null; status: string }
export interface Clinic {
  id: string; clinic_id: string; name: string; city: string; synthetic: boolean;
  last_temp_c: number | null; last_reading_at: string | null; alarm_state: string;
  reported_temp_c?: number | null; reported_temp_at?: string | null;
  power_on: boolean; effective_range: { min_c: number; max_c: number }; devices: Device[];
  used_units: number; free_units: number;
}
export interface Reading { id: number; ts: string; temp_c: number; fridge_display_temp_c?: number | null; humidity?: number | null; stale: boolean; alarm_active: boolean }
export interface DeviceInventory {
  device_id: string; location_id: string; ts: string;
  inventory: { id: string; quantity: number }[];
  transferred?: { id: string; quantity: number }[];
  stock_present: boolean; canonical_stock_updated: false;
}
export interface WatchdogEvent {
  id: string | number; device_id?: string; location_id?: string; event?: string; event_type?: string; ts?: string;
  data?: {
    sensor_temp_c?: number | null; fridge_display_temp_c?: number | null; mismatch_c?: number | null;
    fridge_mode?: string; fridge_power_w?: number; stocked_items?: string[];
    alarm_kind?: string | null; code?: string | number | null; doors?: boolean;
    acknowledged_by?: string; resolved_by?: string; acknowledged_at?: number | null;
  };
  result?: { stale?: boolean };
}
export interface Incident {
  id: number; location_id: string; type: string; message: string; status: string;
  created_at: string; recovered_at: string | null; protocol: number | string | null;
  device_acknowledged_at?: string | null; device_acknowledged_by?: 'knob';
  device_resolved_at?: string | null; device_resolved_by?: 'knob';
  device_reported_protocol?: string | null; assessment_source?: string;
  checklist: { id: string; label: string; done: boolean }[];
}
export interface TimelineEvent { id: number; location_id: string; type: string; created_at: string; incident_type?: string; alert_id?: number; by?: string; item_id?: string; done?: boolean; plan_id?: number }
export interface ImageRecord { id: string; device_id: string; status: string; synthetic: boolean; description: string | null; observed_at: string; updated_at: string }
export interface Transfer {
  id: number; source_location_id: string; status: string; created_at: string; rationale: string;
  moves: { stock_id: number; product_name: string; quantity: number; target_location_id: string; target_name: string }[];
  unplaced: { stock_id: number; product_name: string; reasons: string[] }[];
}

export function normalizeBase(value: string): string {
  if (value === '') return '';
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('VITE_API_URL must be a public HTTP(S) URL without credentials, query or fragment.');
  }
  return url.href.replace(/\/+$/, '');
}
export const API_BASE = normalizeBase(import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://localhost:7071' : ''));
export const apiUrl = (path: string) => `${API_BASE}/api${path}`;
export const imageUrl = (id: string) => apiUrl(`/images/${encodeURIComponent(id)}/content`);

class ServiceError extends Error {
  status: number;
  constructor(status: number) { super(`Service request failed (${status}). Please try again.`); this.status = status; }
}
export async function getDeviceInventory(id: string, signal: AbortSignal): Promise<DeviceInventory | null> {
  try { return await request<DeviceInventory>(`/devices/${encodeURIComponent(id)}/inventory`, { signal }); }
  catch (error) { if (error instanceof ServiceError && error.status === 404) return null; throw error; }
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(apiUrl(path), { ...options, credentials: 'omit', cache: 'no-store' });
  if (!response.ok) throw new ServiceError(response.status);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export async function getList<T>(path: string, signal: AbortSignal): Promise<T[]> {
  const value = await request<unknown>(path, { signal });
  if (!Array.isArray(value)) throw new Error('The service returned an unexpected response.');
  return value as T[];
}
export const temperature = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}°` : '—';
export const dateTime = (value: string | null | undefined) => value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }).format(new Date(value)) : 'Not observed';
export const words = (value: string) => value.replace(/_/g, ' ').toLowerCase();
export function connectivity(clinic: Clinic, now = Date.now()) {
  if (clinic.alarm_state === 'OFFLINE') return 'Offline incident';
  const timestamps = clinic.devices.map(d => d.last_seen ? Date.parse(d.last_seen) : NaN).filter(Number.isFinite);
  if (!timestamps.length) return 'Awaiting device';
  return now - Math.max(...timestamps) > 120_000 ? 'Heartbeat stale' : 'Heartbeat recent';
}
export function observationStale(timestamp: string | null) { return !timestamp || !Number.isFinite(Date.parse(timestamp)) || Date.now() - Date.parse(timestamp) > 120_000; }
export function measurement(clinic: Clinic) {
  if (clinic.last_temp_c == null) return 'No measurement';
  return clinic.last_temp_c < clinic.effective_range.min_c || clinic.last_temp_c > clinic.effective_range.max_c ? 'Outside range' : 'In range at observation';
}
