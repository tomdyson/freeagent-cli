# freeagent-cli

[![CI](https://github.com/tomdyson/freeagent-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/tomdyson/freeagent-cli/actions/workflows/ci.yml)

A small CLI for submitting FreeAgent timeslips without clicking through the web UI.

```
freeagent-cli log acme 1h30m "fixed the thing"
```

## Install

```
uv tool install freeagent-cli
```

## One-time setup

You'll need to register your own OAuth app with FreeAgent. It takes about two minutes and keeps your data and rate limits separate from everyone else's.

1. Go to <https://dev.freeagent.com/apps> and create a new app.
2. Set the redirect URI to: `http://localhost:7878/callback`
3. Note the **OAuth identifier** and **OAuth secret**.
4. Save them locally:

   ```
   freeagent-cli auth init --client-id <id> --client-secret <secret>
   ```

   Add `--sandbox` if you want to test against the FreeAgent sandbox first.
5. Authorise the app in your browser:

   ```
   freeagent-cli auth login
   ```

   A browser tab opens, you approve, and the CLI captures the refresh token. The refresh token lasts ~20 years; access tokens auto-refresh on every command.

Credentials are stored at `~/Library/Application Support/freeagent-cli/config.json` (macOS) or the equivalent platform config directory, with file mode `0600`.

## Usage

```
freeagent-cli --help                                       # canonical flow
freeagent-cli recent                                       # what you've already logged (run this first to avoid duplicates)
freeagent-cli log <project> <duration> [comment...]        # submit a timeslip
freeagent-cli projects                                     # first-time / discovery: projects + tasks in one call
```

Examples:

```
freeagent-cli log Acme 1h30m "fixed the thing"
freeagent-cli log Acme 90m fixed the thing                 # comment without quotes
freeagent-cli log "Big Co" 1.5 --task Coding --date 2026-05-01
freeagent-cli log Acme 1.5 --dry-run                       # preview, don't submit
```

- **Duration** accepts `1.5`, `90m`, `1h30m`, or `1:30`.
- **Project / task** match by case-insensitive name substring, numeric id, or full URL.
- **`--task`** is optional when the project has a single task; otherwise the error lists the choices.
- **`--date`** defaults to today (ISO `YYYY-MM-DD` to override).
- **`--dry-run`** resolves the project/task/date and prints the would-be submission without sending it.
- **`projects --flat`** emits one project/task pair per line (tab-separated) for grep/awk.

## License

MIT
