export type AlarmState = 'NORMAL' | 'WARNING' | 'EXCURSION' | 'POWER_LOSS'
export type AlertType = 'EXCURSION' | 'POWER_LOSS' | 'TAMPER'

export interface Product {
  id: string
  name: string
  min_c: number
  max_c: number
  max_excursion_minutes: number
  notes: string
}

export interface StockItem {
  id: number
  product_id: string
  location_id: string
  quantity: number
  units: number
  product: Product
}

export interface Device {
  id: string
  location_id: string
  last_seen: string | null
  silenced: boolean
}

export interface Location {
  id: string
  name: string
  kind: 'fridge' | 'backup_fridge' | 'partner_site'
  address: string
  min_c: number
  max_c: number
  capacity_units: number
  used_units: number
  free_units: number
  monitored: boolean
  power_on: boolean
  reported_temp_c: number | null
  camera_stock_present: boolean | null
  stock_present: boolean
  alarm_state: AlarmState
  last_temp_c: number | null
  effective_range: { min_c: number; max_c: number } | null
  devices: Device[]
  stock: StockItem[]
}

export interface Reading {
  id: number
  device_id: string
  location_id: string
  ts: string
  temp_c: number
  alarm_active: boolean
}

export interface Alert {
  id: number
  location_id: string
  type: AlertType
  message: string
  created_at: string
  status: 'open' | 'acknowledged' | 'resolved'
  acknowledged_by: string | null
  acknowledged_at: string | null
}

export interface TransferMove {
  stock_id: number
  product_id: string
  product_name: string
  quantity: number
  units: number
  target_location_id: string
  target_name: string
  target_free_units_after: number
}

export interface TransferPlan {
  id: number
  source_location_id: string
  status: 'proposed' | 'approved' | 'rejected'
  created_at: string
  approved_by: string | null
  moves: TransferMove[]
  unplaced: { stock_id: number; product_name: string; units: number; reasons: string[] }[]
  rationale: string
}

export type LiveEvent =
  | { type: 'reading'; data: Reading }
  | { type: 'alert'; data: Alert }
  | { type: 'state'; data: { location_id: string; alarm_state: AlarmState } }
  | { type: 'location'; data: Partial<Location> & { id: string } }
  | { type: 'transfer'; data: TransferPlan }
