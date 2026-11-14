import { useCallback, useEffect, useState } from 'react'
import { BOARD_URL, board } from '../api/board'
import type { BoardCommand, BoardState, Clinic, Medicine, Site } from '../api/board'
import { ClinicsTable } from '../components/watchdog/ClinicsTable'
import { CommandPanel } from '../components/watchdog/CommandPanel'
import { InventoryTable } from '../components/watchdog/InventoryTable'
import { WatchdogStatus } from '../components/watchdog/WatchdogStatus'

const POLL_MS = 1000

export function Watchdog() {
  const [state, setState] = useState<BoardState | null>(null)
  const [inventory, setInventory] = useState<Medicine[]>([])
  const [clinics, setClinics] = useState<Clinic[]>([])
  const [main, setMain] = useState<Site | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [lastResult, setLastResult] = useState<string | null>(null)

  const loadStatic = useCallback(async () => {
    const [inv, cl] = await Promise.all([board.inventory(), board.clinics()])
    setInventory(inv.inventory)
    setClinics(cl.clinics)
    setMain(cl.main)
  }, [])

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const s = await board.state()
        if (alive) {
          setState(s)
          setError(null)
        }
      } catch (e) {
        if (alive) setError((e as Error).message)
      }
    }
    void poll()
    void loadStatic().catch((e: Error) => setError(e.message))
    const id = setInterval(poll, POLL_MS)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [loadStatic])

  // The inventory also changes on the device (knob resolving an outage moves the
  // stock out), so reload the table whenever the board's unit count changes.
  const units = state?.inventory.units
  useEffect(() => {
    if (units === undefined) return
    void loadStatic().catch((e: Error) => setError(e.message))
  }, [units, loadStatic])

  const send = async (name: BoardCommand) => {
    setBusy(true)
    try {
      const res = await board.command(name)
      setState(res.state)
      setLastResult(res.result.message)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const alarm = state?.alarm
  const outage = alarm?.kind === 'power_outage' && alarm.clinics ? alarm : null

  return (
    <div>
      {error && (
        <div className="mb-4 rounded bg-red-950 p-3 text-sm text-red-200">
          Watchdog board unreachable at {BOARD_URL}: {error}
        </div>
      )}
      {!state ? (
        <p className="text-slate-400">Connecting to the watchdog at {BOARD_URL}…</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <WatchdogStatus state={state} />
            <InventoryTable items={inventory} limitingId={outage?.limiting_medicine?.id} />
          </div>
          <div className="space-y-4">
            <CommandPanel onCommand={(c) => void send(c)} busy={busy} lastResult={lastResult} />
            <ClinicsTable main={main} clinics={outage?.clinics ?? clinics} active={!!outage} />
            <EventLog state={state} />
          </div>
        </div>
      )}
    </div>
  )
}

function EventLog({ state }: { state: BoardState }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm">
      <h3 className="mb-2 font-semibold">Event log</h3>
      {state.events.length === 0 ? (
        <p className="text-xs text-slate-500">No events yet.</p>
      ) : (
        <ul className="max-h-64 space-y-1 overflow-y-auto">
          {state.events.map((e) => (
            <li key={`${e.ts}-${e.kind}`} className="text-xs">
              <span className="font-mono text-slate-500">{new Date(e.ts * 1000).toLocaleTimeString()}</span>{' '}
              <span className="text-slate-300">{e.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
