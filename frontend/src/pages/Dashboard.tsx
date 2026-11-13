import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useLiveEvents } from '../api/ws'
import { AlertPanel } from '../components/AlertPanel'
import { FridgeCard } from '../components/FridgeCard'
import { SimulatorPanel } from '../components/SimulatorPanel'
import { TemperatureChart } from '../components/TemperatureChart'
import { TransferPlanCard } from '../components/TransferPlanCard'
import type { Alert, LiveEvent, Location, Reading, TransferPlan } from '../types'

const MAX_POINTS = 300

export function Dashboard() {
  const [locations, setLocations] = useState<Location[]>([])
  const [readings, setReadings] = useState<Reading[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [plans, setPlans] = useState<TransferPlan[]>([])
  const [error, setError] = useState<string | null>(null)

  const monitored = locations.find((l) => l.monitored)

  const refresh = useCallback(async () => {
    try {
      const [inv, al, tr] = await Promise.all([api.inventory(), api.alerts(), api.transfers()])
      setLocations(inv)
      setAlerts(al)
      setPlans(tr)
      const m = inv.find((l) => l.monitored)
      if (m) setReadings(await api.readings(m.id))
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const connected = useLiveEvents((event: LiveEvent) => {
    switch (event.type) {
      case 'reading':
        setReadings((rs) => [...rs, event.data].slice(-MAX_POINTS))
        setLocations((ls) => ls.map((l) => (l.id === event.data.location_id ? { ...l, last_temp_c: event.data.temp_c } : l)))
        break
      case 'alert':
        setAlerts((as) => [event.data, ...as.filter((a) => a.id !== event.data.id)])
        break
      case 'state':
        setLocations((ls) => ls.map((l) => (l.id === event.data.location_id ? { ...l, alarm_state: event.data.alarm_state } : l)))
        break
      case 'location':
        void refresh()
        break
      case 'transfer':
        setPlans((ps) => [event.data, ...ps.filter((p) => p.id !== event.data.id)])
        if (event.data.status === 'approved') void refresh()
        break
    }
  })

  return (
    <div className="mx-auto max-w-7xl p-6">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">🧊 ColdChain Rescue</h1>
          <p className="text-sm text-slate-400">The fridge is warming. Who needs to act, and where can the stock go?</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs ${connected ? 'bg-emerald-900 text-emerald-300' : 'bg-slate-800 text-slate-400'}`}>
          {connected ? '● live' : '○ offline'}
        </span>
      </header>

      {error && <div className="mb-4 rounded bg-red-950 p-3 text-sm text-red-200">Backend unreachable: {error}</div>}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <TemperatureChart
            readings={readings}
            range={monitored?.effective_range ?? null}
            reportedTempC={monitored?.reported_temp_c ?? null}
          />
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {locations.map((l) => (
              <FridgeCard key={l.id} location={l} />
            ))}
          </div>
        </div>
        <div className="space-y-4">
          <AlertPanel
            alerts={alerts}
            onAck={(id, by) => void api.ackAlert(id, by)}
            onResolve={(id) => void api.resolveAlert(id)}
          />
          <TransferPlanCard
            plan={plans[0]}
            onPropose={() => monitored && void api.proposeTransfer(monitored.id)}
            onApprove={(id) => void api.approveTransfer(id, 'Pharmacist on duty')}
          />
          <SimulatorPanel location={monitored} />
        </div>
      </div>

      <footer className="mt-8 text-xs text-slate-500">
        Temperature readings alone cannot establish whether a medicine is still usable. Follow the product's storage
        instructions; a pharmacist decides on use, quarantine or disposal.
      </footer>
    </div>
  )
}
