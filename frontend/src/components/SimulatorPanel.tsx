import { useState } from 'react'
import { api } from '../api/client'
import type { Location } from '../types'

/** Demo controls for things we can't physically do at the hackathon. */
export function SimulatorPanel({ location }: { location: Location | undefined }) {
  const [temp, setTemp] = useState(5)
  const [reported, setReported] = useState(4)
  if (!location) return null
  const deviceId = location.devices[0]?.id

  return (
    <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/60 p-4 text-sm">
      <h3 className="mb-3 font-semibold">
        Simulator <span className="text-xs font-normal text-slate-500">({location.name})</span>
      </h3>

      <Row label="Fridge power">
        <Toggle on={location.power_on} onChange={(on) => api.sim.power(location.id, on)} />
      </Row>

      <Row label="Camera: stock detected">
        <select
          className="rounded bg-slate-800 px-2 py-1"
          value={location.camera_stock_present == null ? 'auto' : String(location.camera_stock_present)}
          onChange={(e) =>
            api.sim.camera(location.id, e.target.value === 'auto' ? null : e.target.value === 'true')
          }
        >
          <option value="auto">From inventory</option>
          <option value="true">Stock present</option>
          <option value="false">Empty</option>
        </select>
      </Row>

      <Row label={`Fridge self-report: ${reported.toFixed(1)} °C`}>
        <input type="range" min={-5} max={25} step={0.5} value={reported}
          onChange={(e) => setReported(Number(e.target.value))}
          onMouseUp={() => api.sim.fridgeReport(location.id, reported)} />
      </Row>

      {deviceId && (
        <>
          <Row label={`Fake sensor reading: ${temp.toFixed(1)} °C`}>
            <div className="flex gap-2">
              <input type="range" min={-5} max={25} step={0.5} value={temp}
                onChange={(e) => setTemp(Number(e.target.value))} />
              <button className="rounded bg-slate-700 px-2 py-1 text-xs" onClick={() => api.sim.telemetry(deviceId, temp)}>
                Send
              </button>
            </div>
          </Row>
          <Row label="Device">
            <button className="rounded bg-slate-700 px-2 py-1 text-xs" onClick={() => api.sendCommand(deviceId, 'test_alarm')}>
              Test buzzer
            </button>
          </Row>
        </>
      )}
      <p className="mt-2 text-xs text-slate-500">
        With the Uno Q connected, warm the Modulino Thermo by hand instead of using the fake sensor.
      </p>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-slate-300">{label}</span>
      {children}
    </div>
  )
}

function Toggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!on)}
      className={`w-16 rounded px-2 py-1 text-xs font-bold ${on ? 'bg-emerald-700' : 'bg-red-700'}`}
    >
      {on ? 'ON' : 'OFF'}
    </button>
  )
}
