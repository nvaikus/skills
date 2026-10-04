"""`model-cli setup`: per-backend key status (live probe), what a key unlocks, and exact steps to get and store it."""
import os
import sys
from pathlib import Path

from . import http

ENV_FILE = os.environ.get("MODEL_CLI_ENV_FILE", "~/.config/model-cli/env")
USE_KEYCHAIN = sys.platform == "darwin" and "MODEL_CLI_ENV_FILE" not in os.environ

# unlocks / free / card are one-liners for the table; steps are the exact click path (placeholders: none).
GUIDE = {
    "groq": {
        "unlocks": "asr whisper-large-v3(-turbo); llm gpt-oss-120b, llama-3.3-70b, qwen3; tts orpheus (en, ar)",
        "free": "whisper 2k req/day, 8 h audio/day, 25 MB/file; llm ~1k req/day/model; tts 100 req/day",
        "card": "no",
        "steps": ["Open https://console.groq.com/keys and sign in (Google, GitHub or email).",
                  "Create API Key -> name it model-cli -> Submit -> copy the key (shown once)."],
        "after": "TTS only: if the first call says the model needs terms acceptance, open "
                 "https://console.groq.com/playground?model=canopylabs/orpheus-v1-english and accept once.",
    },
    "gemini": {
        "unlocks": "llm + vision + audio-in (asr, summaries) gemini-3.x flash; tts gemini-3.8-flash-tts (multilingual)",
        "free": "per-model req/day at https://aistudio.google.com/rate-limit; 20 MB per request",
        "card": "no",
        "steps": ["Open https://aistudio.google.com/apikey and sign in with a Google account.",
                  "Create API key -> pick or create a Google Cloud project -> copy the key."],
        "after": "Free tier: Google may use prompts to improve its products - no secrets or customer data.",
    },
    "cloudflare": {
        "unlocks": "asr whisper-large-v3-turbo; image flux-1-schnell; tts melotts; llm gpt-oss-120b, llama",
        "free": "10k neurons/day (~200 min whisper-turbo or ~170 flux 1024px images); resets 00:00 UTC",
        "card": "no",
        "steps": ["Sign up at https://dash.cloudflare.com/sign-up (free plan).",
                  "Account ID: dash home -> account menu (...) -> Copy account ID (also shown in "
                  "AI -> Workers AI -> Use REST API).",
                  "Token: https://dash.cloudflare.com/profile/api-tokens -> Create Token -> template "
                  "'Workers AI' -> Continue to summary -> Create Token -> copy."],
    },
    "mistral": {
        "unlocks": "llm + vision mistral-small/medium/large-latest; asr voxtral-mini-latest",
        "free": "Experiment plan: ~1 req/s, monthly token cap; limits at console.mistral.ai -> Limits",
        "card": "no (phone SMS verification)",
        "steps": ["Sign up at https://console.mistral.ai and choose the free Experiment plan (verify phone by SMS).",
                  "https://console.mistral.ai/api-keys -> Create new key -> copy."],
        "after": "Experiment plan: prompts may be used for training - no secrets or customer data.",
    },
    "openrouter": {
        "unlocks": "llm + vision: every :free model (gemma, qwen, glm, llama...), openrouter/free router",
        "free": "50 req/day total on :free models (1000/day after a one-time $10 top-up), 20 req/min",
        "card": "no",
        "steps": ["Sign in at https://openrouter.ai (Google, GitHub or email).",
                  "https://openrouter.ai/settings/keys -> Create Key -> leave credit limit empty -> copy."],
    },
    "hf": {
        "unlocks": "image flux, tts kokoro, asr whisper, video, any HF model with a live provider",
        "free": "$0.10/month routed credit, then HTTP 402 until next month (one video eats it all)",
        "card": "no",
        "steps": ["Sign up at https://huggingface.co/join.",
                  "https://huggingface.co/settings/tokens -> Create new token -> Fine-grained -> tick "
                  "'Make calls to Inference Providers' -> Create token -> copy.",
                  "Once: python3 -m pip install --user huggingface_hub"],
    },
    "pollinations": {
        "unlocks": "optional: pick a model, tts, video (keyless already gives default image + llm)",
        "free": "keyless default works without a key; with a key usage is pollen-billed",
        "card": "no",
        "steps": ["https://enter.pollinations.ai -> sign in with GitHub -> Keys -> create a secret key -> copy."],
    },
}


def _probe_url(name, mod):
    return {
        "hf": ("https://huggingface.co/api/whoami-v2", "bearer"),
        "openrouter": ("https://openrouter.ai/api/v1/key", "bearer"),
        "groq": ("https://api.groq.com/openai/v1/models", "bearer"),
        "mistral": ("https://api.mistral.ai/v1/models", "bearer"),
        "gemini": ("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", "goog"),
        "cloudflare": (f"{getattr(mod, 'base', '')}/models/search?per_page=1", "bearer"),
    }.get(name)


def status(name, mod, probe=True):
    """-> 'ok' | 'missing <VARS>' | 'invalid (HTTP n: msg)' | 'set (unchecked)'."""
    envs = getattr(mod, "ENVS", None) or [mod.ENV]
    missing = [e for e in envs if not os.environ.get(e)]
    if missing:
        return "missing " + ",".join(missing) + (" (optional: keyless default works)" if name == "pollinations" else "")
    target = _probe_url(name, mod)
    if not probe or not target:
        return "set (unchecked)"
    url, kind = target
    tok = os.environ[mod.ENV]
    hdrs = {"x-goog-api-key": tok} if kind == "goog" else {"Authorization": f"Bearer {tok}"}
    try:
        http.request("GET", url, headers=hdrs, timeout=20)
        return "ok"
    except http.HttpError as e:
        return f"invalid (HTTP {e.status}: {str(e.body)[:120]})"
    except OSError as e:
        return f"set (probe failed: {e})"


def store_steps(envs):
    f = ENV_FILE
    if os.name == "nt":
        return ["Store: Start -> 'Edit environment variables for your account' -> New -> "
                + " and ".join(f"{e}=<value>" for e in envs) + " -> OK; open a new terminal.",
                "Never paste the key into chat, a command line or the skill folder."]
    if USE_KEYCHAIN:
        adds = " && ".join(f'security add-generic-password -U -a "$USER" -s {e} -w' for e in envs)
        exports = "\n".join(f'export {e}="$(security find-generic-password -a "$USER" -s {e} -w 2>/dev/null)"'
                             for e in envs)
        return [f"Store in macOS Keychain (the user runs it; -w with no value prompts, so the key stays out of "
                f"argv and chat): {adds}",
                f"Once per key, add to ~/.zshrc, then open a new shell:\n{exports}"]
    lines = "; ".join(f"export {e}='<value>'" for e in envs)
    return [f"Store (never in chat, argv or the skill folder): mkdir -p {Path(f).parent} && touch {f} && "
            f"chmod 600 {f}; open {f} in an editor and add: {lines}",
            f"Once per machine, source it from the shell rc: echo '[ -f {f} ] && . {f}' >> ~/.zshrc "
            "(bash: ~/.bashrc); then open a new shell."]


def detail(name, mod, st):
    g = GUIDE.get(name, {})
    envs = getattr(mod, "ENVS", None) or [mod.ENV]
    steps = list(g.get("steps", [])) + store_steps(envs) + [f"Verify: model-cli setup {name}  -> status ok"]
    if g.get("after"):
        steps.append(g["after"])
    return {"backend": name, "status": st, "env": ",".join(envs), "unlocks": g.get("unlocks", ""),
            "free": g.get("free", ""), "card": g.get("card", ""), "signup": mod.SIGNUP,
            "steps": [f"{i}. {s}" for i, s in enumerate(steps, 1)]}
