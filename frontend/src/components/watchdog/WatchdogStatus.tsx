import { useEffect, useState } from 'react'
import { BOARD_URL } from '../../api/board'
import type { BoardState, CameraFrame } from '../../api/board'

const CAMERA_LABELS: Record<CameraFrame['frame'], string> = {
  fridge_normal: 'Normal',
  fridge_door_open: 'Door open',
  fridge_heating: 'Warming',
  fridge_power_outage: 'Power out',
  fridge_empty_normal: 'Empty',
  fridge_empty_door_open: 'Empty · door open',
  fridge_empty_heating: 'Empty · warming',
  fridge_empty_power_outage: 'Empty · power out',
}

const ALL_FRAMES = Object.keys(CAMERA_LABELS) as CameraFrame['frame'][]

export function WatchdogStatus({ state }: { state: BoardState }) {
  const { alarm } = state
  const acked = alarm?.acknowledged_at != null
  const alarmTone = !alarm ? 'green' : acked ? 'amber' : alarm.severity === 'critical' ? 'red' : 'amber'
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Tile label="Sensor temperature" value={state.temp_c == null ? '—' : `${state.temp_c.toFixed(1)} °C`}
          hint={state.temp_age_s == null ? 'waiting for Modulino Thermo' : `updated ${state.temp_age_s.toFixed(0)} s ago`} />
        <Tile label="Fridge inventory" value={state.inventory.stocked ? `${state.inventory.items} medicines` : 'Empty'}
          hint={state.inventory.stocked ? `${state.inventory.units} units` : 'nothing at risk'} />
        <Tile label="Alarm" value={alarm ? (alarm.protocol ?? 'CHECK') : 'None'}
          hint={alarm ? `${alarm.kind.replace('_', ' ')}${acked ? ' · acknowledged' : ''}` : 'all quiet'} tone={alarmTone} />
      </div>

      <SmartFridgePanel state={state} />

      <CameraPanel state={state} tone={alarmTone} />
    </div>
  )
}

function SmartFridgePanel({ state }: { state: BoardState }) {
  const { fridge, temp_c: sensor, fridge_mismatch_c: diff } = state
  const mismatch = diff != null && Math.abs(diff) > 2
  return (
    <div className={`rounded-xl border px-4 py-3 ${mismatch ? 'border-red-600 bg-red-950/60' : 'border-slate-800 bg-slate-900'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs uppercase tracking-wider text-slate-400">Smart fridge feed · {fridge.model}</div>
        <span className={`rounded px-2 py-0.5 text-xs leading-4 ${fridge.online ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'}`}>
          {fridge.online ? 'online' : 'offline'}
        </span>
      </div>
      <div className="mt-2 grid gap-3 sm:grid-cols-3">
        <div>
          <div className="text-xs text-slate-500">Fridge screen says</div>
          <div className="text-xl font-bold leading-tight text-slate-100">{fridge.display_temp_c.toFixed(1)} °C</div>
          <div className="text-xs text-slate-500">setpoint {fridge.setpoint_c.toFixed(1)} °C</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Arduino sensor measures</div>
          <div className="text-xl font-bold leading-tight text-slate-100">{sensor == null ? '—' : `${sensor.toFixed(1)} °C`}</div>
          <div className={`text-xs ${mismatch ? 'font-semibold text-red-300' : 'text-slate-500'}`}>
            {diff == null ? 'no sensor data' : mismatch ? `MISMATCH Δ ${Math.abs(diff).toFixed(1)} °C` : `Δ ${Math.abs(diff).toFixed(1)} °C, consistent`}
          </div>
        </div>
        <dl className="grid grid-cols-[auto_1fr_auto_1fr] content-start gap-x-2 text-xs leading-5 text-slate-400">
          <dt>Mode</dt><dd className="text-slate-200">{fridge.mode}</dd>
          <dt>Door</dt><dd className="text-slate-200">{fridge.door_open ? 'open' : 'closed'}</dd>
          <dt>Compr.</dt><dd className="text-slate-200">{fridge.compressor_on ? 'on' : 'off'}</dd>
          <dt>Power</dt><dd className="text-slate-200">{fridge.power_w.toFixed(0)} W</dd>
          <dt>Defrost</dt><dd className="text-slate-200">{fridge.defrost_active ? 'active' : 'off'}</dd>
        </dl>
      </div>
    </div>
  )
}

function CameraPanel({ state, tone }: { state: BoardState; tone: 'green' | 'amber' | 'red' }) {
  const { camera } = state
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  if (!camera) return null
  const border = { green: 'border-slate-800', amber: 'border-amber-600', red: 'border-red-600' }[tone]
  return (
    <div className={`rounded-xl border bg-slate-900 p-3 ${border}`}>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wider text-slate-400">Fridge camera{camera.simulated ? ' · simulated' : ''}</div>
        <span className="flex items-center gap-1 text-xs font-semibold text-red-400">
          <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" /> LIVE
        </span>
      </div>
      <div className="relative aspect-video overflow-hidden rounded-lg bg-black">
        {/* All stills stay mounted so switching frames cross-fades without a reload flash. */}
        {ALL_FRAMES.map((f) => (
          <img
            key={f}
            src={`${BOARD_URL}/camera/${f}.jpg`}
            alt={`Fridge camera: ${CAMERA_LABELS[f]}`}
            className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-500 ${f === camera.frame ? 'opacity-100' : 'opacity-0'}`}
          />
        ))}
        <div className="absolute left-2 top-2 rounded bg-black/60 px-2 py-0.5 font-mono text-xs text-slate-200">
          CAM-01 · {now.toLocaleTimeString()}
        </div>
        <div className="absolute bottom-2 right-2 rounded bg-black/60 px-2 py-0.5 text-xs font-semibold text-slate-100">
          {CAMERA_LABELS[camera.frame] ?? camera.frame}
        </div>
      </div>
    </div>
  )
}

function Tile({ label, value, hint, tone = 'slate' }: { label: string; value: string; hint: string; tone?: 'slate' | 'green' | 'amber' | 'red' }) {
  const color = { slate: 'text-slate-100', green: 'text-emerald-300', amber: 'text-amber-300', red: 'text-red-300' }[tone]
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-2.5">
      <div className="text-xs uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`text-xl font-bold leading-tight ${color}`}>{value}</div>
      <div className="text-xs text-slate-500">{hint}</div>
    </div>
  )
}
