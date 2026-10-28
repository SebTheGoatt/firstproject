export type Tests = {
  passed: number
  failed: number
  errors: number
  seconds: number | null
  at: string
  isRunning: boolean
}
export type Repo = {
  branch: string
  unmerged: number
  changed: number
  lastCommit: string
  lastMerged: string
  at: string
}

declare module 'claude-code' {
  interface PluginState {
    'post-one-status': {
      tests: Shaped<Tests | null>
      repo: Shaped<Repo | null>
      todos: Shaped<string[]>
    }
  }
}
