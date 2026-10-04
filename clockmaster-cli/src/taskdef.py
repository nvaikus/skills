"""Task definitions: flat `key: value` yaml files in <data>/tasks/<name>.yaml.

Format (kept from the previous tool so migrated files load as-is): one key per
line, `#` comments, a value quoted with ' or " keeps a ` #` inside it,
duplicates and unknown keys are errors, the filename is the task name.
Edits rewrite ONE line and keep every other byte (comments, order).
"""
import re
from pathlib import Path

import identity
from cron import Cron
from errors import NotFound, ValidationError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
KEYS = ("schedule", "command", "workdir", "timeout", "keep", "enabled",
        "description", "notify", "sound", "group", "parallel", "queue", "catchup")
REQUIRED = ("schedule", "command")
NOTIFY_VALUES = ("off", "on", "failure")
DEFAULT_NOTIFY = "failure"
# macOS system sound names (files in /System/Library/Sounds, so case-sensitive).
SOUNDS = ("Basso", "Blow", "Bottle", "Frog", "Funk", "Glass", "Hero",
          "Morse", "Ping", "Pop", "Purr", "Sosumi", "Submarine", "Tink")
DEFAULT_SOUND = "Blow"
SOUND_VALUES = ("off", "on") + SOUNDS
DEFAULT_TIMEOUT = "2h"
DEFAULT_KEEP = 250
DEFAULT_PARALLEL = 1   # runs of one task at the same time; more wait in a queue
DEFAULT_QUEUE = 20     # runs that may wait; one more is recorded as skipped
ON_TIME_SLACK_MIN = 2  # catchup: false -> a scheduled start this late past its minute still runs
_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")


# ---------- reading ----------

def _scalar(rest):
    """(value, end index in rest) — a quoted value runs to its closing quote,
    an unquoted one to the first whitespace-then-#. None when a quote is open."""
    if rest[:1] in ("'", '"'):
        end = rest.find(rest[0], 1)
        return (None, -1) if end < 0 else (rest[1:end], end + 1)
    m = re.search(r"\s#", rest)
    cut = m.start() if m else len(rest)
    return rest[:cut].strip(), cut


def parse_flat(text, fname):
    raw = {}
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _LINE.match(s)
        if not m:
            raise ValidationError("expected 'key: value' (flat yaml, no nesting or lists)", f"{fname}:{i}")
        value, _ = _scalar(m.group(2))
        if value is None:
            raise ValidationError("unterminated quote", f"{fname}:{i}")
        if m.group(1) in raw:
            raise ValidationError(f"duplicate key '{m.group(1)}'", f"{fname}:{i}")
        raw[m.group(1)] = value
    return raw


def parse_timeout(val):
    if val in ("none", "0", ""):
        return None
    m = re.match(r"^(\d+)([smh]?)$", val)
    if not m:
        raise ValidationError(f"timeout must look like 90s, 30m, 2h or none — got '{val}'")
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]


def parse_keep(val):
    if val == "unlimited":
        return None
    if not val.isdigit() or int(val) < 1:
        raise ValidationError(f"keep must be a whole number of runs (1 or more) or 'unlimited' — got '{val}'")
    return int(val)


def parse_count(val, key, low):
    if not val.isdigit() or int(val) < low:
        raise ValidationError(f"{key} must be a whole number ({low} or more) — got '{val}'")
    return int(val)


def parallel_text(n):
    """Plain words for `parallel`."""
    return "1 at a time" if n == 1 else f"up to {n} at a time"


def parse_bool(val, key):
    if val in ("true", "yes"):
        return True
    if val in ("false", "no"):
        return False
    raise ValidationError(f"{key} must be true or false — got '{val}'")


def parse_notify(val):
    if val not in NOTIFY_VALUES:
        raise ValidationError(f"notify must be one of {', '.join(NOTIFY_VALUES)} — got '{val}'")
    return val


def parse_sound(val):
    """'off' or a sound name (`on` means the default sound)."""
    if val == "on":
        return DEFAULT_SOUND
    if val == "off" or val in SOUNDS:
        return val
    raise ValidationError(f"sound must be off, on (= {DEFAULT_SOUND}) or one of these names "
                          f"(case-sensitive): {', '.join(SOUNDS)} — got '{val}'")


def check_name(name, what="task name"):
    if not NAME_RE.match(name or ""):
        raise ValidationError(f"{what} must be kebab-case: lowercase letters, digits and '-' — got '{name}'")
    return name


class Task:
    """A validated task. Attributes mirror the yaml keys, resolved to defaults."""

    def __init__(self, name, raw, path=None):
        self.name, self.path, self.raw = name, path, raw
        self.schedule = raw["schedule"]
        self.cron = Cron(self.schedule)
        self.command = raw["command"]
        self.workdir = Path(raw["workdir"]).expanduser() if raw.get("workdir") else identity.home()
        self.timeout = parse_timeout(raw.get("timeout", DEFAULT_TIMEOUT))
        self.keep = parse_keep(raw.get("keep", str(DEFAULT_KEEP)))
        self.enabled = parse_bool(raw.get("enabled", "true"), "enabled")
        self.description = raw.get("description", "")
        self.notify = parse_notify(raw.get("notify", DEFAULT_NOTIFY))
        self.sound = parse_sound(raw.get("sound", DEFAULT_SOUND))
        self.group = raw.get("group", "")
        self.parallel = parse_count(raw.get("parallel", str(DEFAULT_PARALLEL)), "parallel", 1)
        self.queue = parse_count(raw.get("queue", str(DEFAULT_QUEUE)), "queue", 0)
        self.catchup = parse_bool(raw.get("catchup", "true"), "catchup")
        if self.group:
            check_name(self.group, "group")


def from_text(name, text, fname=None):
    """Validate a whole definition; raises ValidationError located at the file."""
    fname = fname or f"{name}.yaml"
    try:
        check_name(name, "task name (the filename)")
        raw = parse_flat(text, fname)
        if "name" in raw:
            raise ValidationError("remove 'name:' — the filename is the name")
        unknown = sorted(set(raw) - set(KEYS))
        if unknown:
            raise ValidationError(f"unknown keys {unknown}; allowed: {', '.join(KEYS)}")
        for key in REQUIRED:
            if not raw.get(key):
                raise ValidationError(f"missing required key '{key}'")
        return Task(name, raw)
    except ValidationError as e:
        if not e.where:
            e.where = fname
        raise


def path_of(name):
    return identity.tasks_dir() / f"{name}.yaml"


def from_file(path):
    task = from_text(path.stem, path.read_text(encoding="utf-8"), path.name)
    task.path = path
    return task


def find(name):
    """The task, or None when no yaml exists (a broken yaml still raises)."""
    if not NAME_RE.match(name or ""):
        return None
    path = path_of(name)
    return from_file(path) if path.is_file() else None


def load(name):
    task = find(name)
    if task is None:
        raise NotFound(f"no such task '{name}' ({path_of(name)})")
    return task


def load_all():
    """Every task; raises on the first broken file, so a typo can never make
    sync unregister a task."""
    d = identity.tasks_dir()
    if not d.is_dir():
        return []
    return [from_file(p) for p in sorted(d.glob("*.yaml")) if not p.name.startswith("_")]


# ---------- writing (line-preserving) ----------

def quote(value):
    """Value as it must be written so parse_flat reads it back unchanged."""
    if not (value[:1] in ("'", '"') or re.search(r"\s#", value) or value != value.strip()):
        return value
    for q in ("'", '"'):
        if q not in value:
            return f"{q}{value}{q}"
    raise ValidationError("this value needs quoting but holds both ' and \" — the task file cannot store it")


def set_key(text, key, value):
    """`text` with `key` set to the already-quoted `value`; None removes the line.
    Only that line changes — its indent and trailing comment survive."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        m = re.match(rf"^(\s*{re.escape(key)}:[ \t]*)(.*)$", body)
        if not m or body.lstrip().startswith("#"):
            continue
        if value is None:
            del lines[i]
        else:
            _, cut = _scalar(m.group(2))
            tail = m.group(2)[cut:] if cut >= 0 else ""
            lines[i] = m.group(1) + value + tail + line[len(body):]
        return "".join(lines)
    if value is None:
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return f"{text}{key}: {value}\n"


def apply_edits(text, edits):
    """Apply {key: str} edits; blank optional value = drop the key (default again)."""
    for key, value in edits.items():
        if key not in KEYS:
            raise ValidationError(f"unknown key '{key}'")
        if not isinstance(value, str):
            raise ValidationError(f"{key} must be a string")
        value = value.strip()
        if "\n" in value or "\r" in value:
            raise ValidationError(f"{key} must be a single line")
        if not value:
            if key in REQUIRED:
                raise ValidationError(f"{key} cannot be empty")
            text = set_key(text, key, None)
        else:
            text = set_key(text, key, quote(value))
    return text


def new_text(opts):
    """File body for `add`: schedule always quoted (a `*` first is fine in yaml
    proper but reads better quoted), other keys only when given."""
    lines = [f'schedule: "{opts["schedule"]}"', f"command: {quote(opts['command'])}"]
    for key in ("workdir", "timeout", "keep", "description", "notify", "sound", "group", "parallel", "queue",
                "catchup"):
        if opts.get(key) is not None:
            lines.append(f"{key}: {quote(opts[key])}")
    if opts.get("disabled"):
        lines.append("enabled: false")
    return "\n".join(lines) + "\n"


def on_time(task, now):
    """True when `now` is within ON_TIME_SLACK_MIN minutes after a scheduled minute.
    A start missed while off/asleep fires late (systemd Persistent, launchd wake,
    Windows StartWhenAvailable); with `catchup: false` such a start is dropped."""
    from datetime import timedelta
    base = now.replace(second=0, microsecond=0)
    return any(task.cron.matches(base - timedelta(minutes=m)) for m in range(ON_TIME_SLACK_MIN + 1))
