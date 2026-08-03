#!/usr/bin/env python3
"""
compress.py — apply filter / group / truncate / dedupe to noisy text
(logs, command output, diffs, test runs) so fewer tokens get read.

Usage:
    python compress.py < input.txt
    python compress.py input.txt
    python compress.py input.txt --max-line 200 --context 2

Prints compressed text to stdout, plus a one-line stats summary to stderr:
    [compress] 812 -> 96 lines (88% cut), 3 dup groups collapsed
"""

import sys
import re
import argparse
from collections import OrderedDict

NOISE_PATTERNS = [
    r"^\s*$",                                  # blank lines
    r"^[-=_*#]{3,}\s*$",                       # decorative separators
    r"^(remote:\s*)?(Compressing|Enumerating|Counting|Resolving) objects",
    r"^Receiving objects",
    r"^\s*\d+%\|.*\|\s*\d+/\d+",              # progress bars (tqdm-style)
    r"^Downloading .* \d+(\.\d+)?[kKmMgG]?B/\d+",
    r"^\s*\[=*>?\s*\]\s*\d+%",                # ascii progress bars
]
NOISE_RE = [re.compile(p) for p in NOISE_PATTERNS]

PASS_PATTERNS = [
    r"^\s*(ok|PASS|passed|✓|✔)\b",
    r"^test\S* .*\.\.\.\s*ok\s*$",
    r"^\S*test\S*\s*\.\.\.\s*ok\s*$",
]
PASS_RE = [re.compile(p, re.IGNORECASE) for p in PASS_PATTERNS]

FAIL_PATTERNS = [
    r"\b(FAIL|FAILED|Error|ERROR|Traceback|panic|Exception|assert)\b",
]
FAIL_RE = [re.compile(p) for p in FAIL_PATTERNS]


def is_noise(line: str) -> bool:
    return any(r.search(line) for r in NOISE_RE)


def is_pass(line: str) -> bool:
    return any(r.search(line) for r in PASS_RE)


def is_fail(line: str) -> bool:
    return any(r.search(line) for r in FAIL_RE)


def truncate_line(line: str, max_len: int) -> str:
    if len(line) <= max_len:
        return line
    return line[: max_len - 3] + "..."


def filter_step(lines):
    """Drop pure noise lines."""
    return [l for l in lines if not is_noise(l)]


def collapse_pass_lines(lines):
    """Group consecutive passing/ok lines into a single count line."""
    out = []
    run = 0
    for line in lines:
        if is_pass(line):
            run += 1
            continue
        if run:
            out.append(f"... {run} passing/ok line(s) collapsed ...")
            run = 0
        out.append(line)
    if run:
        out.append(f"... {run} passing/ok line(s) collapsed ...")
    return out


def dedupe_lines(lines):
    """Collapse consecutive identical lines into one + count."""
    out = []
    prev = None
    count = 0
    for line in lines:
        if line == prev:
            count += 1
            continue
        if prev is not None:
            out.append(prev if count == 1 else f"{prev}  (x{count})")
        prev = line
        count = 1
    if prev is not None:
        out.append(prev if count == 1 else f"{prev}  (x{count})")
    return out


def group_repeated_nonadjacent(lines, min_repeats=3):
    """Collapse identical lines that repeat non-consecutively (e.g. same
    warning scattered through a log) into one instance + total count."""
    counts = OrderedDict()
    for line in lines:
        counts[line] = counts.get(line, 0) + 1

    seen = set()
    out = []
    for line in lines:
        c = counts[line]
        if c >= min_repeats:
            if line in seen:
                continue
            seen.add(line)
            out.append(f"{line}  (repeated {c}x total)")
        else:
            out.append(line)
    return out


def truncate_step(lines, max_len):
    return [truncate_line(l, max_len) for l in lines]


def truncate_traceback_blocks(lines, keep_context=2):
    """For long traceback/stack-trace blocks, keep only the first and last
    `keep_context` frames plus the final error line."""
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if re.search(r"Traceback \(most recent call last\)", line):
            block_start = i
            j = i + 1
            while j < n and (lines[j].startswith((" ", "\t")) or lines[j].strip() == ""):
                j += 1
            block = lines[block_start:j]
            if len(block) > (2 * keep_context + 2):
                head = block[: keep_context + 1]
                tail = block[-(keep_context + 1):]
                out.extend(head)
                out.append(f"    ... {len(block) - len(head) - len(tail)} frame(s) omitted ...")
                out.extend(tail)
            else:
                out.extend(block)
            i = j
        else:
            out.append(line)
            i += 1
    return out


def compress(text: str, max_len: int = 200, keep_context: int = 2) -> tuple[str, dict]:
    lines = text.splitlines()
    orig_count = len(lines)

    lines = filter_step(lines)
    lines = truncate_traceback_blocks(lines, keep_context=keep_context)
    lines = collapse_pass_lines(lines)
    lines = group_repeated_nonadjacent(lines)
    lines = dedupe_lines(lines)
    lines = truncate_step(lines, max_len)

    new_count = len(lines)
    pct = 0 if orig_count == 0 else round(100 * (1 - new_count / orig_count))
    stats = {"orig_lines": orig_count, "new_lines": new_count, "pct_cut": pct}
    return "\n".join(lines), stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="Input file (defaults to stdin)")
    ap.add_argument("--max-line", type=int, default=200, help="Max characters per line before truncation")
    ap.add_argument("--context", type=int, default=2, help="Stack frames to keep at head/tail of long tracebacks")
    args = ap.parse_args()

    text = open(args.file, encoding="utf-8", errors="replace").read() if args.file else sys.stdin.read()

    compressed, stats = compress(text, max_len=args.max_line, keep_context=args.context)
    print(compressed)
    print(
        f"[compress] {stats['orig_lines']} -> {stats['new_lines']} lines "
        f"({stats['pct_cut']}% cut)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
