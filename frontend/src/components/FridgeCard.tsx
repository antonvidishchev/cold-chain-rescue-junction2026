import type { Location } from '../types'

const STATE_STYLE: Record<string, string> = {
  NORMAL: 'border-emerald-600 bg-emerald-950/40 text-emerald-300',
  WARNING: 'border-amber-500 bg-amber-950/40 text-amber-300',
  EXCURSION: 'border-red-500 bg-red-950/50 text-red-300 animate-pulse',
  POWER_LOSS: 'border-fuchsia-500 bg-fuchsia-950/50 text-fuchsia-300 animate-pulse',
}

const KIND_LABEL: Record<Location['kind'], string> = {
  fridge: 'Monitored fridge',
  backup_fridge: 'Backup fridge',
  partner_site: 'Partner site',
}

export function FridgeCard({ location }: { location: Location }) {
  const pct = Math.round((location.used_units / location.capacity_units) * 100)
  const range = location.effective_range ?? { min_c: location.min_c, max_c: location.max_c }
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">{KIND_LABEL[location.kind]}</div>
          <h3 className="text-lg font-semibold">{location.name}</h3>
          <div className="text-xs text-slate-500">{location.address}</div>
        </div>
        {location.monitored && (
          <span className={`rounded-md border px-2 py-1 text-xs font-bold ${STATE_STYLE[location.alarm_state]}`}>
            {location.alarm_state.replace('_', ' ')}
          </span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-sm">
        <Stat label="Watchdog" value={location.last_temp_c != null ? `${location.last_temp_c.toFixed(1)} °C` : '—'} />
        <Stat label="Fridge says" value={location.reported_temp_c != null ? `${location.reported_temp_c.toFixed(1)} °C` : '—'} />
        <Stat label="Allowed" value={`${range.min_c}–${range.max_c} °C`} />
      </div>

      <div className="mt-3">
        <div className="flex justify-between text-xs text-slate-400">
          <span>Capacity</span>
          <span>
            {location.used_units}/{location.capacity_units} units · {location.free_units} free
          </span>
        </div>
        <div className="mt-1 h-2 rounded bg-slate-800">
          <div className="h-2 rounded bg-sky-500" style={{ width: `${Math.min(pct, 100)}%` }} />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <Badge ok={location.power_on}>{location.power_on ? 'Power on' : 'Power OFF'}</Badge>
        <Badge ok={!location.stock_present} neutral>
          {location.stock_present ? 'Stock present' : 'Empty'}
        </Badge>
      </div>

      {location.stock.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-slate-300">
          {location.stock.map((s) => (
            <li key={s.id} className="flex justify-between">
              <span>{s.product.name}</span>
              <span className="text-slate-500">
                ×{s.quantity} · {s.product.min_c}–{s.product.max_c} °C
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-800/60 p-2">
      <div className="text-[10px] uppercase text-slate-400">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  )
}

function Badge({ ok, neutral, children }: { ok: boolean; neutral?: boolean; children: React.ReactNode }) {
  const color = neutral ? 'bg-slate-800 text-slate-300' : ok ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-200'
  return <span className={`rounded px-2 py-0.5 ${color}`}>{children}</span>
}
