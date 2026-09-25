---
name: model-cli
description: Finds, calls and fetches results from non-Claude AI models - image, video, text-to-speech, speech-to-text, music and other LLMs, open source included - through one CLI over Hugging Face Inference Providers, OpenRouter and keyless Pollinations, free tiers first. Use when a task needs a generated image/video/audio file, a transcription, a second-opinion or cheaper LLM, or when the user asks which model can do X and wants to try it. Triggers - generate an image, make a picture, text to image, video generation, TTS, voice over, read this aloud, transcribe audio, whisper, speech to text, ask another model, GPT/Gemini/Llama/Qwen/Flux/Kokoro, open source model, Hugging Face model, OpenRouter, free model, model-cli. NOT for calling Claude itself (that's the claude-api skill).
---

# model-cli

One CLI: `search` (live catalogs) → `info` (parameters) → `run` / shortcut → JSON with a file path or text.

```
model-cli doctor                              # which tokens are set, what runs now
model-cli search <words> --task image|video|tts|asr|llm|vision|audio
model-cli info <model>
model-cli run <model> "<prompt>" | <file> [-o path] [--param k=v]
model-cli image|video|tts|asr|llm <prompt|file> [-m model] [-o path]
```

Windows: `python model-cli.py ...` or `model-cli.cmd`. Everything else - flags, exit codes, examples - is in `model-cli <verb> --help`.

## Contract

- `run` / shortcuts print one JSON object: `{"path"|"text", "model", "backend", "task", "cost", "duration_ms"}`. Read the file at `path`; nothing else needs parsing.
- Result files land in `/tmp/model-cli/` (throwaway). Anything the user keeps → pass `-o <path>`; never copy from `/tmp` later.
- Model refs: `hf:<org/name>`, `openrouter:<id>`, `pollinations:<name>`, a config alias, or a bare id (OpenRouter catalog first, then HF).
- Parameters are passthrough: take names from `info`, pass `--param k=v` (JSON-typed) or `--params-json`. A rejection comes back with the provider's text verbatim - fix the param, don't guess another backend.
- Exit `2` + signup URL = missing token: tell the user which env var to set; do not retry. Exit `3` = paid model refused under `free_only`: pick a free one from `search`, or `--paid` only when the user approved spending.

## Tokens and config

- Env only: `HF_TOKEN`, `OPENROUTER_API_KEY`, optional `POLLINATIONS_API_KEY`. Never put a token in argv or a file inside the skill; a `chmod 600` env file sourced from the shell rc is the recommended home.
- Config: `~/.claude/model-cli/config.json` (copy `config.example.json`): `free_only`, `hf_provider`, `defaults.<task>` (fallback list - first entry whose backend has a token wins), `aliases`. Going paid = `"free_only": false`, no code change.
- Dependency: `hf` runs need `huggingface_hub` (`python3 -m pip install --user huggingface_hub`); search, info, OpenRouter and Pollinations are stdlib only.

| when | read |
|---|---|
| choosing a backend/model under the free budget, or a run fails with 402/429 | `references/free-tiers.md` |

## Memory

User-local facts: `~/.claude/model-cli/`, outside the skill — updates never
touch it. Root `memory.md`: read at run start, create on first write. Root =
every-run facts + one pointer per topic: `<trigger> → memory/<topic>.md`.
Sub-file: read only when its trigger hits.

Anything that cost a question, burned context, or took retries to learn —
persist immediately: future runs must not pay it again. Bucket at write: every
run → root; situation X → its sub-file + pointer in root. One-line imperatives;
reason only as a short parenthesis preventing a wrong action. Fact useful to
every user = defect (below), not memory; unsure → memory, proven general →
into the skill, out of the file.

- Typical entries: a model that worked well for a task, a provider that failed repeatedly, the user's preferred voice/size.

## Fix on friction

Friction is a DEFECT of this skill — never work around it silently. Capability
gap or not AI-friendly (confusing behavior, context-flooding output, noisy
errors, stale instructions) — same reflex:

- Fix cheaper than a ticket (one-line fact, typo, small flag) → fix it here,
  move on.
- Bigger → background teammate (`model: "opus"`), one-message ticket: fact +
  proving command and output. It fixes the broken layer — SKILL.md,
  `references/`, `scripts/`, or the tool underneath.

Continue in parallel only if not blocked; blocked → fix inline or wait.
Local skill: edit in place. If skillsync manages it (`skillsync list`), edit the clone and publish back instead.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/clis/model-cli/SKILL.md
