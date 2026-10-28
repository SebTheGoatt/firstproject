import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Repo, Tests } from '../types'

// Post One at a glance, beside the chat: the last test run, where the branch stands against the base branch
// it merges into, and the owner's open to-dos from CLAUDE.md. Opens with the session and with /post-one.
const PANE = 'post-one-status'
const BASE = 'claude/veteran-gibill-platform-NAd4k'
const APP = 'property-dispatch'
const TODO_HEADING = "## Owner's open to-dos"

// Change a tag when that value's fields change: it declines what an earlier version stored.
const tests = atom({ plugin: 'post-one-status', key: 'tests' } as const, null, { shape: 'tests-1' })
const repo = atom({ plugin: 'post-one-status', key: 'repo' } as const, null, { shape: 'repo-1' })
const todos = atom({ plugin: 'post-one-status', key: 'todos' } as const, [], { shape: 'todos-1' })

/** pytest's summary line ("583 passed, 1 warning in 50.19s") as counts; null when the text has none. */
export function parsePytest(out: string): Omit<Tests, 'at' | 'isRunning'> | null {
  const line = out.trim().split('\n').reverse().find(l => /\b\d+ (passed|failed|errors?)\b/.test(l))
  if (!line) return null
  const count = (word: string) => Number(line.match(new RegExp(`(\\d+) ${word}\\b`))?.[1] ?? 0)
  const secs = line.match(/ in ([\d.]+)s/)
  return { passed: count('passed'), failed: count('failed'), errors: count('errors?'), seconds: secs ? Number(secs[1]) : null }
}

/** The bullets under "Owner's open to-dos" in CLAUDE.md, one line each, markdown marks dropped. */
export function parseTodos(md: string): string[] {
  const start = md.indexOf(TODO_HEADING)
  if (start < 0) return []
  const lines = md.slice(start).split('\n').slice(1)
  const end = lines.findIndex(l => l.startsWith('## '))
  const items: string[] = []
  for (const l of end < 0 ? lines : lines.slice(0, end)) {
    if (l.startsWith('- ')) items.push(l.slice(2))
    else if (/^\s+\S/.test(l) && items.length) items[items.length - 1] += ' ' + l.trim()
  }
  return items.map(s => s.replace(/`|\*\*/g, '').replace(/\s+/g, ' ').trim())
}

function clock(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: 'numeric', minute: '2-digit' })
  } catch {
    return iso.slice(11, 16) + ' UTC'
  }
}

const short = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s)

async function root($: EngineInterface): Promise<string | null> {
  const r = await $.process.run(['git', 'rev-parse', '--show-toplevel'])
  return r.exitCode === 0 ? r.stdout.trim() : null
}

async function git($: EngineInterface, cwd: string, args: string[]): Promise<string> {
  const r = await $.process.run(['git', ...args], { cwd })
  return r.exitCode === 0 ? r.stdout.trim() : ''
}

/** Branch, merge state and to-dos: a few quick git reads and one file. */
async function refresh($: EngineInterface): Promise<void> {
  const top = await root($)
  if (!top) return
  const [branch, unmerged, changed, lastCommit, merged] = await Promise.all([
    git($, top, ['rev-parse', '--abbrev-ref', 'HEAD']),
    git($, top, ['rev-list', '--count', `origin/${BASE}..HEAD`]),
    git($, top, ['status', '--porcelain']),
    git($, top, ['log', '-1', '--format=%s']),
    git($, top, ['log', `origin/${BASE}`, '--merges', '-1', '--format=%s%n%b']),
  ])
  const [mergeLine = '', title = ''] = merged.split('\n')
  const pr = mergeLine.match(/#\d+/)?.[0]
  const next: Repo = {
    branch, unmerged: Number(unmerged) || 0, changed: changed ? changed.split('\n').length : 0, lastCommit,
    lastMerged: pr ? `${pr} ${title.trim()}` : mergeLine, at: new Date().toISOString(),
  }
  await update($, repo, () => next)
  try {
    const md = await $.fs.read(`${top}/CLAUDE.md`)
    await update($, todos, () => parseTodos(md))
  } catch {
    // no CLAUDE.md here: the list stays as it was
  }
  await status($)
}

async function status($: EngineInterface): Promise<void> {
  const t = await read($, tests)
  const r = await read($, repo)
  const list = await read($, todos)
  const parts = ['Post One']
  if (t) parts.push(t.isRunning ? 'tests running' : t.failed + t.errors ? `tests ${t.failed + t.errors} failing` : `tests ${t.passed} ok`)
  if (r) parts.push(r.unmerged ? `${r.unmerged} not merged` : 'all merged')
  parts.push(`${list.length} to-dos`)
  $.ui.status(parts.join(' · '))
}

async function runTests($: EngineInterface): Promise<void> {
  const top = await root($)
  if (!top) return
  const was = await read($, tests)
  if (was?.isRunning) return
  await update($, tests, t => (t ? { ...t, isRunning: true } : { passed: 0, failed: 0, errors: 0, seconds: null, at: new Date().toISOString(), isRunning: true }))
  await status($)
  let got: Omit<Tests, 'at' | 'isRunning'> | null = null
  try {
    const r = await $.process.run(['python3', '-m', 'pytest', '-q'], { cwd: `${top}/${APP}`, timeoutMs: 600_000 })
    got = parsePytest(r.stdout) ?? parsePytest(r.stderr)
  } catch {
    got = null
  }
  await update($, tests, t =>
    got ? { ...got, at: new Date().toISOString(), isRunning: false }
      : t ? { ...t, isRunning: false } : null)
  await status($)
  $.ui.toast(got ? (got.failed + got.errors ? `Post One tests: ${got.failed + got.errors} failing` : `Post One tests: all ${got.passed} passed`) : 'Post One tests could not run')
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'post-one', description: 'Show the Post One status pane (tests, branch, to-dos)' })
    void $.ui.open({ id: PANE, title: 'Post One' })
    void refresh($)
    return next(e)
  })

  on('command.run', { command: 'post-one' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Post One' })
    void refresh($)
    return { text: 'Post One status pane opened.' }
  })

  // After every turn: commits, merges and CLAUDE.md edits show up without a click.
  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    void refresh($)
    return done
  })

  // Any pytest run in the chat updates the test line, so the pane matches what was just run.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (/\bpytest\b/.test(e.command) && ran.deny === undefined && ran.text) {
      const got = parsePytest(ran.text)
      if (got) {
        await update($, tests, () => ({ ...got, at: new Date().toISOString(), isRunning: false }))
        await status($)
      }
    }
    return ran
  }).catch(($, e, next) => next(e))     // reading the result must never change the command's own outcome

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const t = await read($, tests)
    const r = await read($, repo)
    const list = await read($, todos)
    const width = Math.max(30, (e.props.bodyColumns ?? 60) - 4)
    const failing = t ? t.failed + t.errors : 0

    return (
      <Box flexDirection="column" gap={1}>
        <Box flexDirection="column">
          <Text bold>Tests</Text>
          {!t && <Text dimColor>Not run in this session yet.</Text>}
          {t && t.isRunning && <Text color="warning">Running… (about a minute)</Text>}
          {t && !t.isRunning && (
            <Text color={failing ? 'error' : 'success'}>
              {failing ? `✗ ${failing} failing, ${t.passed} passed` : `✓ ${t.passed} passed`}
              {t.seconds != null ? ` in ${Math.round(t.seconds)}s` : ''} <Text dimColor>at {clock(t.at)}</Text>
            </Text>
          )}
          <Box flexDirection="row" gap={1}>
            <Button key="run-tests" onPress={() => void runTests($)}>{t?.isRunning ? 'Running…' : 'Run tests'}</Button>
            <Button key="refresh" onPress={() => void refresh($)}>Refresh</Button>
          </Box>
        </Box>

        <Box flexDirection="column">
          <Text bold>Branch</Text>
          {!r && <Text dimColor>Reading git…</Text>}
          {r && <Text>{short(r.branch, width)}</Text>}
          {r && (
            <Text color={r.unmerged || r.changed ? 'warning' : undefined}>
              {r.unmerged ? `${r.unmerged} commit${r.unmerged === 1 ? '' : 's'} not merged yet` : 'Nothing waiting to merge'}
              {r.changed ? ` · ${r.changed} file${r.changed === 1 ? '' : 's'} changed, not committed` : ''}
            </Text>
          )}
          {r && r.lastMerged && <Text dimColor>Last merged: {short(r.lastMerged, width)}</Text>}
        </Box>

        <Box flexDirection="column">
          <Text bold>Your to-dos ({list.length})</Text>
          {list.length === 0 && <Text dimColor>None listed in CLAUDE.md.</Text>}
          {list.map(item => <Text>• {short(item, width)}</Text>)}
        </Box>
      </Box>
    )
  })
}
