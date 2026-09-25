# skills

Claude Code skills, installable one at a time.

| Path | Holds |
|---|---|
| `clis/<name>/` | CLI skills: `SKILL.md`, the CLI (`<name>.py`), `src/`, `dev/tests/`, `references/` |
| `skills/<name>/` | flow skills |

## Skills

| Skill | What it does |
|---|---|
| [model-cli](clis/model-cli/SKILL.md) | Find, call and fetch results from non-Claude models (image, video, TTS, ASR, LLM) via Hugging Face, OpenRouter and Pollinations, free tiers first |

## Install

Copy a skill folder into `~/.claude/skills/<name>/`, or install it with auto-updates via skillsync:
`skillsync add https://github.com/nvaikus/skills.git clis/model-cli`
