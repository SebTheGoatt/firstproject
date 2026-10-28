# Post One status (Claude Code mod)

A pane beside the chat that shows Post One at a glance while Claude works on this repo:

- **Tests:** the last `pytest` result (any run in the chat updates it), with a **Run tests** button.
- **Branch:** the working branch, commits not yet merged into `claude/veteran-gibill-platform-NAd4k`, uncommitted
  files, and the last merged pull request.
- **Your to-dos:** the bullets under "Owner's open to-dos" in `CLAUDE.md`, re-read after every turn.

The status line carries the short form (`Post One · tests 583 ok · all merged · 10 to-dos`), and `/post-one`
opens the pane again. It reads git and one file; it changes nothing and needs no keys.

## Turning it on

- In a cloud session (the Claude app): ask Claude to "turn on the Post One status pane". Claude copies this folder
  into the session's mods folder and the app asks once to turn on mods.
- In a terminal: `claude --plugin-dir .claude/mods/post-one-status`.

Check it with `claude plugin validate .claude/mods/post-one-status` and `claude plugin test .claude/mods/post-one-status`.
