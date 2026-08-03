Cut noisy logs by 60–90% before they hit context — keep signal, drop token burn.

# Claude Token Reducer Skill

**A lightweight Claude skill for compressing verbose logs/output into actionable summaries.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Da-ya7/claude-token-reducer-skill?style=social)](https://github.com/Da-ya7/claude-token-reducer-skill/stargazers)

## Demo (Before → After)

### Before (raw log)
```text
[INFO] Building app...
[INFO] Building app...
[INFO] Building app...
[WARN] Retry 1/5 connecting to DB at db.internal:5432 timeout=5000ms
[WARN] Retry 2/5 connecting to DB at db.internal:5432 timeout=5000ms
[WARN] Retry 3/5 connecting to DB at db.internal:5432 timeout=5000ms
[ERROR] Migration failed: duplicate key value violates unique constraint "users_email_key"
[TRACE] at migrateUsers (/srv/app/migrate.js:241:13)
[TRACE] at processTicksAndRejections (node:internal/process/task_queues:95:5)
```

### After (compressed)
```text
Build spam deduped ("Building app..." repeated 3x).
DB connection retries failed 3x (timeout=5000ms, host=db.internal:5432).
Root error: duplicate key violates users_email_key during user migration.
Stack trimmed to most relevant frame: migrateUsers:241.
```

## Install (one command)

```bash
git clone https://github.com/Da-ya7/claude-token-reducer-skill.git ~/.claude/skills/claude-token-reducer-skill
```

## Usage

Use this when a tool dump or CI output is too long/noisy.

```text
Compress this output for decision-making:
- Remove duplicate/repetitive lines
- Group related warnings/errors
- Keep counts, key params, and root cause
- Trim stack traces to top actionable frames
- End with: What happened / Why / Next action

<PASTE RAW LOG HERE>
```

## Why it helps

- Lower token usage and cost
- Faster debugging loops
- Cleaner handoff summaries for teammates

## License

MIT — see [LICENSE](./LICENSE).
