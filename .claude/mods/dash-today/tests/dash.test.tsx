import { expect, test } from 'claude-code/testing'

import { parseToday, range, statusText } from '../hooks/register'

const PANE = {
  plugin: 'dash-today',
  component: 'Pane',
  requestId: 'dash-today',
  props: { title: 'Dash today', isFocused: false, bodyColumns: 72, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

const TODAY = JSON.stringify({
  day: 'Saturday', date: '2026-10-31', source: 'auto plan', hours: 8,
  shifts: [
    { start: '16:00', end: '21:00', strategy: 'Standard Delivery' },
    { start: '21:00', end: '23:00', strategy: 'Late Night Fast Food' },
  ],
  notes: ['Rain likely 1 PM-7 PM: orders usually rise. Slow down, lights on'],
  weather_error: null,
  hotspots: { 'Standard Delivery': 'FM 1960 & Atascocita Rd corridor; Deerbrook Mall', 'Late Night Fast Food': 'Fast food on FM 1960' },
})

test('times read like a person says them', () => {
  expect(range({ start: '17:00', end: '20:00', strategy: '' })).toBe('5–8 PM')
  expect(range({ start: '11:00', end: '14:00', strategy: '' })).toBe('11 AM–2 PM')
  expect(range({ start: '21:00', end: '00:30', strategy: '' })).toBe('9 PM–12:30 AM')
  expect(parseToday('not json')).toBe(null)
  const t = parseToday(TODAY)!
  expect(statusText({ ...t, at: '' })).toBe('Dash today · 4–9 PM, 9–11 PM')
  expect(statusText({ ...t, shifts: [], at: '' })).toBe('Dash today · off')
})

test('the pane shows the shifts, where to wait and the notes, on every surface', async ($, on) => {
  on('command.register', () => ({ value: { command: 'dash' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => ({
    value: { exitCode: 0, stdout: e.argv[0] === 'git' ? '/repo' : TODAY, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  }))

  await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true })
  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    await ui.press({ key: 'refresh' })
    expect(await ui.find({ type: 'Text', text: /Saturday 2026-10-31/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /4–9 PM · Standard Delivery/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Wait near: FM 1960 & Atascocita Rd corridor$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Rain likely/ })).toBeDefined()
    await ui.unmount()
  }
})

test('a planner error shows instead of a blank pane', async ($, on) => {
  on('process.run', (_, e) => ({
    value: { exitCode: e.argv[0] === 'git' ? 0 : 1, stdout: '/repo', stderr: 'Traceback...\nModuleNotFoundError: outlook', isStdoutTruncated: false, isStderrTruncated: false },
  }))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'refresh' })
  expect(await ui.find({ type: 'Text', text: /Planner: ModuleNotFoundError/ })).toBeDefined()
  await ui.unmount()
})
