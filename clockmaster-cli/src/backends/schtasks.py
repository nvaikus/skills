"""Windows: one Task Scheduler task per task in the `\\clockmaster` folder.

Registered from Task Definition XML (schema 1.2) written by this module. Drift
is measured against an XML cache written at registration (`schtasks /query
/xml` re-serializes: own element order, \\r\\r\\n, console codepage), plus the
registered <Enabled> flag (someone may disable it in taskschd.msc).

Task Scheduler cannot AND day-of-month with weekday, nor filter a weekly
schedule by month: the XML over-fires and `exec_guard` re-checks the DATE at run
time (hour/minute deliberately not: a StartWhenAvailable catch-up runs late).
"""
import os
import re
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import identity
from errors import Conflict, ValidationError

name = "schtasks"
label = "SCHEDULER"
CAP = 512
ANCHOR = "2000-01-01"  # a past StartBoundary: the trigger is live from registration on
DOW = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
ENABLED_RE = re.compile(r"<Settings>.*?<Enabled>\s*(\w+)\s*</Enabled>", re.S)


def task_path(task_name):
    return f"{identity.WIN_FOLDER}\\{task_name}"


def xml_dir():
    return identity.data_dir() / "schtasks-xml"


def cache_path(task_name):
    return xml_dir() / f"{task_name}.xml"


def python_w():
    """pythonw.exe beside the running interpreter: a console python flashes a
    window at every fire. sys.executable, not PATH: a WindowsApps launcher
    resolves to the real interpreter dir, which does hold pythonw.exe."""
    exe = Path(sys.executable)
    stem = exe.stem.lower()
    if stem.startswith("pythonw"):
        return str(exe)
    if stem.startswith("python"):
        cand = exe.with_name("pythonw" + exe.name[len("python"):])
        if cand.exists():
            return str(cand)
    return str(exe)


def user():
    dom = os.environ.get("USERDOMAIN") or os.environ.get("COMPUTERNAME") or ""
    u = os.environ.get("USERNAME") or ""
    return f"{dom}\\{u}" if dom else u


def grid_step(minutes):
    """Step of an every-N-minutes grid covering a whole hour, else None."""
    if not minutes or 60 % len(minutes):
        return None
    step = 60 // len(minutes)
    return step if minutes == list(range(0, 60, step)) else None


def trigger_times(c):
    """([(hour, minute)], repeat_minutes|None). There is no "every hour"
    wildcard: an unrestricted hour with a whole-hour minute grid collapses into
    ONE midnight trigger with a <Repetition>; anything else is spelled out."""
    if c.hour is None:
        step = grid_step(c.minute if c.minute is not None else list(range(60)))
        if step:
            return [(0, 0)], step
    hours = c.hour if c.hour is not None else list(range(24))
    minutes = c.minute if c.minute is not None else list(range(60))
    if len(hours) * len(minutes) > CAP:
        raise ValidationError(f"schedule expands to more than {CAP} Task Scheduler triggers; simplify it")
    return [(h, m) for h in hours for m in minutes], None


def schedule_xml(c):
    """The <Schedule*> element: WHICH DAYS a trigger fires. Whatever cannot be
    expressed fires too often and is re-checked by exec_guard."""
    if c.day is None and c.weekday is None and c.month is None:
        return "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
    if c.day is None and c.weekday is not None:
        days = "".join(f"<{DOW[d]} />" for d in c.weekday)
        return f"<ScheduleByWeek><DaysOfWeek>{days}</DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek>"
    days = "".join(f"<Day>{d}</Day>" for d in (c.day or range(1, 32)))
    months = "".join(f"<{MONTHS[m - 1]} />" for m in (c.month or range(1, 13)))
    return f"<ScheduleByMonth><DaysOfMonth>{days}</DaysOfMonth><Months>{months}</Months></ScheduleByMonth>"


def task_xml(task):
    """StartWhenAvailable = launchd's sleep catch-up. ExecutionTimeLimit PT0S:
    the runner enforces the task's own timeout. InteractiveToken + least
    privilege = the current user, no admin."""
    times, repeat = trigger_times(task.cron)
    sched = schedule_xml(task.cron)
    rep = ("\n      <Repetition><Interval>PT%dM</Interval><Duration>P1D</Duration>"
           "<StopAtDurationEnd>false</StopAtDurationEnd></Repetition>" % repeat) if repeat else ""
    triggers = "".join(
        f"    <CalendarTrigger>{rep}\n"
        f"      <StartBoundary>{ANCHOR}T{h:02d}:{m:02d}:00</StartBoundary>\n"
        f"      <Enabled>true</Enabled>\n"
        f"      {sched}\n"
        f"    </CalendarTrigger>\n"
        for h, m in times)
    u = xml_escape(user())
    desc = xml_escape(task.description or f"{identity.APP}: {task.schedule}")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>{u}</Author>
    <URI>{xml_escape(task_path(task.name))}</URI>
    <Description>{desc}</Description>
  </RegistrationInfo>
  <Triggers>
{triggers}  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{u}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{xml_escape(python_w())}</Command>
      <Arguments>"{xml_escape(str(identity.ENTRY))}" _exec {xml_escape(task.name)}</Arguments>
      <WorkingDirectory>{xml_escape(str(identity.SKILL_DIR))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def xml_bytes(task):
    """schtasks wants a Unicode file: UTF-16 with a BOM, CRLF."""
    return task_xml(task).replace("\n", "\r\n").encode("utf-16")


def schtasks(*args, binary=False):
    kw = {} if binary else {"text": True, "errors": "replace"}
    return subprocess.run(["schtasks", *args], capture_output=True, **kw)


def query(task_name):
    r = schtasks("/query", "/tn", task_path(task_name), "/xml", binary=True)
    return None if r.returncode else r.stdout.decode("utf-8", "replace")


def registered_enabled(text):
    m = ENABLED_RE.search(text or "")
    return m.group(1).lower() != "false" if m else True


def registered(task_name):
    return query(task_name) is not None


def registered_names():
    r = schtasks("/query", "/fo", "CSV", "/nh", "/tn", identity.WIN_FOLDER + "\\")
    if r.returncode:
        return []  # no folder yet
    prefix, names = identity.WIN_FOLDER + "\\", set()
    for line in r.stdout.splitlines():
        tn = line.split('","')[0].strip('"') if line.startswith('"') else ""
        if tn.startswith(prefix) and "\\" not in tn[len(prefix):]:
            names.add(tn[len(prefix):])
    return sorted(names)


def register(task_name, content):
    p = cache_path(task_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    r = schtasks("/create", "/tn", task_path(task_name), "/xml", str(p), "/f")
    if r.returncode:
        p.unlink()  # no cache -> state stays stale
        raise Conflict(f"schtasks /create failed for '{task_name}': {(r.stderr or r.stdout).strip()}")


def unregister(task_name):
    schtasks("/delete", "/tn", task_path(task_name), "/f")  # rc ignored: may not exist
    try:
        cache_path(task_name).unlink()
    except FileNotFoundError:
        pass


def state(task):
    reg = query(task.name)
    if not task.enabled:
        return "stale" if reg is not None else "off"
    if reg is None:
        return "missing"
    cache = cache_path(task.name)
    if not cache.exists() or cache.read_bytes() != xml_bytes(task):
        return "stale"
    return "ok" if registered_enabled(reg) else "unloaded"


def states(tasks):
    return {t.name: state(t) for t in tasks}


def sync(tasks):
    for d in (identity.tasks_dir(), identity.runs_dir(), identity.data_dir() / "scheduler-io", xml_dir()):
        d.mkdir(parents=True, exist_ok=True)
    desired = {t.name: t for t in tasks if t.enabled}
    have = set(registered_names())
    lines, unchanged = [], 0
    for n, t in sorted(desired.items()):
        content = xml_bytes(t)
        cache = cache_path(n)
        if n not in have or not cache.exists() or cache.read_bytes() != content:
            register(n, content)
            times, repeat = trigger_times(t.cron)
            how = f"{len(times)} trigger{'s' if len(times) != 1 else ''}" + (f", every {repeat}m" if repeat else "")
            lines.append(f"~ {n}: scheduled '{t.schedule}' ({how})")
        elif not registered_enabled(query(n)):
            register(n, content)  # disabled by hand in taskschd.msc
            lines.append(f"+ {n}: re-enabled")
        else:
            unchanged += 1
    for n in sorted(have - set(desired)):
        unregister(n)
        lines.append(f"- {n}: removed from Task Scheduler")
    for cache in sorted(xml_dir().glob("*.xml")):
        if cache.stem not in desired:
            cache.unlink()
    lines.append(f"sync done: {len(desired)} scheduled, {len(lines)} changed, {unchanged} unchanged")
    return lines


def notes():
    return []


def exec_guard(task, now):
    """Date-only re-check (see module doc)."""
    return task.cron.date_ok(now)


# ---------- UI autostart: not on Windows yet ----------

def ui_autostart_state():
    return None


def ui_autostart_on(port):
    raise ValidationError("ui --autostart is not available on Windows yet")


def ui_autostart_off():
    pass


def ui_autostart_restart(port):
    pass


def ui_autostart_stop():
    pass


def ui_autostart_hint():
    return ""
