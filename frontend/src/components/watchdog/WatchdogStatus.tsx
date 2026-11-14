import type { BoardState } from '../../api/board'

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
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <Tile label="Sensor temperature" value={state.temp_c == null ? '—' : `${state.temp_c.toFixed(1)} °C`}
          hint={state.temp_age_s == null ? 'waiting for Modulino Thermo' : `updated ${state.temp_age_s.toFixed(0)} s ago`} />
        <Tile label="Fridge inventory" value={state.inventory.stocked ? `${state.inventory.items} medicines` : 'Empty'}
          hint={state.inventory.stocked ? `${state.inventory.units} units` : 'nothing at risk'} />
        <Tile label="Alarm" value={alarm ? (alarm.protocol ?? 'CHECK') : 'None'}
          hint={alarm ? alarm.kind.replace('_', ' ') : 'all quiet'} tone={alarm ? (alarm.severity === 'critical' ? 'red' : 'amber') : 'green'} />
      </div>

      <SmartFridgePanel state={state} />

      {state.doors_open && (
        <div className="overflow-hidden rounded-xl border border-amber-600 bg-amber-950 py-3 text-amber-200">
          <div className="marquee whitespace-nowrap text-2xl font-bold tracking-widest">
            ⚠ CLOSE THE DOORS ⚠ CLOSE THE DOORS ⚠ CLOSE THE DOORS ({state.doors_seconds_left} s)
          </div>
        </div>
      )}

      {alarm && (
        <div className={`rounded-xl border p-4 ${alarm.severity === 'critical' ? 'border-red-600 bg-red-950/80' : 'border-amber-600 bg-amber-950/70'}`}>
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
