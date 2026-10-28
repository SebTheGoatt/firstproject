import { expect, test } from 'claude-code/testing'

import { parsePytest, parseTodos } from '../hooks/register'

const PANE = {
  plugin: 'post-one-status',
  component: 'Pane',
  requestId: 'post-one-status',
  props: { title: 'Post One', isFocused: false, bodyColumns: 72, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

const CLAUDE_MD = `# notes
## Owner's open to-dos (outside the code)
- Render env: \`LIABILITY_COVERAGE\` only once insured.
- Pick opening day and set \`LAUNCH_DATE\` in Render. Mowing in Houston
  restarts mid-to-late March.
- Run the **community** migration.

## Market notes
- not a to-do
`

// Stand-ins for git: each argv answers as the repo would.
const GIT: Record<string, string> = {
  'rev-parse --show-toplevel': '/repo',
  'rev-parse --abbrev-ref HEAD': 'claude/property-service-routing-jntyoz',
  'rev-list --count origin/claude/veteran-gibill-platform-NAd4k..HEAD': '2',
  'status --porcelain': ' M CLAUDE.md',
  'log -1 --format=%s': 'Storm mode',
  'log origin/claude/veteran-gibill-platform-NAd4k --merges -1 --format=%s%n%b':
    'Merge pull request #93 from SebTheGoatt/claude/property-service-routing-jntyoz\nReel log: mods and Dashboard V18',
}

test('the parsers read pytest and CLAUDE.md', () => {
  expect(parsePytest('....\n583 passed, 1 warning in 50.19s')).toEqual({ passed: 583, failed: 0, errors: 0, seconds: 50.19 })
  expect(parsePytest('FAILED tests/x.py\n2 failed, 581 passed, 1 error in 61.0s')).toEqual({ passed: 581, failed: 2, errors: 1, seconds: 61 })
  expect(parsePytest('no tests here')).toBe(null)
  expect(parseTodos(CLAUDE_MD)).toEqual([
    'Render env: LIABILITY_COVERAGE only once insured.',
    'Pick opening day and set LAUNCH_DATE in Render. Mowing in Houston restarts mid-to-late March.',
    'Run the community migration.',
  ])
})

test('the pane shows the branch, the to-dos and a pytest run, on every surface', async ($, on) => {
  on('command.register', () => ({ value: { command: 'post-one' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => ({
    value: { exitCode: 0, stdout: GIT[e.argv.slice(1).join(' ')] ?? '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  }))
  on('fs.read', () => ({ value: CLAUDE_MD }))
  on('tool.call', () => ({ result: {}, text: '..........\n583 passed, 1 warning in 50.19s' }))

  await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true })
  await $.tool.call({ tool: 'Bash', command: 'cd property-dispatch && python3 -m pytest -q' })

  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    await ui.press({ key: 'refresh' })
    expect((await ui.find({ type: 'Text', text: /passed/ }))?.text).toMatch(/✓ 583 passed in 50s/)
    expect(await ui.find({ type: 'Text', text: /2 commits not merged yet · 1 file changed/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Last merged: #93 Reel log/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Your to-dos \(3\)/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /LAUNCH_DATE in Render/ })).toBeDefined()
    await ui.unmount()
  }
})

test('a value an earlier version stored is declined', async ($, on) => {
  on('state.get', () => ({ value: { value: { passed: 'lots' }, version: 1 } }))
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Not run in this session yet/ })).toBeDefined()
  await ui.unmount()
})
