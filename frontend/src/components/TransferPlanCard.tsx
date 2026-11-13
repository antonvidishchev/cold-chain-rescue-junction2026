import type { TransferPlan } from '../types'

interface Props {
  plan: TransferPlan | undefined
  onPropose: () => void
  onApprove: (id: number) => void
}

export function TransferPlanCard({ plan, onPropose, onApprove }: Props) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-semibold">Transfer plan</h3>
        <button className="rounded bg-slate-700 px-3 py-1 text-xs hover:bg-slate-600" onClick={onPropose}>
          Propose transfer
        </button>
      </div>
      {!plan && <p className="text-sm text-slate-500">No plan yet. Propose one when cooling cannot be restored.</p>}
      {plan && (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-400">
              <tr>
                <th className="pb-1">Product</th>
                <th className="pb-1">Qty</th>
                <th className="pb-1">To</th>
                <th className="pb-1 text-right">Free after</th>
              </tr>
            </thead>
            <tbody>
              {plan.moves.map((m) => (
                <tr key={m.stock_id} className="border-t border-slate-800">
                  <td className="py-1">{m.product_name}</td>
                  <td>×{m.quantity}</td>
                  <td>{m.target_name}</td>
                  <td className="text-right font-mono">{m.target_free_units_after}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {plan.unplaced.length > 0 && (
            <div className="mt-3 rounded bg-red-950/60 p-2 text-xs text-red-200">
              <b>Could not place:</b>
              {plan.unplaced.map((u) => (
                <div key={u.stock_id}>
                  {u.product_name}: {u.reasons.join('; ')}
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 text-xs text-slate-500">{plan.rationale}</p>
          {plan.status === 'proposed' ? (
            <button
              className="mt-3 w-full rounded bg-emerald-600 py-2 text-sm font-semibold hover:bg-emerald-500"
              onClick={() => onApprove(plan.id)}
            >
              Approve transfer (human sign-off)
            </button>
          ) : (
            <p className="mt-3 text-sm text-emerald-300">✓ Approved by {plan.approved_by}</p>
          )}
        </>
      )}
    </div>
  )
}
