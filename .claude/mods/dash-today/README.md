# Dash today (Claude Code mod)

A pane beside the chat with today's DoorDash shifts from the Atascocita planner (`dasher-scheduler/`):

- **Shifts:** times and strategy (restaurants, Shop & Deliver, late-night fast food) and where to wait.
- **Heads up:** rain, thunderstorms and severe-weather warnings from the National Weather Service, local events
  (Texans games, Humble ISD breaks, holidays), and Post One mowing hours once opening day comes.
- **Status line:** `Dash today · 5–8 PM`. `/dash` opens the pane again.

It runs `python3 dasher-scheduler/dasher_schedule.py --today --json` (your saved schedule if it has today, else the
auto plan), re-reads at most every 30 minutes, and changes nothing.

## Turning it on
- In a cloud session: ask Claude to "turn on the Dash today pane". Claude copies this folder into the session's mods
  folder and the app asks once to turn on mods.
- In a terminal: `claude --plugin-dir .claude/mods/dash-today`.

Check it with `claude plugin validate .claude/mods/dash-today` and `claude plugin test .claude/mods/dash-today`.
