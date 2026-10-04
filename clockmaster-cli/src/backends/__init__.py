"""OS scheduler backends — one module per scheduler, one interface:

  name                       "launchd" | "systemd" | "schtasks" | "null"
  label                      column title in `list` (LAUNCHD / SYSTEMD / SCHEDULER)
  state(task)                "ok" | "off" | "missing" | "stale" | "unloaded"
  states(tasks)              {name: state} in one pass (default: state() each)
  registered(name), registered_names()
  sync(tasks) -> [lines]     register/refresh enabled, unregister disabled + orphans
  unregister(name)
  notes() -> [str]           environment warnings (linger, no user bus, TCC …)
  exec_guard(task, now)      False = the scheduler over-fired, skip this run
  ui_autostart_state(), ui_autostart_on(port), ui_autostart_off(),
  ui_autostart_restart(port), ui_autostart_stop()

`CLOCKMASTER_SCHEDULER=null` selects the null backend (dev/demo/tests): a JSON
registry in the data dir, no OS scheduler touched. Hidden from the help text.
"""
import os
import sys

import identity

_CACHE = {}


def current():
    want = os.environ.get(identity.ENV_SCHEDULER, "").strip().lower()
    if not want:
        want = {"darwin": "launchd", "win32": "schtasks"}.get(sys.platform, "systemd")
    if want not in _CACHE:
        if want == "null":
            from backends import null as mod
        elif want == "launchd":
            from backends import launchd as mod
        elif want == "schtasks":
            from backends import schtasks as mod
        elif want == "systemd":
            from backends import systemd as mod
        else:
            raise SystemExit(f"error: {identity.ENV_SCHEDULER}={want!r} — use systemd, launchd, schtasks or null, or unset it")
        _CACHE[want] = mod
    return _CACHE[want]


def states(backend, tasks):
    fn = getattr(backend, "states", None)
    if fn:
        return fn(tasks)
    return {t.name: backend.state(t) for t in tasks}

