import type { Alert, Location, Reading, TransferPlan } from '../types'

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status}`)
  return res.json() as Promise<T>
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  inventory: () => request<Location[]>('/api/inventory'),
  readings: (locationId: string, limit = 300) =>
    request<Reading[]>(`/api/readings?location_id=${encodeURIComponent(locationId)}&limit=${limit}`),
  alerts: () => request<Alert[]>('/api/alerts'),
  ackAlert: (id: number, by: string) => post<Alert>(`/api/alerts/${id}/ack`, { by }),
  resolveAlert: (id: number) => post<Alert>(`/api/alerts/${id}/resolve`, {}),
  transfers: () => request<TransferPlan[]>('/api/transfers'),
  proposeTransfer: (sourceLocationId: string) =>
    post<TransferPlan>('/api/transfers/propose', { source_location_id: sourceLocationId }),
  approveTransfer: (id: number, by: string) => post<TransferPlan>(`/api/transfers/${id}/approve`, { by }),
  sendCommand: (deviceId: string, command: 'silence' | 'unsilence' | 'test_alarm') =>
    post(`/api/devices/${deviceId}/commands`, { command }),
  sim: {
    telemetry: (deviceId: string, tempC: number) =>
      post('/api/telemetry', { device_id: deviceId, temp_c: tempC }),
    fridgeReport: (locationId: string, tempC: number | null) =>
      post('/api/sim/fridge-report', { location_id: locationId, temp_c: tempC }),
    power: (locationId: string, on: boolean) => post('/api/sim/power', { location_id: locationId, on }),
    camera: (locationId: string, stockPresent: boolean | null) =>
      post('/api/sim/camera', { location_id: locationId, stock_present: stockPresent }),
  },
}
