"""Null backend: registrations live in <data>/null-registry.json, nothing runs
on a schedule. For tests, demos and frontend work (CLOCKMASTER_SCHEDULER=null)."""
import hashlib
import json

import identity
from errors import ValidationError

name = "null"
label = "SCHEDULER"


def _path():
    return identity.data_dir() / "null-registry.json"


def _load():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(reg):
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _digest(task):
    return hashlib.sha1(f"{task.schedule}\0{task.command}\0{task.workdir}".encode()).hexdigest()


def registered(name):
    return name in _load()


def registered_names():
    return sorted(_load())


def state(task):
    reg = _load()
    if not task.enabled:
        return "stale" if task.name in reg else "off"
    if task.name not in reg:
        return "missing"
    return "ok" if reg[task.name] == _digest(task) else "stale"


def states(tasks):
    return {t.name: state(t) for t in tasks}


def sync(tasks):
    reg, out = _load(), []
    want = {t.name: t for t in tasks if t.enabled}
    for t in tasks:
        if t.enabled and reg.get(t.name) != _digest(t):
            out.append(f"registered {t.name}")
            reg[t.name] = _digest(t)
    for n in sorted(set(reg) - set(want)):
        del reg[n]
        out.append(f"unregistered {n}")
    _save(reg)
    return out or ["nothing to do — everything is in sync"]


def unregister(name):
    reg = _load()
    if reg.pop(name, None) is not None:
        _save(reg)


def notes():
    return ["null scheduler (CLOCKMASTER_SCHEDULER=null): nothing runs on a schedule"]


def exec_guard(task, now):
    return True


def ui_autostart_state():
    return None


def ui_autostart_on(port):
    raise ValidationError("the null scheduler has no UI autostart")


def ui_autostart_off():
    pass


def ui_autostart_restart(port):
    pass


def ui_autostart_stop():
    pass


def ui_autostart_hint():
    return ""
