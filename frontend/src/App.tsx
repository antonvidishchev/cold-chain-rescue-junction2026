import { useState } from 'react'
import { Dashboard } from './pages/Dashboard'
import { Watchdog } from './pages/Watchdog'

type Tab = 'watchdog' | 'legacy'

export default function App() {
  const [tab, setTab] = useState<Tab>('watchdog')
  return (
    <div className="min-h-screen">
      <nav className="mx-auto flex max-w-7xl items-center gap-2 px-6 pt-6">
        <span className="mr-4 text-xl font-bold">🧊 ColdChain Rescue</span>
        <TabButton active={tab === 'watchdog'} onClick={() => setTab('watchdog')}>Fridge watchdog</TabButton>
        <TabButton active={tab === 'legacy'} onClick={() => setTab('legacy')}>Backend dashboard (legacy)</TabButton>
      </nav>
      {tab === 'watchdog' ? (
        <main className="mx-auto max-w-7xl p-6">
          <Watchdog />
        </main>
      ) : (
        <Dashboard />
      )}
    </div>
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className={`rounded-full px-3 py-1 text-sm ${active ? 'bg-sky-800 text-white' : 'text-slate-400 hover:bg-slate-800'}`}>
      {children}
    </button>
  )
}
