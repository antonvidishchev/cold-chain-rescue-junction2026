import { useState } from 'react'
import type { Alert } from '../types'

const TYPE_STYLE: Record<Alert['type'], string> = {
  EXCURSION: 'bg-red-600',
  POWER_LOSS: 'bg-fuchsia-600',
  TAMPER: 'bg-orange-600',
}

interface Props {
  alerts: Alert[]
  onAck: (id: number, by: string) => void
  onResolve: (id: number) => void
}

export function AlertPanel({ alerts, onAck, onResolve }: Props) {
  const [who, setWho] = useState('Pharmacist on duty')
  const active = alerts.filter((a) => a.status !== 'resolved')
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="font-semibold">Alerts</h3>
        <input
          className="w-44 rounded bg-slate-800 px-2 py-1 text-xs"
          value={who}
          onChange={(e) => setWho(e.target.value)}
          title="Acknowledge as"
        />
      </div>
      {active.length === 0 && <p className="text-sm text-slate-500">No active alerts.</p>}
      <ul className="space-y-2">
        {active.map((a) => (
          <li key={a.id} className="rounded-lg bg-slate-800/70 p-3 text-sm">
            <div className="flex items-center gap-2">
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${TYPE_STYLE[a.type]}`}>{a.type}</span>
              <span className="text-xs text-slate-400">{new Date(a.created_at).toLocaleTimeString()}</span>
            </div>
            <p className="mt-1">{a.message}</p>
            {a.status === 'open' ? (
              <button
                className="mt-2 rounded bg-sky-600 px-3 py-1 text-xs font-semibold hover:bg-sky-500"
                onClick={() => onAck(a.id, who)}
              >
                Acknowledge
              </button>
            ) : (
              <div className="mt-2 flex items-center justify-between text-xs text-emerald-300">
                <span>✓ Acknowledged by {a.acknowledged_by}</span>
                <button className="text-slate-400 hover:text-slate-200" onClick={() => onResolve(a.id)}>
                  Resolve
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
