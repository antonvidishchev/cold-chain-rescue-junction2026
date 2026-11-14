import { useId } from 'react';
import { dateTime, type Reading, type Clinic } from './api';
export default function HistoryChart({ readings, clinic }: { readings: Reading[]; clinic: Clinic }) {
  const title = useId();
  const points = readings.filter(row => Number.isFinite(row.temp_c) && Number.isFinite(Date.parse(row.ts)));
  if (!points.length) return <div className="empty">No temperature observations in the last 24 hours.</div>;
  const min = Math.min(clinic.effective_range.min_c, ...points.map(p => p.temp_c)) - 1;
  const max = Math.max(clinic.effective_range.max_c, ...points.map(p => p.temp_c)) + 1;
  const start = Date.parse(points[0].ts), end = Date.parse(points.at(-1)!.ts);
  const x = (time: string) => 48 + (end === start ? 0.5 : (Date.parse(time) - start) / (end - start)) * 680;
  const y = (temp: number) => 170 - (temp - min) / (max - min) * 144;
  return <>
    <svg className="history-chart" viewBox="0 0 760 210" role="img" aria-labelledby={title}>
      <title id={title}>{clinic.city} measured temperature history. {points.length} observations. Latest {points.at(-1)!.temp_c} degrees Celsius. Configured range {clinic.effective_range.min_c} to {clinic.effective_range.max_c} degrees.</title>
      <rect x="48" y={y(clinic.effective_range.max_c)} width="680" height={y(clinic.effective_range.min_c) - y(clinic.effective_range.max_c)} fill="#e3f1e9" rx="3" />
      {[min, clinic.effective_range.min_c, clinic.effective_range.max_c, max].map((tick, index) => <g key={index}><line x1="48" x2="728" y1={y(tick)} y2={y(tick)} stroke="#dce4e4" strokeDasharray="3 5" /><text x="37" y={y(tick) + 4} textAnchor="end">{tick.toFixed(1)}°</text></g>)}
      <polyline fill="none" stroke="#13776d" strokeWidth="2.5" strokeLinejoin="round" points={points.map(p => `${x(p.ts)},${y(p.temp_c)}`).join(' ')} />
      {points.map(p => <circle key={p.id} cx={x(p.ts)} cy={y(p.temp_c)} r={points.length > 80 ? 2 : 3.5} fill={p.temp_c < clinic.effective_range.min_c || p.temp_c > clinic.effective_range.max_c ? '#be4938' : '#13776d'}><title>{dateTime(p.ts)}: {p.temp_c}°C{p.stale ? ' (late arrival)' : ''}</title></circle>)}
      <text x="48" y="200">{dateTime(points[0].ts)}</text><text x="728" y="200" textAnchor="end">{dateTime(points.at(-1)!.ts)}</text>
    </svg>
    <div className="chart-caption"><span><i className="legend-dot teal" />Measured °C</span><span><i className="legend-dot range" />Configured range</span><span>{points.length} observations · last 24h</span></div>
    <details className="data-table"><summary>View accessible observation table</summary><div className="table-scroll" tabIndex={0} role="region" aria-label="Temperature observations"><table><thead><tr><th scope="col">Observation time</th><th scope="col">Sensor °C</th><th scope="col">Fridge display °C</th><th scope="col">Humidity %</th><th scope="col">Delivery</th></tr></thead><tbody>{points.map(p => <tr key={p.id}><td>{dateTime(p.ts)}</td><td>{p.temp_c}</td><td>{p.fridge_display_temp_c ?? '—'}</td><td>{p.humidity ?? '—'}</td><td>{p.stale ? 'Late arrival' : 'Current at receipt'}</td></tr>)}</tbody></table></div></details>
  </>;
}
