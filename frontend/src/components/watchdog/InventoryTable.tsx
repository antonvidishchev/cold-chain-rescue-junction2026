import type { Medicine } from '../../api/board'

export function InventoryTable({ items, limitingId }: { items: Medicine[]; limitingId?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h3 className="mb-3 font-semibold">Fridge inventory</h3>
      {items.length === 0 ? (
        <p className="text-sm text-slate-400">The fridge is empty.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-400">
              <tr>
                <th className="py-1 pr-3">Medicine</th>
                <th className="pr-3">Form</th>
                <th className="pr-3">Storage</th>
                <th className="pr-3">Max out of fridge</th>
                <th className="pr-3 text-right">Qty</th>
                <th className="pr-3">Lot / expiry</th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id} title={m.notes}
                  className={`border-t border-slate-800 ${m.id === limitingId ? 'bg-red-950/60' : ''}`}>
                  <td className="py-1.5 pr-3">
                    <div className="font-medium">{m.name}</div>
                    <div className="text-xs text-slate-500">{m.atc} · {m.category}</div>
                  </td>
                  <td className="pr-3 text-slate-300">{m.form}</td>
                  <td className="pr-3 whitespace-nowrap">
                    {m.storage_min_c}–{m.storage_max_c} °C
                    {m.freeze_sensitive && <span title="Do not freeze" className="ml-1">❄̸</span>}
                    {m.light_sensitive && <span title="Protect from light" className="ml-1">☀</span>}
                  </td>
                  <td className="pr-3">{m.max_excursion_minutes} min</td>
                  <td className="pr-3 text-right">{m.quantity} {m.unit}</td>
                  <td className="pr-3 text-xs text-slate-400">{m.lot}<br />{m.expiry}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-xs text-slate-500">Synthetic demo data — storage limits must come from each product's SmPC.</p>
    </div>
  )
}
