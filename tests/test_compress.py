# Run with: pytest tests/test_compress.py -v

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.compress import read_input_text, redact_line, validate_input_path


def test_bearer_token_is_redacted() -> None:
    line = 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234567890'

    assert redact_line(line) == 'Authorization: Bearer [REDACTED]'


def test_api_key_field_is_redacted() -> None:
    line = 'api_key: "abc123def456ghi789"'

    assert redact_line(line) == 'api_key: "[REDACTED]"'


def test_jwt_is_redacted_as_jwt() -> None:
    line = 'token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc123def456.zyx987wvu654'

    assert redact_line(line) == 'token=[REDACTED_JWT]'


def test_commit_sha_without_secret_context_is_not_redacted() -> None:
    sha = '0123456789abcdef0123456789abcdef01234567'

    assert redact_line(f'git revision {sha}') == f'git revision {sha}'


@pytest.mark.skipif(not hasattr(os, 'symlink'), reason='symlink creation is not supported on this platform')
def test_symlink_escape_is_blocked_by_default_and_allowed_with_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    outside_dir = tmp_path / 'outside'
    outside_dir.mkdir()
    outside_file = outside_dir / 'secret.log'
    outside_file.write_text('outside content', encoding='utf-8')

    link = cwd / 'escape.log'
    try:
        link.symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation is not permitted in this environment')

    monkeypatch.chdir(cwd)

    with pytest.raises(PermissionError):
        validate_input_path(str(link))

    validated = validate_input_path(str(link), allow_symlink_escape=True)
    assert validated == link
    assert read_input_text(str(link), 1024, allow_symlink_escape=True) == 'outside content'