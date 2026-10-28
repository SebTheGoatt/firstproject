export type Shift = { start: string; end: string; strategy: string }
export type Today = {
  day: string
  date: string
  source: string
  shifts: Shift[]
  notes: string[]
  hotspots: Record<string, string>
  weatherError: string | null
  at: string
}

declare module 'claude-code' {
  interface PluginState {
    'dash-today': {
      today: Shaped<Today | null>
      problem: Shaped<string | null>
    }
  }
}
