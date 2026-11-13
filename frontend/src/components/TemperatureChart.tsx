import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Reading } from '../types'

interface Props {
  readings: Reading[]
  range: { min_c: number; max_c: number } | null
  reportedTempC: number | null
}

export function TemperatureChart({ readings, range, reportedTempC }: Props) {
  const data = readings.map((r) => ({
    t: new Date(r.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    watchdog: r.temp_c,
    reported: reportedTempC,
  }))
  return (
    <div className="h-72 rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="mb-2 flex items-center justify-between text-sm">
        <h3 className="font-semibold">Temperature: Pharmacy Fridge A</h3>
        <div className="flex gap-3 text-xs text-slate-400">
          <span className="text-sky-400">● watchdog sensor</span>
          <span className="text-slate-400">- - fridge self-report</span>
          <span className="text-emerald-400">▮ allowed range</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height="88%">
        <LineChart data={data}>
          <CartesianGrid stroke="#1e293b" />
          <XAxis dataKey="t" stroke="#64748b" fontSize={11} minTickGap={40} />
          <YAxis stroke="#64748b" fontSize={11} domain={[0, 'auto']} unit="°" />
          <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155' }} />
          {range && <ReferenceArea y1={range.min_c} y2={range.max_c} fill="#10b981" fillOpacity={0.12} />}
          <Line type="monotone" dataKey="watchdog" stroke="#38bdf8" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="stepAfter" dataKey="reported" stroke="#94a3b8" strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
