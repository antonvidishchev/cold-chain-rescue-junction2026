import { Watchdog } from './pages/Watchdog'

export default function App() {
  return (
    <div className="min-h-screen">
      <nav className="mx-auto flex max-w-7xl items-center gap-2 px-6 pt-6">
        <span className="text-xl font-bold">🧊 ColdChain Rescue</span>
      </nav>
      <main className="mx-auto max-w-7xl p-6">
        <Watchdog />
      </main>
    </div>
  )
}
