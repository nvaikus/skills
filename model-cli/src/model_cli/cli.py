"""model-cli: find, call and fetch results from non-Claude models (HF, OpenRouter, Pollinations, Groq, Gemini,
Cloudflare Workers AI, Mistral)."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import http, onboarding
from .backends import cloudflare, compat, gemini, hf, openrouter, pollinations
from .core import (CliError, GuardRefused, MissingToken, UsageError, CONFIG_PATH, OUT_DIR, RUNNABLE,
                   TASKS, canon_task, load_config, short_task)

BACKENDS = {"hf": hf, "openrouter": openrouter, "pollinations": pollinations, "groq": compat.groq,
            "gemini": gemini.backend, "cloudflare": cloudflare.backend, "mistral": compat.mistral}
PREFIX = {"hf": "hf", "huggingface": "hf", "openrouter": "openrouter", "or": "openrouter",
          "pollinations": "pollinations", "poll": "pollinations", "groq": "groq", "gemini": "gemini",
          "google": "gemini", "cloudflare": "cloudflare", "cf": "cloudflare", "mistral": "mistral"}
SEARCH_FIELDS = ["id", "backend", "task", "free", "price", "popularity", "providers"]
FILE_PROMPT = {"audio": "Transcribe this audio verbatim in its original language. Output only the transcript.",
               "image": "Describe this image.",
               "video": "Describe this video."}


# ---- output -----------------------------------------------------------------

def emit(rows, fields, args):
    """Data on stdout: TSV (default) or JSON (-j). Dict rows only."""
    if args.fields:
        fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    if args.json:
        out = [{f: r.get(f) for f in fields} for r in rows]
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if not args.no_header:
        print("\t".join(fields))
    for r in rows:
        print("\t".join("" if r.get(f) is None else str(r.get(f)).replace("\t", " ").replace("\n", " ")
                        for f in fields))


def note(msg):
    sys.stdout.flush()  # keep '# ...' notes after the data they describe when both go to one pipe
    print(f"# {msg}", file=sys.stderr)


# ---- model resolution -------------------------------------------------------

def split_ref(ref, backend=None):
    if ":" in ref:
        head, rest = ref.split(":", 1)
        if head.lower() in PREFIX:
            return PREFIX[head.lower()], rest
    return (PREFIX.get(backend, backend) if backend else None), ref


def resolve(ref, cfg, backend=None):
    """-> (backend_name, model_id, meta). meta from the backend's live lookup."""
    ref = cfg["aliases"].get(ref, ref)
    be, mid = split_ref(ref, backend)
    if be:
        if be not in BACKENDS:
            raise UsageError(f"unknown backend {be}; one of {', '.join(BACKENDS)}")
        meta = BACKENDS[be].lookup(mid)
        if not meta:
            raise CliError(f"{be}: model not found: {mid} (try: model-cli search {mid.split('/')[-1]})")
        return be, mid, meta
    for be in ("openrouter", "hf"):  # OpenRouter first: one cached catalog fetch, owns :free ids
        meta = BACKENDS[be].lookup(mid)
        if meta:
            return be, mid, meta
    raise CliError(f"model not found on any backend: {mid} (try: model-cli search {mid.split('/')[-1]})")


def parse_params(args):
    params = {}
    if args.params_json:
        try:
            params.update(json.loads(args.params_json))
        except ValueError as e:
            raise UsageError(f"--params-json is not valid JSON: {e}") from None
    for kv in args.param or []:
        if "=" not in kv:
            raise UsageError(f"--param expects k=v, got {kv!r}")
        k, v = kv.split("=", 1)
        try:
            params[k] = json.loads(v)  # 7 -> int, 0.5 -> float, true -> bool, [..] -> list
        except ValueError:
            params[k] = v
    return params


def read_input(value, prompt):
    if value == "-":
        return {"text": sys.stdin.read()}
    if _is_file(value):
        p = Path(value).expanduser()
        kind = _kind(p)
        return {"file": str(p), "kind": kind, "text": prompt or FILE_PROMPT.get(kind, "")}
    return {"text": value if not prompt else f"{prompt}\n\n{value}"}


def _is_file(value):
    """A prompt is not a path: a long one raises ENAMETOOLONG from stat()."""
    try:
        return Path(value).expanduser().is_file()
    except (OSError, ValueError):
        return False


def _kind(p):
    import mimetypes
    mime = mimetypes.guess_type(str(p))[0] or ""
    return mime.split("/")[0] if mime else "file"


# ---- verbs ------------------------------------------------------------------

def cmd_search(args, cfg):
    task = canon_task(args.task)
    names = _backends(args.backend)
    free = args.free or (cfg.get("free_only") and not args.all)
    per = {}
    for n in names:
        try:
            rows = BACKENDS[n].search(" ".join(args.query).strip(), task, free, args.limit)
        except http.HttpError as e:
            note(f"{n}: search failed: HTTP {e.status}: {e.body}")
            continue
        if free:
            rows = [r for r in rows if r["free"] in ("yes", "credit", "quota")]
        per[n] = rows
    merged, i = [], 0  # interleave by per-backend rank
    while any(i < len(r) for r in per.values()):
        merged += [r[i] for r in per.values() if i < len(r)]
        i += 1
    total = len(merged)
    merged = merged[:args.limit]
    emit(merged, SEARCH_FIELDS, args)
    if total > len(merged) or any(len(r) >= args.limit for r in per.values()):
        note(f"showing {len(merged)} (limit {args.limit}); more may exist - raise --limit or narrow the query")
    if free:
        note("free-only filter on (credit = hf monthly credits, quota = free tier with daily limits); "
             "--all shows paid/unknown models")
    if not merged:
        return 1


def _backends(spec):
    if not spec:
        return list(BACKENDS)
    out = []
    for s in spec.split(","):
        n = PREFIX.get(s.strip().lower())
        if not n:
            raise UsageError(f"unknown backend {s!r}; one of {', '.join(BACKENDS)}")
        out.append(n)
    return out


def cmd_info(args, cfg):
    be, mid, _ = resolve(args.model, cfg, args.backend)
    meta = BACKENDS[be].info(mid)
    params = meta.pop("params", [])
    meta.pop("_raw", None)
    meta.pop("task_full", None)
    if args.json:
        meta["params"] = params
        print(json.dumps(meta, ensure_ascii=False, indent=1))
        return
    for k, v in meta.items():
        if v not in (None, "") and k != "is_free":
            note(f"{k}: {v}")
    emit(params, ["name", "type", "default", "description"], args)
    if not params:
        note("no parameter schema published; --param values are passed through as-is")


def cmd_run(args, cfg, task_hint=None):
    params = parse_params(args)
    if task_hint and not args.model:
        be, mid, meta = _default(task_hint, cfg)
    else:
        be, mid, meta = resolve(args.model, cfg, args.backend)
    task = canon_task(getattr(args, "task", None)) or task_hint or meta.get("task_full")
    if not task:
        raise UsageError(f"{be}:{mid}: task unknown - pass --task ({', '.join(TASKS)})")
    if task not in RUNNABLE:
        raise UsageError(f"task {task} is not runnable yet; runnable: {', '.join(short_task(t) for t in RUNNABLE)}")
    if cfg.get("free_only") and not args.paid and meta.get("is_free") is False:
        raise GuardRefused(f"{be}:{mid} is paid ({meta.get('price')}); free_only is on - pass --paid or "
                           f"set \"free_only\": false in {CONFIG_PATH}")
    _chat_flags(args, be, mid, params)
    inp = read_input(args.input, args.prompt)
    if args.ref:
        inp["refs"] = _refs(args.ref, be, mid, task)
    t0 = time.monotonic()
    res = BACKENDS[be].run(mid, task, inp, params, args.output, cfg)
    if args.output and "text" in res and "path" not in res:
        p = Path(args.output).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(res["text"])
        res["path"] = str(p)
    out = {k: res[k] for k in ("path", "text") if k in res}
    out.update({"model": f"{be}:{mid}", "backend": be, "task": short_task(task), "cost": res.get("cost"),
                "duration_ms": int((time.monotonic() - t0) * 1000)})
    if res.get("served_by"):
        out["served_by"] = res["served_by"]
    if args.fields:
        out = {f: out.get(f) for f in args.fields.split(",")}
    print(json.dumps(out, ensure_ascii=False))


def _refs(paths, be, mid, task):
    """--ref: extra input images, sent after the main input. Unsupported backend/task -> usage error, never dropped."""
    takes = getattr(BACKENDS[be], "takes_refs", None)
    if not (takes and takes(task)):
        raise UsageError(f"{be}:{mid} ({short_task(task)}) takes one input, not --ref images; multi-image input: "
                         "openrouter chat/image models, gemini/groq/mistral/cloudflare/hf chat models")
    out = []
    for r in paths:
        p = Path(r).expanduser()
        if not _is_file(r):
            raise UsageError(f"--ref: no such file: {r}")
        if _kind(p) != "image":
            raise UsageError(f"--ref takes images, not {_kind(p)}: {r}")
        out.append(str(p))
    return out


def _chat_flags(args, be, mid, params):
    """--max-tokens / --no-reasoning -> chat params; explicit --param wins."""
    if args.max_tokens:
        params.setdefault("max_tokens", args.max_tokens)
    if args.no_reasoning:
        hook = getattr(BACKENDS[be], "no_reasoning", None)
        if be == "openrouter":
            params.setdefault("reasoning", {"enabled": False})
        elif not (hook and hook(mid, params)):
            note(f"--no-reasoning ignored on {be}:{mid}")


def _default(task, cfg, lookup=True):
    short = short_task(task)
    refs = cfg["defaults"].get(short) or []
    if isinstance(refs, str):
        refs = [refs]
    if not refs:
        raise UsageError(f"no default model for {short} in {CONFIG_PATH}; pass -m MODEL")
    for ref in refs:
        be, _ = split_ref(cfg["aliases"].get(ref, ref))
        if be and BACKENDS[be].available(task):
            return resolve(ref, cfg) if lookup else (be, split_ref(cfg["aliases"].get(ref, ref))[1], {})
    need = []
    for ref in refs:
        be, _ = split_ref(cfg["aliases"].get(ref, ref))
        mod = BACKENDS.get(be)
        if mod and mod.ENV not in [n[0] for n in need]:
            need.append((",".join(getattr(mod, "ENVS", None) or [mod.ENV]), mod.SIGNUP))
    if not need:
        raise UsageError(f"defaults.{short} in {CONFIG_PATH} names no known backend; pass -m MODEL")
    raise MissingToken(need[0][0], need[0][1], more=need[1:], hint="model-cli setup")


def cmd_setup(args, cfg):
    names = _backends(args.backend) if args.backend else list(BACKENDS)
    rows = [onboarding.detail(n, BACKENDS[n], onboarding.status(n, BACKENDS[n], probe=not args.no_probe))
            for n in names]
    if args.json:
        print(json.dumps(rows if len(rows) > 1 else rows[0], ensure_ascii=False, indent=1))
        return
    if len(rows) == 1:
        r = rows[0]
        for k in ("backend", "status", "env", "unlocks", "free", "card", "signup"):
            print(f"{k}: {r[k]}")
        print("steps:")
        for s in r["steps"]:
            print(f"  {s}")
        return
    emit(rows, ["backend", "status", "env", "unlocks", "free", "card"], args)
    note("exact steps for one backend: model-cli setup <backend>; no key ever goes into chat or argv")
    now = []
    for short in ("asr", "llm", "tts", "image", "video"):
        try:
            be, mid, _ = _default(TASKS[short], cfg, lookup=False)
            now.append(f"{short}={be}:{mid}")
        except CliError:
            now.append(f"{short}=-")
    note("shortcut defaults now (first backend with a key): " + ", ".join(now))
    todo = [r["backend"] for r in rows if r["status"].startswith(("missing", "invalid")) and
            "optional" not in r["status"]]
    if todo:
        note("not ready: " + ", ".join(todo))


def cmd_doctor(args, cfg):
    rows = []
    for n, mod in BACKENDS.items():
        envs = getattr(mod, "ENVS", None) or [mod.ENV]
        rows.append({"backend": n, "env": ",".join(envs),
                     "token": "set" if all(os.environ.get(e) for e in envs) else "missing",
                     "runs_now": ",".join(short_task(t) for t in RUNNABLE if mod.available(t)) or "-",
                     "signup": mod.SIGNUP})
    emit(rows, ["backend", "env", "token", "runs_now", "signup"], args)
    note(f"config: {CONFIG_PATH} ({'found' if CONFIG_PATH.exists() else 'defaults'}); free_only={cfg.get('free_only')}")
    note(f"output dir (throwaway): {OUT_DIR}")
    if os.environ.get(openrouter.ENV):
        try:
            k = http.get_json(f"{openrouter.BASE}/key",
                              headers={"Authorization": f"Bearer {os.environ[openrouter.ENV]}"})["data"]
            note("openrouter key: " + json.dumps(k))
        except http.HttpError as e:
            note(f"openrouter key check failed: HTTP {e.status}: {e.body}")


# ---- parser -----------------------------------------------------------------

EPILOG = {
    "main": """contract: data on stdout (TSV, -j JSON; run prints one JSON object), diagnostics on stderr as '# ...'.
exit: 0 ok, 1 failed, 2 usage/config/missing token, 3 guard refused (paid model, nothing sent), 130 interrupt.
tokens (env only): GROQ_API_KEY, GEMINI_API_KEY, CLOUDFLARE_API_TOKEN+CLOUDFLARE_ACCOUNT_ID, MISTRAL_API_KEY,
  OPENROUTER_API_KEY, HF_TOKEN, POLLINATIONS_API_KEY (optional). How to get each: model-cli setup [backend].
model refs: <backend>:<id> (hf, openrouter|or, pollinations, groq, gemini, cloudflare|cf, mistral), a config
  alias, or a bare id (OpenRouter, then HF).

examples:
  model-cli setup
  model-cli setup groq
  model-cli asr ./voice.ogg
  model-cli doctor
  model-cli search flux --task image
  model-cli info hf:black-forest-labs/FLUX.1-schnell
  model-cli image "a red fox, watercolor" -o ./fox.png
  model-cli llm "summarize: ..." -m openrouter:z-ai/glm-5.2:free""",
    "search": """Live query: HF Hub (models with a live inference provider), OpenRouter catalog, Pollinations catalog.
free column: yes = zero price; credit = HF monthly credits; quota = free tier with daily/minute limits
(groq, gemini, cloudflare, mistral: curated free list, plus the live list when a key is set); key = needs
POLLINATIONS_API_KEY; unknown = not in the curated free list; no = paid.
popularity: HF likes; Pollinations request count; OpenRouter has none (ranked by name match, newest first).
free_only config on -> paid rows hidden unless --all.

examples:
  model-cli search --task tts
  model-cli search gemini flash --task vision
  model-cli search whisper --task asr --backend hf
  model-cli search qwen --task llm --free -j --fields id,price
  model-cli search "" --task image --backend openrouter --all""",
    "setup": """No argument: one row per backend - status (ok | missing VAR | invalid (HTTP ..) - live key probe),
env vars, what the key unlocks, free limits, card needed. Then '# shortcut defaults now': the model each shortcut uses today.
With a backend: status + numbered steps: signup URL, key creation click path, where to store it (chmod 600 env
file sourced from the shell rc; MODEL_CLI_ENV_FILE overrides the suggested path), verify command.
Walk the user through the steps; the user pastes the key into the env file - never into chat.

examples:
  model-cli setup
  model-cli setup gemini
  model-cli setup --no-probe -j""",
    "info": """Parameters come from the HF task input schema (types) or OpenRouter supported_parameters (names only).
Pass them to run via --param k=v; anything not listed is passed through and the provider's error is shown verbatim.

examples:
  model-cli info hf:hexgrad/Kokoro-82M
  model-cli info openrouter/free -j""",
    "run": """Task comes from model metadata; --task overrides (needed for pollinations:default).
input: prompt text, '-' for stdin, or a file path (asr audio; image to a vision model; audio/pdf to openrouter
  or gemini; with --prompt).
--ref IMAGE (repeatable): more images in the same message, input = image 1, refs = image 2, 3, ... - multi-reference
  editing on openrouter image models, comparison on chat/vision models. Other backends/tasks: exit 2, nothing sent.
asr audio: any format; ffmpeg transcodes to Opus and splits into chunks when a backend's format/size cap needs it
  (groq/mistral 24 MB, cloudflare 15 MB, gemini 14 MB); chunk texts are joined.
--no-reasoning: openrouter reasoning off; groq gpt-oss effort low / qwen none; gemini thinking_level low.
reasoning models: output <=800 tokens can come back empty (thinking ate the budget) -> --no-reasoning or a bigger --max-tokens.
429/5xx: retried with 4/8(/16) s backoff (OpenRouter 3x, groq/gemini/mistral 2x).
Output file: -o PATH (dir or file) or a throwaway file in /tmp/model-cli/. LLM text: in JSON; -o also writes it to a file.
stdout: {"path"|"text", "model", "backend", "task", "cost", "duration_ms"}; cost null = not reported (HF: taken from monthly credits).

examples:
  model-cli run hf:black-forest-labs/FLUX.1-schnell "isometric castle" --param num_inference_steps=4 --param width=512
  model-cli run openrouter:google/gemma-4-31b-it:free photo.jpg --prompt "what breed is this dog?"
  model-cli run or:google/gemini-3-pro-image room2.jpg --ref room1.jpg --prompt "furnish image 1 with the same
    sofa and rug as image 2" --paid -o room2-furnished.png
  model-cli run dots-studio/dots-3-note-preview:free thumb.jpg --prompt "classify" --no-reasoning --max-tokens 300
  model-cli run whisper ./meeting.mp3 -o ./meeting.txt
  model-cli run groq:whisper-large-v3 ./memo.ogg --param language=ru
  model-cli run gemini:gemini-3.5-flash ./call.m4a --prompt "summarize with action items"
  model-cli run gemini:gemini-3.8-flash-tts "Hello there" --param voice=Puck -o hi.wav
  model-cli run pollinations:default "a lighthouse at dusk" --task image""",
}


def _common(p):
    p.add_argument("-j", "--json", action="store_true", help="JSON output")
    p.add_argument("--fields", help="comma-separated output fields")
    p.add_argument("--no-header", action="store_true", help="TSV without header row")


def _run_opts(p, model_positional):
    if model_positional:
        p.add_argument("model", help="model ref (hf:org/name, openrouter:id, pollinations:name, alias)")
    else:
        p.add_argument("-m", "--model", help="model ref; default = first usable entry of config defaults.<task>")
    p.add_argument("input", help="prompt text, '-' for stdin, or an input file path")
    p.add_argument("-o", "--output", help="save result here (file or dir); default throwaway /tmp/model-cli/")
    p.add_argument("--prompt", help="instruction text sent with a file input")
    p.add_argument("--ref", action="append", metavar="IMAGE",
                   help="extra reference image, repeatable; sent after the input in order (image 2, 3, ...)")
    p.add_argument("--param", action="append", metavar="K=V", help="model parameter, repeatable, JSON-typed")
    p.add_argument("--params-json", metavar="JSON", help="parameters as one JSON object")
    p.add_argument("--backend", help="force backend for a bare model id")
    p.add_argument("--max-tokens", type=int, metavar="N", help="chat output cap (reasoning counts toward it)")
    p.add_argument("--no-reasoning", action="store_true",
                   help="turn model thinking off/low (openrouter, groq, gemini); much faster")
    p.add_argument("--paid", action="store_true", help="allow a paid model despite free_only")
    _common(p)


def build_parser():
    fmt = argparse.RawDescriptionHelpFormatter
    ap = argparse.ArgumentParser(prog="model-cli", description=__doc__, epilog=EPILOG["main"], formatter_class=fmt)
    sub = ap.add_subparsers(dest="verb", metavar="VERB")
    sp = sub.add_parser("search", help="find models live", epilog=EPILOG["search"], formatter_class=fmt)
    sp.add_argument("query", nargs="*", default=[], help="words matched against id/name (all must match)")
    sp.add_argument("--task", help=f"{', '.join(TASKS)} or any HF pipeline tag")
    sp.add_argument("--free", action="store_true", help="free rows only (default when free_only is on)")
    sp.add_argument("--all", action="store_true", help="include paid rows despite free_only")
    sp.add_argument("--backend", help="comma list: hf,openrouter,pollinations")
    sp.add_argument("--limit", type=int, default=15, help="max rows (default 15)")
    _common(sp)
    ip = sub.add_parser("info", help="model metadata + parameters", epilog=EPILOG["info"], formatter_class=fmt)
    ip.add_argument("model")
    ip.add_argument("--backend")
    _common(ip)
    rp = sub.add_parser("run", help="call a model", epilog=EPILOG["run"], formatter_class=fmt)
    _run_opts(rp, True)
    rp.add_argument("--task", help="override task (image, llm, tts, asr, video, ...)")
    for short in ("image", "video", "tts", "asr", "llm"):
        s = sub.add_parser(short, help=f"{TASKS[short]} with the configured default model",
                           epilog=f"Default model: first usable entry of config defaults.{short}. "
                                  f"Same output as run.\n\nexample:\n  model-cli {short} "
                                  + {"image": '"a red fox" -o fox.png\n  model-cli image room2.jpg --ref room1.jpg '
                                              '--prompt "same furniture as image 2" -m or:google/gemini-3-pro-image',
                                     "video": '"waves at sunset"',
                                     "tts": '"Hello there" -o hi.wav', "asr": "./talk.mp3",
                                     "llm": '"explain RAID 5 in two lines"'}[short],
                           formatter_class=fmt)
        _run_opts(s, False)
    dp = sub.add_parser("doctor", help="tokens, usable tasks, config, OpenRouter key limits")
    _common(dp)
    up = sub.add_parser("setup", help="onboarding: key status per backend, what it unlocks, how to get it",
                        epilog=EPILOG["setup"], formatter_class=fmt)
    up.add_argument("backend", nargs="?", help="one backend -> numbered steps (signup, key, env var, store, verify)")
    up.add_argument("--no-probe", action="store_true", help="skip the live key check")
    _common(up)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.verb:
        ap.print_help()
        return 2
    try:
        cfg = load_config()
        if args.verb == "search":
            return cmd_search(args, cfg) or 0
        if args.verb == "info":
            return cmd_info(args, cfg) or 0
        if args.verb == "setup":
            return cmd_setup(args, cfg) or 0
        if args.verb == "doctor":
            return cmd_doctor(args, cfg) or 0
        if args.verb == "run":
            return cmd_run(args, cfg) or 0
        return cmd_run(args, cfg, task_hint=TASKS[args.verb]) or 0
    except CliError as e:
        print(f"model-cli: {e}", file=sys.stderr)
        return e.code
    except http.HttpError as e:
        print(f"model-cli: HTTP {e.status} from {e.url}: {e.body}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"model-cli: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
