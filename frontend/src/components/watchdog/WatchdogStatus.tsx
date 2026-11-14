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

function formatCountdown(seconds: number) {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

export function WatchdogStatus({ state }: { state: BoardState }) {
  const { alarm } = state
  const acked = alarm?.acknowledged_at != null
  const alarmTone = !alarm ? 'green' : acked ? 'amber' : alarm.severity === 'critical' ? 'red' : 'amber'
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <Tile label="Sensor temperature" value={state.temp_c == null ? '—' : `${state.temp_c.toFixed(1)} °C`}
          hint={state.temp_age_s == null ? 'waiting for Modulino Thermo' : `updated ${state.temp_age_s.toFixed(0)} s ago`} />
        <Tile label="Fridge inventory" value={state.inventory.stocked ? `${state.inventory.items} medicines` : 'Empty'}
          hint={state.inventory.stocked ? `${state.inventory.units} units` : 'nothing at risk'} />
        <Tile label="Alarm" value={alarm ? (alarm.protocol ?? 'CHECK') : 'None'}
          hint={alarm ? `${alarm.kind.replace('_', ' ')}${acked ? ' · acknowledged' : ''}` : 'all quiet'} tone={alarmTone} />
      </div>

      <SmartFridgePanel state={state} />

      <CameraPanel state={state} tone={alarmTone} />

      {state.doors_open && (
        <div className="overflow-hidden rounded-xl border border-amber-600 bg-amber-950 py-3 text-amber-200">
          <div className="marquee whitespace-nowrap text-2xl font-bold tracking-widest">
            ⚠ CLOSE THE DOORS ⚠ CLOSE THE DOORS ⚠ CLOSE THE DOORS ({state.doors_seconds_left} s)
          </div>
        </div>
      )}

      {alarm && acked && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-600 bg-emerald-950/80 px-4 py-3 text-emerald-200">
          <div>
            <div className="text-lg font-semibold">✓ Alarm acknowledged at the fridge</div>
            <div className="text-xs text-emerald-400">Turn the knob clockwise again once the protocol is done to clear the alarm.</div>
          </div>
          <div className="text-sm text-emerald-300">
            {alarm.acknowledged_by === 'knob' ? 'Modulino Knob turned clockwise' : alarm.acknowledged_by} ·{' '}
            {new Date(alarm.acknowledged_at! * 1000).toLocaleTimeString()}
          </div>
        </div>
      )}

      {alarm && (
        <div className={`rounded-xl border p-4 ${acked ? 'border-slate-600 bg-slate-900' : alarm.severity === 'critical' ? 'border-red-600 bg-red-950/80' : 'border-amber-600 bg-amber-950/70'}`}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-wider text-slate-300">⚠ {alarm.title}</div>
              <p className="mt-1 text-sm text-slate-100">{alarm.message}</p>
              {alarm.protocol_title && (
                <p className="mt-2 text-sm font-semibold">Runbook {alarm.protocol}: {alarm.protocol_title}</p>
              )}
            </div>
            {alarm.protocol && (
              <div className="text-right">
                <div className="text-5xl font-black text-red-300">{alarm.protocol}</div>
                {alarm.seconds_left != null && (
                  <div className="mt-1 font-mono text-lg text-red-200">{formatCountdown(alarm.seconds_left)} left</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function SmartFridgePanel({ state }: { state: BoardState }) {
  const { fridge, temp_c: sensor, fridge_mismatch_c: diff } = state
  const mismatch = diff != null && Math.abs(diff) > 2
  return (
    <div className={`rounded-xl border p-4 ${mismatch ? 'border-red-600 bg-red-950/60' : 'border-slate-800 bg-slate-900'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs uppercase tracking-wider text-slate-400">Smart fridge feed · {fridge.model}</div>
        <span className={`rounded px-2 py-0.5 text-xs ${fridge.online ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'}`}>
          {fridge.online ? 'online' : 'offline'}
        </span>
      </div>
      <div className="mt-3 grid gap-4 sm:grid-cols-3">
        <div>
          <div className="text-xs text-slate-500">Fridge screen says</div>
          <div className="text-2xl font-bold text-slate-100">{fridge.display_temp_c.toFixed(1)} °C</div>
          <div className="text-xs text-slate-500">setpoint {fridge.setpoint_c.toFixed(1)} °C</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Arduino sensor measures</div>
          <div className="text-2xl font-bold text-slate-100">{sensor == null ? '—' : `${sensor.toFixed(1)} °C`}</div>
          <div className={`text-xs ${mismatch ? 'font-semibold text-red-300' : 'text-slate-500'}`}>
            {diff == null ? 'no sensor data' : mismatch ? `MISMATCH Δ ${Math.abs(diff).toFixed(1)} °C` : `Δ ${Math.abs(diff).toFixed(1)} °C, consistent`}
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-x-3 text-xs text-slate-400">
          <dt>Mode</dt><dd className="text-right text-slate-200">{fridge.mode}</dd>
          <dt>Compressor</dt><dd className="text-right text-slate-200">{fridge.compressor_on ? 'on' : 'off'}</dd>
          <dt>Defrost</dt><dd className="text-right text-slate-200">{fridge.defrost_active ? 'active' : 'off'}</dd>
          <dt>Door</dt><dd className="text-right text-slate-200">{fridge.door_open ? 'open' : 'closed'}</dd>
          <dt>Power</dt><dd className="text-right text-slate-200">{fridge.power_w.toFixed(0)} W</dd>
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
    <div className={`rounded-xl border bg-slate-900 p-4 ${border}`}>
      <div className="mb-3 flex items-center justify-between">
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
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="text-xs uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-slate-500">{hint}</div>
    </div>
  )
}
