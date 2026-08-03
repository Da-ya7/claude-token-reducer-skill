# token-reducer
Cut log noise before Claude ever sees it.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Stars](https://img.shields.io/github/stars/dhayalan/token-reducer?style=flat&label=Stars)](https://github.com/dhayalan/token-reducer) [![Issues](https://img.shields.io/github/issues/dhayalan/token-reducer?style=flat&label=Issues)](https://github.com/dhayalan/token-reducer/issues) [![Built for Claude](https://img.shields.io/badge/Built%20for%20Claude-111111?style=flat&logo=anthropic&logoColor=white)](https://claude.ai)

## Before / After

### Before
```text
Resolving package metadata...
Downloading wheels 12%|█████▌                          | 122/1014
Downloading wheels 13%|█████▋                          | 133/1014
Downloading wheels 13%|█████▋                          | 133/1014
test_login_flow ... ok
test_login_flow ... ok
test_login_flow ... ok
Traceback (most recent call last):
  File "/workspace/app/tests/test_parser.py", line 184, in test_parse
    assert output[812] == "done"
RuntimeError: failed to parse line 812
```

### After
```text
... 3 passing/ok line(s) collapsed ...
Traceback (most recent call last):
    ... 14 frame(s) omitted ...
RuntimeError: failed to parse line 812
[compress] 812 -> 96 lines (88% cut)
```

## Why this exists

Logs are token-eating garbage until you strip them down. token-reducer keeps the signal and throws away the duplicate fluff so Claude reads faster, cheaper, and with less context waste.

## Install

```bash
curl -fsSL <placeholder-raw-url> | bash
```

## Usage

```bash
python scripts/compress.py mylog.txt
```

## How it works

- Filter: drops blank lines, progress bars, separators, and other pure noise.
- Group: collapses repeated pass lines, warnings, and scattered duplicates into counts.
- Truncate: shortens long lines and trims traceback blocks to the useful frames.
- Dedupe: merges consecutive identical lines into one line with an `xN` count.

## Credits

Built by Dhayalan (aka Joy)

## License

MIT license: [LICENSE](LICENSE)
