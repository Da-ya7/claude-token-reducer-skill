---
name: token-reducer
description: Compress verbose pasted content (command output, logs, error traces, diffs, stack traces) and long uploaded files/documents before reading or summarizing them, to cut the tokens spent on them. Use whenever the user pastes raw terminal/log/build/test output into chat, uploads a large file (log, CSV, JSON, code dump, long doc) and asks for analysis/summary/debugging, or explicitly asks to "reduce tokens", "save tokens", "compress this", or mentions RTK-style filtering. Do NOT use for short pastes (under 40 lines) or content the user wants read/quoted in full.
---

# Token Reducer

*by Dhayalan (aka Joy)*

Applies four compression techniques — filter, group, truncate, dedupe — to verbose text before it enters the working context, so Claude spends fewer tokens reading it while keeping the parts that matter.

## When to trigger

- User pastes raw output (`git status`, `git diff`, `git log`, test runner output, build/lint output, stack traces, docker/kubectl logs, JSON blobs) directly in a message
- User uploads a file that is long and noisy (build logs, CSVs, large JSON, verbose code dumps) and wants it analyzed, debugged, or summarized — not read verbatim
- User explicitly asks to reduce/save tokens or compress input

Skip this for: short pastes, content the user wants reproduced in full, or files where a skill like docx/pdf/xlsx already has a better dedicated reading strategy — use this only for compressing noisy raw text/log-like content, not structured documents that need full fidelity.

## The four techniques

Apply in this order, only as far as needed to remove noise without losing signal:

1. **Filter** — drop noise: blank lines, decorative separators, boilerplate banners, progress bars, "Compressing objects... done" style chatter, comments that don't affect meaning.
2. **Group** — bundle similar items instead of listing each one: group files by directory/status, group errors by rule/type, group repeated warnings by category with a count.
3. **Truncate** — cut long lines/paths/stack frames to the part that carries information (e.g. keep the failing assertion + file:line, drop the rest of a 40-frame stack trace unless asked).
4. **Dedupe** — collapse repeated log lines into one line + `(x37)` style count instead of printing every occurrence.

## Worked patterns

| Input type | Keep | Drop / compress |
|---|---|---|
| `git status`/`diff` | changed files, +/- counts | full diff context, unchanged hunks |
| Test output (pytest/jest/cargo test/go test) | failing test names, assertion, file:line | passing test lines (→ count), full tracebacks (→ top + bottom frame) |
| Build/lint output | errors grouped by file/rule | passing files, repeated identical warnings (→ dedupe) |
| Logs (docker/kubectl/app logs) | first + last occurrence of each distinct message, with count | every repeated line |
| Large JSON/CSV | schema/keys + a few sample rows | full row-by-row dump |

## How to apply it

**Prefer the script over manual judgement — it's deterministic and doesn't cost you tokens to run.**

1. Save the pasted/uploaded raw content to a file (e.g. `/tmp/raw.txt`).
2. Run `scripts/compress.py` on it:
```bash
   python3 scripts/compress.py /tmp/raw.txt
```
   Core flags: `--max-line N` (default 200, truncate long lines), `--context N` (default 2, stack frames kept at head/tail of long tracebacks).

   Security / safety flags:
   - `--max-bytes N` — hard cap on input size read before processing (guards against huge/runaway files).
   - `--no-redact` — disable secret masking (masking is **ON by default**, see below).
   - `--no-entropy-redact` — disable the high-entropy-string heuristic pass specifically, while keeping pattern-based redaction (API keys, Bearer tokens, JWTs) on.
   - `--allow-symlink-escape` — permit following symlinks that point outside the input dir (off by default, blocked to avoid reading unintended files).
   - `--allowed-dir PATH` — restrict the script to only reading files under `PATH`; use this for automated/unattended runs.
3. Read the compressed stdout output (not the original file) for your analysis. The script prints a one-line stats summary to stderr (`[compress] 812 -> 96 lines (88% cut)`) — you can mention this if useful.
4. If a follow-up question needs a specific detail that got cut (a stack frame, a specific duplicate occurrence), go back to the original file and pull just that piece — don't reprocess the whole thing.
5. If the input isn't in a file yet (e.g. it's plain text in the conversation with no natural file form), write it to a scratch file first, then run the script — don't skip straight to manual compression unless the script genuinely can't apply (e.g. non-text/binary content).
6. Don't announce the compression mechanics unless asked — just give the compact, useful answer.

### What the script does

`scripts/compress.py` implements the four techniques programmatically:
- **Filter**: drops blank lines, decorative separators, git/progress-bar boilerplate
- **Group**: collapses runs of passing/`ok` test lines into a single count line; collapses non-adjacent repeated lines (e.g. a warning scattered through a log) into one instance + total count
- **Truncate**: caps line length; keeps only head/tail frames of long tracebacks, omitting the middle
- **Dedupe**: collapses consecutive identical lines into `line (xN)`
- **Redact** (default ON): masks common secret patterns — API keys, Bearer/auth tokens, JWTs, and high-entropy strings — before the rest of the pipeline runs. Heuristic, not a guarantee; sanity-check output before pasting it somewhere sensitive. Disable with `--no-redact` (both) or `--no-entropy-redact` (entropy pass only).

It's a starting heuristic, not perfect — always sanity-check that nothing load-bearing (the actual error, the actual failing assertion) got cut, and that redaction didn't over- or under-mask.

## Note on scope

This skill works on text already in the conversation (pasted or uploaded). It does not run commands on the user's machine — for that, real command-output compression on their own terminal, point them to the `rtk` CLI tool (https://github.com/rtk-ai/rtk), which does this same filter/group/truncate/dedupe job automatically for local shell commands.

Security posture: file reading is bounded by `--max-bytes` and `--allowed-dir`, symlink-escape is blocked by default, and secret redaction runs before other processing. These are heuristic safeguards for a token-compression tool, not a security audit — treat compressed output as reduced-risk, not risk-free.