import type { ReactNode } from 'react'
import type { AssessedClinic, BoardAlarm, BoardState } from '../../api/board'
import { ackInstruction, doneInstruction, inline, runbookSection, runbookSignal } from '../../runbook'
import { clockTime, formatCountdown } from './format'

/**
 * Full-width "what to do now" panel shown at the top of the Watchdog page while
 * anything actionable is going on. The steps come verbatim from the printed
 * runbook; live values (clinics, temperatures, countdown) sit next to them.
 */
export function ActionPanel({ state }: { state: BoardState }) {
  const { alarm, doors_open } = state
  if (!alarm && !doors_open) return null
  return (
    <div className="mb-4 space-y-4">
      {doors_open && <DoorsAction secondsLeft={state.doors_seconds_left} />}
      {alarm && <AlarmAction alarm={alarm} state={state} />}
    </div>
  )
}

function AlarmAction({ alarm, state }: { alarm: BoardAlarm; state: BoardState }) {
  const acked = alarm.acknowledged_at != null
  const code = alarm.protocol ?? 'CHECK'
  const section = alarm.protocol ? runbookSection(alarm.protocol) : null
  const signal = alarm.protocol ? null : runbookSignal('`CHECK`')
  const steps = section?.steps ?? (signal ? [signal.action] : [])
  const title = section?.title ?? alarm.protocol_title ?? alarm.title

  const tone = acked
    ? 'border-slate-500 bg-slate-900'
    : alarm.severity === 'critical'
      ? 'border-red-500 bg-red-950/80'
      : 'border-amber-500 bg-amber-950/70'
  const codeColor = acked ? 'text-slate-200' : alarm.severity === 'critical' ? 'text-red-300' : 'text-amber-300'

  return (
    <section className={`overflow-hidden rounded-xl border-2 ${tone}`} aria-label={`Runbook ${code}`}>
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-white/10 px-5 py-4">
        <div className={`text-6xl font-black leading-none ${codeColor} ${acked ? '' : 'animate-pulse'}`}>{code}</div>
        <div className="min-w-0 flex-1">
          <div className="text-xs uppercase tracking-wider text-slate-300">Runbook {code} · {alarm.title}</div>
          <h2 className="text-2xl font-bold text-white sm:text-3xl">{title}</h2>
          {alarm.kind === 'power_outage' && alarm.limiting_medicine && (
            <p className="mt-1 text-sm text-slate-200">
              Limiting medicine: <strong>{alarm.limiting_medicine.name}</strong> · safe window {alarm.window_minutes} min ·{' '}
              {state.inventory.units} units at risk
            </p>
          )}
          {signal && <p className="mt-1 text-sm text-slate-200"><Md text={signal.meaning} /></p>}
        </div>
        {alarm.seconds_left != null && (
          <div className="text-right">
            <div className="font-mono text-4xl font-bold text-white">{formatCountdown(alarm.seconds_left)}</div>
            <div className="text-xs uppercase tracking-wider text-slate-300">left in safe window</div>
          </div>
        )}
      </header>

      <div className="grid gap-0 lg:grid-cols-3">
        <ol className="space-y-3 px-5 py-4 lg:col-span-2">
          {steps.map((step, i) => (
            <li key={i} className="flex gap-4 text-lg leading-snug text-slate-100 sm:text-xl">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 font-bold">{i + 1}</span>
              <span><Md text={step} /></span>
            </li>
          ))}
          {steps.length === 0 && <li className="text-lg text-slate-200">{alarm.message}</li>}
        </ol>
        <aside className="border-t border-white/10 px-5 py-4 lg:border-l lg:border-t-0">
          <Context alarm={alarm} state={state} />
        </aside>
      </div>

      <footer className={`border-t px-5 py-3 text-sm ${acked ? 'border-emerald-700 bg-emerald-950/80 text-emerald-200' : 'border-white/10 bg-black/30 text-slate-200'}`}>
        {acked ? (
          <>
            <span className="font-semibold">
              ✓ Acknowledged at the fridge
              {alarm.acknowledged_by === 'knob' ? ' (Modulino Knob)' : alarm.acknowledged_by ? ` (${alarm.acknowledged_by})` : ''} at{' '}
              {clockTime(alarm.acknowledged_at!)}.
            </span>{' '}
            {doneInstruction && (
              <>
                <span className="font-semibold">When the protocol is done: </span>
                <Md text={doneInstruction} />
              </>
            )}
          </>
        ) : (
          <>
            <span className="font-semibold">First: </span>
            {ackInstruction && <Md text={ackInstruction} />}
          </>
        )}
      </footer>
    </section>
  )
}

function Context({ alarm, state }: { alarm: BoardAlarm; state: BoardState }) {
  if (alarm.kind === 'fridge_tamper') return <TamperContext state={state} />
  if (alarm.kind === 'power_outage' && alarm.protocol === 'P3') return <WatchContext alarm={alarm} />
  if (alarm.kind === 'power_outage' && alarm.clinics) return <CallList clinics={alarm.clinics} />
  return (
    <ContextBox title="Then">
      <p className="text-sm text-slate-300">Press <strong>Reset</strong> on the dashboard, or turn the knob, after checking.</p>
    </ContextBox>
  )
}

function CallList({ clinics }: { clinics: AssessedClinic[] }) {
  const sorted = [...clinics].sort((a, b) => a.drive_minutes - b.drive_minutes)
  const reachable = sorted.filter((c) => c.reachable)
  return (
    <ContextBox title={reachable.length ? 'Call in this order' : 'No clinic reachable in time'}>
      <ol className="space-y-2">
        {sorted.map((c) => (
          <li key={c.id} className={c.reachable ? 'text-slate-100' : 'text-slate-500'}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-semibold">{c.name}</span>
              <span className="shrink-0 text-xs">{c.drive_minutes} min</span>
            </div>
            <div className="flex items-baseline justify-between gap-2 text-xs">
              {c.phone ? (
                <a href={`tel:${c.phone.replace(/\s/g, '')}`} className={`font-mono text-sm ${c.reachable ? 'text-sky-300' : ''}`}>{c.phone}</a>
              ) : (
                <span>no phone on file</span>
              )}
              <span>
                {c.cold_storage_capacity_units} units{c.accepts_after_hours ? '' : ' · office hours only'}
              </span>
            </div>
          </li>
        ))}
      </ol>
    </ContextBox>
  )
}

function TamperContext({ state }: { state: BoardState }) {
  const diff = state.fridge_mismatch_c
  return (
    <ContextBox title="Trust the sensor, not the fridge">
      <dl className="grid grid-cols-2 gap-y-2 text-sm">
        <dt className="text-slate-400">Arduino sensor</dt>
        <dd className="text-right text-2xl font-bold text-white">{state.temp_c == null ? '—' : `${state.temp_c.toFixed(1)} °C`}</dd>
        <dt className="text-slate-400">Fridge screen says</dt>
        <dd className="text-right text-2xl font-bold text-slate-400 line-through">{state.fridge.display_temp_c.toFixed(1)} °C</dd>
        <dt className="text-slate-400">Difference</dt>
        <dd className="text-right font-semibold text-red-300">{diff == null ? '—' : `Δ ${Math.abs(diff).toFixed(1)} °C`}</dd>
      </dl>
      <p className="mt-3 text-xs text-slate-400">Safe range 2–8 °C. Compare with the handheld thermometer.</p>
    </ContextBox>
  )
}

function WatchContext({ alarm }: { alarm: BoardAlarm }) {
  const half = alarm.window_minutes ? alarm.started_at + (alarm.window_minutes * 60) / 2 : null
  return (
    <ContextBox title="Escalate if power is not back">
      {half && (
        <p className="text-lg text-slate-100">
          Power not back by <strong className="font-mono text-2xl">{clockTime(half)}</strong> → switch to <strong>P2</strong>.
        </p>
      )}
      <p className="mt-2 text-sm text-slate-400">Check this screen every 30 minutes.</p>
    </ContextBox>
  )
}

function DoorsAction({ secondsLeft }: { secondsLeft: number }) {
  const signal = runbookSignal('CLOSE THE DOORS')
  return (
    <section className="overflow-hidden rounded-xl border-2 border-amber-500 bg-amber-950 text-amber-100" aria-label="Doors open">
      <div className="marquee whitespace-nowrap py-3 text-3xl font-black tracking-widest">
        ⚠ CLOSE THE DOORS ⚠ CLOSE THE DOORS ⚠ CLOSE THE DOORS ({secondsLeft} s)
      </div>
      {signal && (
        <p className="border-t border-amber-700 px-5 py-2 text-lg">
          <Md text={signal.action} />
        </p>
      )}
    </section>
  )
}

function ContextBox({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-300">{title}</h3>
      {children}
    </div>
  )
}

function Md({ text }: { text: string }) {
  return (
    <>
      {inline(text).map((run, i) =>
        run.kind === 'bold' ? <strong key={i} className="font-bold text-white">{run.text}</strong>
        : run.kind === 'em' ? <em key={i}>{run.text}</em>
        : run.kind === 'code' ? <code key={i} className="rounded bg-black/40 px-1 font-mono">{run.text}</code>
        : <span key={i}>{run.text}</span>,
      )}
    </>
  )
}
