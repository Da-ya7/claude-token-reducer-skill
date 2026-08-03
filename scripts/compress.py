#!/usr/bin/env python3
"""
compress.py — apply filter / group / truncate / dedupe to noisy text
(logs, command output, diffs, test runs) so fewer tokens get read.

Security changelog:
- Added opt-out secret redaction so common API keys, bearer tokens, password/token fields, and high-entropy strings are masked before compression.
- Added input size limits and long-line caps to reduce memory abuse and regex worst cases on hostile logs.
- Added file/path validation plus a hard block for symlinks that escape the current working directory unless explicitly allowed.
- Added ANSI escape stripping so terminal control sequences never reach compressed output.
- Added an opt-out entropy fallback pass and an optional allowed-directory boundary for automated callers.

Usage:
    python compress.py < input.txt
    python compress.py input.txt
    python compress.py input.txt --max-line 200 --context 2

Prints compressed text to stdout, plus a one-line stats summary to stderr:
    [compress] 812 -> 96 lines (88% cut), 3 dup groups collapsed
"""

import sys
import os
import math
import re
import argparse
from pathlib import Path
from collections import OrderedDict

DEFAULT_MAX_BYTES = 20 * 1024 * 1024
MAX_REGEX_LINE = 5000

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

ANSI_RE = re.compile(
    r"\x1B\[[0-?]*[ -/]*[@-~]|\x1B\][^\x1b\x07]*(?:\x07|\x1b\\)|\x1B[@-Z\\-_]"
)

HIGH_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=_-]{20,}")

SENSITIVE_FIELD_RE = re.compile(
    r'(?i)(\b(?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?token|client[_-]?secret|session[_-]?id)\b\s*[:=]\s*)(["\']?)([^\s,;"\']+)(["\']?)'
)
JSON_SENSITIVE_FIELD_RE = re.compile(
    r'(?i)(["\'](?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?token|client[_-]?secret|session[_-]?id)["\']\s*:\s*)(["\'])(.*?)(\2)'
)
JWT_RE = re.compile(r'(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{10,})(?![A-Za-z0-9_-])')
JWT_VALUE_RE = re.compile(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$')
BASIC_SECRET_REPLACEMENTS = [
    (re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b'), 'Bearer [REDACTED]'),
    (re.compile(r'(?i)\bsk-[A-Za-z0-9]{16,}\b'), '[REDACTED]'),
    (re.compile(r'(?i)\bghp_[A-Za-z0-9]{20,}\b'), '[REDACTED]'),
    (re.compile(r'(?i)\bAKIA[0-9A-Z]{16}\b'), '[REDACTED]'),
    (re.compile(r'(?i)\bxox[baprs]-[A-Za-z0-9-]{10,}\b'), '[REDACTED]'),
]


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


def strip_ansi(text: str) -> str:
    text = ANSI_RE.sub("", text)
    return text


def redact_line(line: str) -> str:
    def redact_json_field(match: re.Match[str]) -> str:
        value = match.group(3)
        replacement = '[REDACTED_JWT]' if JWT_VALUE_RE.fullmatch(value) else '[REDACTED]'
        return f"{match.group(1)}{match.group(2)}{replacement}{match.group(4)}"

    def redact_kv_field(match: re.Match[str]) -> str:
        value = match.group(3)
        replacement = '[REDACTED_JWT]' if JWT_VALUE_RE.fullmatch(value) else '[REDACTED]'
        return f"{match.group(1)}{match.group(2)}{replacement}{match.group(4)}"

    line = JSON_SENSITIVE_FIELD_RE.sub(redact_json_field, line)
    line = SENSITIVE_FIELD_RE.sub(redact_kv_field, line)
    line = JWT_RE.sub('[REDACTED_JWT]', line)
    for pattern, replacement in BASIC_SECRET_REPLACEMENTS:
        line = pattern.sub(replacement, line)
    return line


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0

    counts = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1

    length = len(value)
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def redact_high_entropy_line(line: str, threshold: float = 4.0) -> str:
    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0)
        if shannon_entropy(candidate) > threshold:
            return "[REDACTED_HIGH_ENTROPY]"
        return candidate

    return HIGH_ENTROPY_RE.sub(replace, line)


def sanitize_text(
    text: str,
    redact: bool = True,
    max_regex_line: int = MAX_REGEX_LINE,
    entropy_redact: bool = True,
) -> str:
    text = strip_ansi(text)
    lines = []
    for raw_line in text.splitlines():
        line = raw_line if len(raw_line) <= max_regex_line else raw_line[: max_regex_line - 3] + "..."
        if redact:
            line = redact_line(line)
            if entropy_redact:
                line = redact_high_entropy_line(line)
        lines.append(line)
    return "\n".join(lines)


def within_directory(candidate: Path, base: Path) -> bool:
    try:
        candidate.relative_to(base)
        return True
    except ValueError:
        return False


def warn(message: str) -> None:
    print(f"[compress] warning: {message}", file=sys.stderr)


def validate_input_path(
    path_str: str,
    allow_symlink_escape: bool = False,
    allowed_dirs: list[str] | None = None,
) -> Path:
    path = Path(path_str).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"input file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"input path is not a regular file: {path}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"input file is not readable: {path}")

    resolved_path = path.resolve()

    if allowed_dirs:
        resolved_allowed_dirs = []
        for directory in allowed_dirs:
            allowed_path = Path(directory).expanduser()
            if not allowed_path.exists():
                raise FileNotFoundError(f"allowed directory does not exist: {allowed_path}")
            if not allowed_path.is_dir():
                raise ValueError(f"allowed path is not a directory: {allowed_path}")
            resolved_allowed_dirs.append(allowed_path.resolve())
        if not any(within_directory(resolved_path, allowed_directory) for allowed_directory in resolved_allowed_dirs):
            raise PermissionError(
                f"refusing to read input outside allowed directories: {resolved_path}"
            )

    if path.is_symlink():
        cwd = Path.cwd().resolve()
        if not within_directory(resolved_path, cwd):
            if allow_symlink_escape:
                warn(f"following symlink outside current working directory: {path} -> {resolved_path}")
            else:
                raise PermissionError(
                    f"refusing to read symlink outside current working directory: {path} -> {resolved_path}"
                )

    return path


def read_stream_capped(stream, max_bytes: int) -> tuple[str, bool]:
    chunks = []
    total = 0
    truncated = False
    while total < max_bytes:
        chunk = stream.read(min(1024 * 1024, max_bytes - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)

    extra = stream.read(1)
    if extra:
        truncated = True

    if truncated:
        warn(f"input exceeded {max_bytes} bytes; truncating to first {max_bytes} bytes")

    data = b"".join(chunks)
    return data.decode("utf-8", errors="replace"), truncated


def read_input_text(
    file_path: str | None,
    max_bytes: int,
    allow_symlink_escape: bool = False,
    allowed_dirs: list[str] | None = None,
) -> str:
    if file_path:
        path = validate_input_path(
            file_path,
            allow_symlink_escape=allow_symlink_escape,
            allowed_dirs=allowed_dirs,
        )
        with path.open("rb") as handle:
            text, _ = read_stream_capped(handle, max_bytes)
        return text

    stdin_buffer = getattr(sys.stdin, "buffer", None)
    if stdin_buffer is None:
        return sys.stdin.read()
    text, _ = read_stream_capped(stdin_buffer, max_bytes)
    return text


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
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="Maximum input bytes to read before truncating")
    ap.add_argument("--no-redact", action="store_true", help="Disable secret redaction before compression")
    ap.add_argument("--no-entropy-redact", action="store_true", help="Disable the entropy-based fallback redaction layer")
    ap.add_argument("--allow-symlink-escape", action="store_true", help="Allow input symlinks that resolve outside the current working directory")
    ap.add_argument("--allowed-dir", action="append", default=[], help="Restrict file input to one or more allowed directories")
    args = ap.parse_args()

    if args.max_bytes <= 0:
        raise ValueError("--max-bytes must be a positive integer")
    if args.max_line <= 0:
        raise ValueError("--max-line must be a positive integer")
    if args.context < 0:
        raise ValueError("--context must be zero or a positive integer")

    text = read_input_text(
        args.file,
        args.max_bytes,
        allow_symlink_escape=args.allow_symlink_escape,
        allowed_dirs=args.allowed_dir or None,
    )
    prepared = sanitize_text(
        text,
        redact=not args.no_redact,
        max_regex_line=MAX_REGEX_LINE,
        entropy_redact=not args.no_entropy_redact,
    )

    compressed, stats = compress(prepared, max_len=args.max_line, keep_context=args.context)
    print(compressed)
    print(
        f"[compress] {stats['orig_lines']} -> {stats['new_lines']} lines "
        f"({stats['pct_cut']}% cut)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
