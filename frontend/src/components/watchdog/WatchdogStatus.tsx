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
