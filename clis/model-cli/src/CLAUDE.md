# model-cli - developer notes

Entry `model-cli.py` → `src/model_cli/cli.py:main`. Python 3.9+, stdlib only except `huggingface_hub` (lazy, `hf.run` only).

## Layers
| file | owns |
|---|---|
| `http.py` | every network call (`request`; tests patch it), `HttpError` with the provider's message, retry |
| `core.py` | exit-code errors, task vocabulary (`TASKS`, `RUNNABLE`), config load/merge, output paths, magic-byte sniffing |
| `backends/<name>.py` | `NAME ENV SIGNUP`, `available(task)`, `search(query, task, free, limit)`, `lookup(id)`, `info(id)`, `run(id, task, inp, params, out, cfg)` |
| `cli.py` | argparse + `--help` epilogs (the documented surface), model resolution, guard, output |

## Invariants
- stdout = data only (TSV / `-j` JSON; `run` = one JSON object). stderr = `# ...` notes and `model-cli: <error>`.
- Exit: 0 ok, 1 failed, 2 usage/config/missing token, 3 guard refused (nothing sent), 130 interrupt.
- Tokens from env only; never logged, never in argv.
- Provider errors surface verbatim (`HttpError.body`); no silent fallback to another model.
- Output caps announce themselves on stderr.
- Search/info never need a token.
- HF `text_to_image` returns PIL: `hf._client` patches `_bytes_to_image` to identity (no Pillow). Upgrading `huggingface_hub` → re-check that patch point.

## Add a backend
Module in `backends/` with the interface above → register in `cli.BACKENDS` and `cli.PREFIX` → tests in `dev/tests/test_cli.py` with `FakeNet` routes.

## Add a task
`core.TASKS` (short name) + `core.RUNNABLE` (output kind) → per-backend `run` branch → shortcut list in `cli.build_parser` if it deserves one.

## Test
`python3 -m unittest discover -s dev/tests` (mocked HTTP, no tokens needed).
