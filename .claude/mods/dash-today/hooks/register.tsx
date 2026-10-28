import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Shift, Today } from '../types'

// Today's DoorDash shifts beside the chat, from the Atascocita planner (dasher-scheduler/): times, strategy,
// where to wait, and the day's weather and event notes. Opens with the session and with /dash.
const PANE = 'dash-today'
const PLANNER = 'dasher-scheduler/dasher_schedule.py'
const STALE_MS = 30 * 60_000      // the forecast changes slowly: re-read at most every 30 minutes after a turn

// Change a tag when that value's fields change: it declines what an earlier version stored.
const today = atom({ plugin: 'dash-today', key: 'today' } as const, null, { shape: 'today-1' })
const problem = atom({ plugin: 'dash-today', key: 'problem' } as const, null, { shape: 'problem-1' })

/** '17:00' -> 17; '00:30' after a 23:00 start -> 24.5. */
function hours(start: string, end: string): [number, number] {
  const toH = (t: string) => { const [h, m] = t.split(':').map(Number); return h + m / 60 }
  const s = toH(start)
  let e = toH(end)
  if (e <= s) e += 24
  return [s, e]
}

function clock(h: number, withSuffix = true): string {
  const hh = Math.floor(h % 24)
  const mm = Math.round((h % 1) * 60)
  const text = `${hh % 12 || 12}${mm ? `:${String(mm).padStart(2, '0')}` : ''}`
  return withSuffix ? `${text} ${hh < 12 ? 'AM' : 'PM'}` : text
}

/** '17:00'-'20:00' -> '5–8 PM'; '11:00'-'14:00' -> '11 AM–2 PM'. */
export function range(shift: Shift): string {
  const [s, e] = hours(shift.start, shift.end)
  const same = (Math.floor(s % 24) < 12) === (Math.floor(e % 24) < 12)
  return `${clock(s, !same)}–${clock(e)}`
}

/** The planner's --today --json output as a Today; null when it isn't that. */
export function parseToday(out: string): Omit<Today, 'at'> | null {
  try {
    const d = JSON.parse(out)
    if (typeof d?.day !== 'string' || !Array.isArray(d.shifts)) return null
    return {
      day: d.day, date: d.date ?? '', source: d.source ?? '', shifts: d.shifts, notes: d.notes ?? [],
      hotspots: d.hotspots ?? {}, weatherError: d.weather_error ?? null,
    }
  } catch {
    return null
  }
}

export function statusText(t: Today | null): string {
  if (!t) return 'Dash today'
  if (!t.shifts.length) return 'Dash today · off'
  return `Dash today · ${t.shifts.map(range).join(', ')}`
}

async function refresh($: EngineInterface): Promise<void> {
  const top = await $.process.run(['git', 'rev-parse', '--show-toplevel'])
  if (top.exitCode !== 0) return
  const r = await $.process.run(['python3', PLANNER, '--today', '--json'], { cwd: top.stdout.trim(), timeoutMs: 60_000 })
  const got = r.exitCode === 0 ? parseToday(r.stdout) : null
  if (got) {
    await update($, today, () => ({ ...got, at: new Date().toISOString() }))
    await update($, problem, () => null)
  } else {
    await update($, problem, () => (r.stderr.trim().split('\n').pop() || 'The planner did not answer'))
  }
  $.ui.status(statusText(await read($, today)))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'dash', description: "Show today's DoorDash shifts (Atascocita planner)" })
    void $.ui.open({ id: PANE, title: 'Dash today' })
    void refresh($)
    return next(e)
  })

  on('command.run', { command: 'dash' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Dash today' })
    void refresh($)
    return { text: 'Dash today pane opened.' }
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    const t = await read($, today)
    if (!t || Date.now() - Date.parse(t.at) > STALE_MS) void refresh($)
    return done
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const t = await read($, today)
    const err = await read($, problem)

    return (
      <Box flexDirection="column" gap={1}>
        {!t && !err && <Text dimColor>Reading today's plan…</Text>}
        {err && <Text color="error">Planner: {err}</Text>}
        {t && (
          <Box flexDirection="column">
            <Text bold>{t.day} {t.date}</Text>
            <Text dimColor>From {t.source}</Text>
          </Box>
        )}
        {t && (
          <Box flexDirection="column">
            {t.shifts.length === 0 && <Text>Off today. Rest up.</Text>}
            {t.shifts.map(s => (
              <Box flexDirection="column">
                <Text color="success">{range(s)} · {s.strategy}</Text>
                {t.hotspots[s.strategy] && <Text dimColor>Wait near: {t.hotspots[s.strategy].split(';')[0]}</Text>}
              </Box>
            ))}
          </Box>
        )}
        {t && t.notes.length > 0 && (
          <Box flexDirection="column">
            <Text bold>Heads up</Text>
            {t.notes.map(n => <Text color="warning">• {n}</Text>)}
          </Box>
        )}
        {t?.weatherError && <Text dimColor>{t.weatherError}</Text>}
        <Box flexDirection="row" gap={1}>
          <Button key="refresh" onPress={() => void refresh($)}>Refresh</Button>
        </Box>
      </Box>
    )
  })
}
