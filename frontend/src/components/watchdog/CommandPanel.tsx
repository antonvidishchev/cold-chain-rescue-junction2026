import { useState } from 'react'
import type { BoardCommand } from '../../api/board'

const OPEN_KEY = 'coldchain.commandPanel.open'

const COMMANDS: { name: BoardCommand; label: string; hint: string; style: string }[] = [
  { name: 'unfreeze', label: '❄ Suspicious unfreeze', hint: 'Fridge receives a defrost command', style: 'bg-sky-800 hover:bg-sky-700' },
  { name: 'power_outage', label: '⚡ Power outage', hint: 'Mains power lost', style: 'bg-red-800 hover:bg-red-700' },
  { name: 'doors_open', label: '🚪 Doors left open', hint: '15 s marquee + chime', style: 'bg-amber-700 hover:bg-amber-600' },
  { name: 'hack_fridge', label: '☠ Simulate hacked fridge', hint: 'Screen lies: 4 °C while defrosting', style: 'bg-purple-800 hover:bg-purple-700' },
  { name: 'empty', label: '📤 Empty the fridge', hint: 'Remove all medicines', style: 'bg-slate-700 hover:bg-slate-600' },
  { name: 'fill', label: '📥 Fill the fridge', hint: 'Restore full inventory', style: 'bg-slate-700 hover:bg-slate-600' },
]

export function CommandPanel({ onCommand, busy, lastResult }: {
  onCommand: (c: BoardCommand) => void
  busy: boolean
  lastResult: string | null
}) {
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) !== '0')
  const toggle = () => {
    setOpen((o) => {
      localStorage.setItem(OPEN_KEY, o ? '0' : '1')
      return !o
    })
  }
  return (
    <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/60 p-4 text-sm">
      <button type="button" onClick={toggle} aria-expanded={open}
        className="flex w-full items-center justify-between text-left font-semibold hover:text-white">
        <span>Simulate on the board</span>
        <span className={`text-xs text-slate-400 transition-transform ${open ? 'rotate-90' : ''}`}>▶</span>
      </button>
      {open && <>
      <div className="mt-3 grid gap-2">
        {COMMANDS.map((c) => (
          <button key={c.name} type="button" disabled={busy} onClick={() => onCommand(c.name)}
            className={`flex items-center justify-between rounded-lg px-3 py-2 text-left disabled:opacity-50 ${c.style}`}>
            <span className="font-medium">{c.label}</span>
            <span className="text-xs text-slate-300">{c.hint}</span>
          </button>
        ))}
        <button type="button" disabled={busy} onClick={() => onCommand('reset')}
          className="mt-2 rounded-lg border border-emerald-700 px-3 py-2 font-medium text-emerald-300 hover:bg-emerald-950 disabled:opacity-50">
          ✓ Reset alarms (operator)
        </button>
      </div>
      </>}
      {lastResult && <p className="mt-3 text-xs text-slate-400">Last: {lastResult}</p>}
    </div>
  )
}
