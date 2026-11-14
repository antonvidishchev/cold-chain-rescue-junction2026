// Client for the ColdChain Watchdog running on the Arduino Uno Q (WebUI brick, port 7000).

export const BOARD_URL = ((import.meta.env.VITE_BOARD_URL as string | undefined) ?? 'http://10.0.41.103:7000').replace(
  /\/$/,
  '',
)

export type BoardCommand = 'unfreeze' | 'power_outage' | 'doors_open' | 'empty' | 'fill' | 'reset'

export interface Medicine {
  id: string
  name: string
  atc: string
  category: string
  form: string
  storage_min_c: number
  storage_max_c: number
  freeze_sensitive: boolean
  light_sensitive: boolean
  max_excursion_minutes: number
  quantity: number
  unit: string
  lot: string
  expiry: string
  notes: string
}

export interface Site {
  id: string
  name: string
  address: string
  lat: number
  lon: number
}

export interface Clinic extends Site {
  type: string
  city: string
  phone: string | null
  distance_km: number
  drive_minutes: number
  cold_storage_capacity_units: number
  accepts_after_hours: boolean
}

export interface AssessedClinic extends Clinic {
  minutes_needed: number
  reachable: boolean
}

export interface Assessment {
  window_minutes: number
  limiting_medicine: { id: string; name: string }
  protocol: 'P1' | 'P2' | 'P3' | 'P4'
  protocol_title: string
  clinics: AssessedClinic[]
  reachable_count: number
}

export interface BoardAlarm extends Partial<Omit<Assessment, 'protocol'>> {
  kind: 'unfreeze' | 'power_outage'
  severity: 'warning' | 'critical'
  title: string
  message: string
  protocol: Assessment['protocol'] | null
  started_at: number
  deadline: number | null
  seconds_left?: number
}

export interface BoardEvent {
  ts: number
  kind: string
  message: string
}

export interface BoardState {
  now: number
  temp_c: number | null
  humidity: number | null
  temp_age_s: number | null
  inventory: { stocked: boolean; items: number; units: number }
  alarm: BoardAlarm | null
  doors_open: boolean
  doors_seconds_left: number
  main_site: Site
  events: BoardEvent[]
}

export interface CommandResponse {
  result: { command: BoardCommand; message: string; stubs: string[] }
  state: BoardState
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BOARD_URL}${path}`, init)
  if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status}`)
  return res.json() as Promise<T>
}

export const board = {
  state: () => request<BoardState>('/api/state'),
  inventory: () => request<{ inventory: Medicine[] }>('/api/inventory'),
  clinics: () => request<{ main: Site; clinics: Clinic[]; assessment: Assessment | null }>('/api/clinics'),
  command: (name: BoardCommand) => request<CommandResponse>(`/api/command/${name}`, { method: 'POST' }),
}
