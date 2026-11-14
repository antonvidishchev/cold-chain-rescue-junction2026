// The operator runbook, read from the same markdown file that is printed and kept
// next to the fridge (docs/runbook.md), so the screen and the paper copy never drift.
// The parser keys on the `## P1 …` / `## H1 …` headings, the numbered steps under
// them, and the "Other watchdog alarms" table.
import md from '../../docs/runbook.md?raw'

export interface RunbookSection {
  code: string
  title: string
  steps: string[]
}

export interface RunbookSignal {
  signal: string
  meaning: string
  action: string
}

export type Inline = { kind: 'text' | 'bold' | 'em' | 'code'; text: string }

const sections = md.split(/^## /m).slice(1).map((chunk) => {
  const [heading, ...body] = chunk.split('\n')
  return { heading: heading.trim(), body }
})

function numberedSteps(lines: string[]): string[] {
  const steps: string[] = []
  for (const line of lines) {
    const start = line.match(/^\d+\.\s+(.*)$/)
    if (start) steps.push(start[1].trim())
    else if (steps.length && /^\s+\S/.test(line)) steps[steps.length - 1] += ` ${line.trim()}`
  }
  return steps
}

/** Runbook section for a protocol code (P1–P4, H1), or null if the runbook has none. */
export function runbookSection(code: string): RunbookSection | null {
  const sec = sections.find((s) => s.heading.split(/\s/)[0] === code)
  if (!sec) return null
  const title = sec.heading.replace(/^\S+\s+[—-]\s+/, '')
  return { code, title, steps: numberedSteps(sec.body) }
}

/** Row of the "Other watchdog alarms" table whose Signal cell contains `match`. */
export function runbookSignal(match: string): RunbookSignal | null {
  const sec = sections.find((s) => s.heading.startsWith('Other watchdog alarms'))
  if (!sec) return null
  for (const line of sec.body) {
    if (!line.startsWith('|')) continue
    const cells = line.split('|').slice(1, -1).map((c) => c.trim())
    if (cells.length >= 3 && cells[0].includes(match)) {
      return { signal: cells[0], meaning: cells[1], action: cells[2] }
    }
  }
  return null
}

/** Paragraph introduced by a bold label, e.g. "**Acknowledge at the fridge first:** …". */
function labelledParagraph(label: string): string | null {
  const start = md.indexOf(`**${label}`)
  if (start < 0) return null
  const end = md.indexOf('\n\n', start)
  const para = md.slice(start, end < 0 ? undefined : end).replace(/\s*\n\s*/g, ' ')
  return para.replace(/^\*\*[^*]+\*\*\s*/, '')
}

export const ackInstruction = labelledParagraph('Acknowledge at the fridge first')
export const doneInstruction = labelledParagraph('When the protocol is done')

/** Split runbook text into plain / **bold** / *em* / `code` runs for rendering. */
export function inline(text: string): Inline[] {
  const out: Inline[] = []
  for (const part of text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/)) {
    if (!part) continue
    if (part.startsWith('**')) out.push({ kind: 'bold', text: part.slice(2, -2) })
    else if (part.startsWith('*')) out.push({ kind: 'em', text: part.slice(1, -1) })
    else if (part.startsWith('`')) out.push({ kind: 'code', text: part.slice(1, -1) })
    else out.push({ kind: 'text', text: part })
  }
  return out
}
