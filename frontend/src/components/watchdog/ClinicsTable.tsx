import { lazy, Suspense, useState } from 'react'
import type { AssessedClinic, Clinic, Site } from '../../api/board'

const ClinicsMap = lazy(() => import('./ClinicsMap'))

export function ClinicsTable({ main, clinics, active }: {
  main: Site | null
  clinics: (Clinic | AssessedClinic)[]
  active: boolean
}) {
  const [showMap, setShowMap] = useState(false)
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Nearby clinics</h3>
        <button
          onClick={() => setShowMap((v) => !v)}
          className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
        >
          {showMap ? 'Hide map' : 'Show map'}
        </button>
      </div>
      {main && <p className="mb-3 text-xs text-slate-400">From {main.name}, {main.address}</p>}
      {showMap && (
        <div className="mb-3">
          <Suspense fallback={<p className="text-xs text-slate-400">Loading map…</p>}>
            <ClinicsMap main={main} clinics={clinics} active={active} />
          </Suspense>
          <p className="mt-1 text-xs text-slate-500">Red = fridge site. Blue = clinic{active ? '; green = reachable, grey = not' : ''}.</p>
        </div>
      )}
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-slate-400">
          <tr>
            <th className="py-1 pr-2">#</th>
            <th className="pr-2">Clinic</th>
            <th className="pr-2">Phone</th>
            <th className="pr-2 text-right">Drive</th>
            <th className="pr-2 text-right">Space</th>
          </tr>
        </thead>
        <tbody>
          {clinics.map((c, i) => {
            const reachable = 'reachable' in c ? c.reachable : null
            const tone = !active || reachable == null ? '' : reachable ? 'text-emerald-300' : 'text-slate-500 line-through'
            return (
              <tr key={c.id} className="border-t border-slate-800">
                <td className="py-1.5 pr-2 text-slate-500">{i + 1}</td>
                <td className={`pr-2 ${tone}`}>
                  <div>{c.name}</div>
                  <div className="text-xs text-slate-500 no-underline">{c.city}{c.accepts_after_hours ? ' · 24/7' : ''}</div>
                </td>
                <td className="pr-2 whitespace-nowrap text-xs">{c.phone ?? '—'}</td>
                <td className="pr-2 text-right whitespace-nowrap">{c.drive_minutes} min</td>
                <td className="pr-2 text-right">{c.cold_storage_capacity_units}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {active && <p className="mt-2 text-xs text-slate-400">Green = reachable within the safe window (drive + 15 min packing). Call in this order.</p>}
    </div>
  )
}
