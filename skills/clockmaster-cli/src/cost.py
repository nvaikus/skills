"""What a run spent, in USD — two sources, summed when both exist:

1. the claude transcript of the run's session: the command adopted
   $TASK_SESSION_ID (`claude -p --session-id "$TASK_SESSION_ID" …`), so
   ~/.claude/projects/<workdir slug>/<sessionId>.jsonl exists;
2. `TASK_COST_USD=<number>` lines the command printed itself (a script that
   calls claude several times reports each call).

Unknown is None, never 0.0: an unpriced model or a run that reported nothing is
not free. Results are cached by (path, mtime, size) — a finished file never
changes, and the UI polls.
"""
import json
import re

import identity

# USD per million tokens (input, output). Not listed = not priced.
PRICES = {
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# multiples of the input price
WRITE_5M, WRITE_1H, READ = 1.25, 2.0, 0.1
MARKER_RE = re.compile(rf"{identity.COST_MARKER}=([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*$")
_MEMO, _MEMO_MAX = {}, 500


def _memo(path, compute):
    try:
        st = path.stat()
    except (OSError, AttributeError):
        return None
    key = (str(path), st.st_mtime, st.st_size)
    if key not in _MEMO:
        if len(_MEMO) >= _MEMO_MAX:
            _MEMO.clear()
        _MEMO[key] = compute(path)
    return _MEMO[key]


def turn_cost(usage, model):
    """(usd, priced) for one assistant message."""
    price = PRICES.get(model)
    if not price:
        return 0.0, False
    inp, outp = price
    cc = usage.get("cache_creation") or {}
    w5, w1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:  # older entries: only the total, 5 min TTL
        w5, w1 = usage.get("cache_creation_input_tokens"), 0
    usd = ((usage.get("input_tokens") or 0) * inp
           + (usage.get("output_tokens") or 0) * outp
           + (w5 or 0) * inp * WRITE_5M
           + (w1 or 0) * inp * WRITE_1H
           + (usage.get("cache_read_input_tokens") or 0) * inp * READ) / 1e6
    return usd, True


def _transcript(path):
    total, priced, seen = 0.0, False, set()
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue  # half-written tail of a live session
                msg = entry.get("message") if isinstance(entry, dict) else None
                if entry.get("type") != "assistant" or not isinstance(msg, dict) \
                        or not isinstance(msg.get("usage"), dict):
                    continue
                rid = entry.get("requestId")
                if rid is not None:  # one API call may be logged several times
                    if rid in seen:
                        continue
                    seen.add(rid)
                usd, ok = turn_cost(msg["usage"], msg.get("model"))
                total += usd
                priced = priced or ok
    except OSError:
        return None
    return round(total, 6) if priced else None


def _reported(path):
    total, seen = 0.0, False
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = MARKER_RE.match(line)
                if m:
                    total, seen = total + float(m.group(1)), True
    except OSError:
        return None
    return round(total, 6) if seen else None


def session_file(workdir, session_id):
    """Transcript of the run's session, None when the command never used it."""
    if not workdir or not session_id:
        return None
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(workdir))
    path = identity.home() / ".claude" / "projects" / slug / f"{session_id}.jsonl"
    return path if path.is_file() else None


def add(*parts):
    known = [p for p in parts if p is not None]
    return round(sum(known), 6) if known else None


def run_cost(meta, log_path):
    """(costUsd | None, hasSession)."""
    sess = session_file(meta.get("workdir"), meta.get("sessionId"))
    return add(_memo(sess, _transcript) if sess else None, _memo(log_path, _reported)), sess is not None
