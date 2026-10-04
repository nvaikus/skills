---
name: model-cli
description: Finds, calls and fetches results from non-Claude AI models - image, video, text-to-speech, speech-to-text, music and other LLMs, open source included - through one CLI over free tiers first (Groq, Google Gemini, Cloudflare Workers AI, Mistral, OpenRouter, Hugging Face, keyless Pollinations), with guided key onboarding. Use when a task needs a generated image/video/audio file, a transcription, a second-opinion or cheaper LLM, or when the user asks which model can do X and wants to try it. Triggers - generate an image, make a picture, text to image, video generation, TTS, voice over, read this aloud, transcribe audio, voice message, whisper, speech to text, ask another model, GPT/Gemini/Llama/Qwen/Flux/Kokoro, open source model, Hugging Face model, OpenRouter, Groq, Gemini API, free model, set up an AI API key, model-cli. NOT for calling Claude itself (that's the claude-api skill).
---

# model-cli

One CLI: `search` (live catalogs) → `info` (parameters) → `run` / shortcut → JSON with a file path or text.

```
model-cli setup [backend]                     # key status (live check), what it unlocks, how to get it
model-cli doctor                              # tokens, config, OpenRouter key limits
model-cli search <words> --task image|video|tts|asr|llm|vision|audio
model-cli info <model>
model-cli run <model> "<prompt>" | <file> [-o path] [--param k=v]
model-cli image|video|tts|asr|llm <prompt|file> [-m model] [-o path]
```

Windows: `python model-cli.py ...` or `model-cli.cmd`. Everything else - flags, exit codes, examples - is in `model-cli <verb> --help`.

## Contract

- `run` / shortcuts print one JSON object: `{"path"|"text", "model", "backend", "task", "cost", "duration_ms"}`. Read the file at `path`; nothing else needs parsing.
- Result files land in `/tmp/model-cli/` (throwaway). Anything the user keeps → pass `-o <path>`; never copy from `/tmp` later.
- Model refs: `<backend>:<id>` (`hf`, `openrouter`, `pollinations`, `groq`, `gemini`, `cloudflare`, `mistral`), a config alias, or a bare id (OpenRouter catalog first, then HF).
- Parameters are passthrough: take names from `info`, pass `--param k=v` (JSON-typed) or `--params-json`. A rejection comes back with the provider's text verbatim - fix the param, don't guess another backend.
- Exit `2` + signup URL = missing token: run `model-cli setup <backend>` and walk the user through its steps (the user pastes the key into the env file, never into chat); do not retry before `setup` shows `ok`. Exit `3` = paid model refused under `free_only`: pick a free one from `search`, or `--paid` only when the user approved spending.

## Tokens and config

- Env only (full list + signup: `model-cli setup`). Never put a token in argv, chat or a file inside the skill; macOS: Keychain + an `export X="$(security find-generic-password ...)"` line in `~/.zshrc`; elsewhere (or with `MODEL_CLI_ENV_FILE` set) a `chmod 600` env file sourced from the shell rc.
- ASR works free with any of Groq, Gemini, Cloudflare, Mistral; ffmpeg converts/splits audio to fit each cap.
- Config: `~/.claude/model-cli/config.json` (copy `config.example.json`): `free_only`, `hf_provider`, `defaults.<task>` (fallback list - first entry whose backend has a token wins), `aliases`. Going paid = `"free_only": false`, no code change.
- Dependency: `hf` runs need `huggingface_hub` (`python3 -m pip install --user huggingface_hub`); everything else is stdlib; audio conversion needs `ffmpeg` on PATH.

| when | read |
|---|---|
| choosing a backend/model under the free budget, a run fails with 402/429, or the user asks which free AI API to sign up for | `references/free-tiers.md` |

## Memory

`~/.claude/model-cli/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: a model that worked well for a task, a provider that failed repeatedly, the user's preferred voice/size.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/model-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
