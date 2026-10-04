"""Background index updates every 5 minutes: systemd user timer (Linux) / LaunchAgent (macOS).
Each tick runs `gdrive --profile P index update --unbounded`; api/indexer's lock makes an
overlapping tick exit at once."""
import os
import plistlib
import subprocess
from pathlib import Path

from . import indexer, persist

INTERVAL = 300


def _name(prof):
    return f"gdrive-index-{prof}"


def _label(prof):
    return f"gdrive.index.{prof}"


RELOCATION = ("GDRIVE_ROOT", "GDRIVE_HOME", "GDRIVE_CACHE_DIR")


def _env():
    # launchd starts agents with PATH=/usr/bin:/bin:/usr/sbin:/sbin, where a Homebrew pdftotext
    # is invisible -> capture the installing shell's PATH (and any relocated gdrive dirs)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    env.update({k: os.environ[k] for k in RELOCATION if os.environ.get(k)})
    return env


def systemd_units(prof):
    q = persist.sd_quote
    log = indexer.log_path(prof)
    service = (f"[Unit]\nDescription=gdrive index update ({prof})\n\n[Service]\nType=oneshot\nNice=10\n"
               + "".join(f"Environment={q(f'{k}={v}')}\n" for k, v in _env().items())
               + f"ExecStart={' '.join(q(a) for a in indexer.command(prof))}\n"
               f"StandardOutput=append:{log}\nStandardError=append:{log}\n")
    timer = (f"[Unit]\nDescription=gdrive index every {INTERVAL // 60} min ({prof})\n\n[Timer]\n"
             f"OnActiveSec=30s\nOnUnitInactiveSec={INTERVAL}s\n\n[Install]\nWantedBy=timers.target\n")
    return service, timer


def launchd_plist(prof):
    log = str(indexer.log_path(prof))
    return plistlib.dumps({"Label": _label(prof), "ProgramArguments": indexer.command(prof),
                           "StartInterval": INTERVAL, "RunAtLoad": True, "Nice": 10, "LowPriorityIO": True,
                           "EnvironmentVariables": _env(), "StandardOutPath": log, "StandardErrorPath": log})


def _unit_dir():
    return Path("~/.config/systemd/user").expanduser()


def _plist_path(prof):
    return Path("~/Library/LaunchAgents").expanduser() / f"{_label(prof)}.plist"


def install(prof):
    """Write + start (idempotent: rewrites with the current python/skill paths). -> unit path."""
    k = persist.kind()
    if k == "systemd":
        service, timer = systemd_units(prof)
        persist.write_unit(_unit_dir() / f"{_name(prof)}.service", service.encode())
        persist.write_unit(_unit_dir() / f"{_name(prof)}.timer", timer.encode())
        persist.run_cmd(["systemctl", "--user", "daemon-reload"])
        persist.run_cmd(["systemctl", "--user", "enable", "--now", f"{_name(prof)}.timer"])
        return str(_unit_dir() / f"{_name(prof)}.timer")
    path = _plist_path(prof)
    persist.write_unit(path, launchd_plist(prof))
    persist.bootstrap(_label(prof), path)
    return str(path)


def remove(prof):
    k = persist.kind()
    if k == "systemd":
        subprocess.run(["systemctl", "--user", "disable", "--now", f"{_name(prof)}.timer"], capture_output=True)
        for ext in ("timer", "service"):
            (_unit_dir() / f"{_name(prof)}.{ext}").unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    else:
        subprocess.run(["launchctl", "bootout", f"{persist.domain()}/{_label(prof)}"], capture_output=True)
        _plist_path(prof).unlink(missing_ok=True)


def state(prof):
    """-> 'on' | 'off' | 'broken' (unit file present but not loaded) | 'unsupported'."""
    try:
        k = persist.kind()
    except Exception:  # noqa: BLE001 - UsageError on unsupported OS
        return "unsupported"
    if k == "systemd":
        if not (_unit_dir() / f"{_name(prof)}.timer").exists():
            return "off"
        p = subprocess.run(["systemctl", "--user", "is-active", f"{_name(prof)}.timer"], capture_output=True, text=True)
        return "on" if p.stdout.strip() == "active" else "broken"
    if not _plist_path(prof).exists():
        return "off"
    p = subprocess.run(["launchctl", "print", f"{persist.domain()}/{_label(prof)}"], capture_output=True)
    return "on" if p.returncode == 0 else "broken"
