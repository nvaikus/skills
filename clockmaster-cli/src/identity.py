"""The tool's name and every name or path derived from it — the single rename point.

Paths are functions, not constants: they read the environment at call time, so
tests (and `CLOCKMASTER_HOME`) can move them without re-importing anything.
"""
import os
import sys
from pathlib import Path

APP = "clockmaster"
TITLE = APP
UI_PORT = 7788

SRC_DIR = Path(__file__).resolve().parent
SKILL_DIR = SRC_DIR.parent
ENTRY = SKILL_DIR / f"{APP}.py"            # what schedulers and the UI execute
SERVER = SRC_DIR / "web" / "server.py"
ASSETS = SKILL_DIR / "assets"

ENV_HOME = "CLOCKMASTER_HOME"              # data dir override
ENV_SCHEDULER = "CLOCKMASTER_SCHEDULER"    # "null" = dev/test backend, touches no OS scheduler

# Task-facing env names stay the old generic ones: migrated task commands and
# scripts already use them.
ENV_SESSION = "TASK_SESSION_ID"
COST_MARKER = "TASK_COST_USD"

# launchd (macOS): the UI agent label sits OUTSIDE the task prefix on purpose —
# sync deletes every prefixed plist without a yaml behind it.
LAUNCHD_PREFIX = f"com.claude.{APP}."
LAUNCHD_UI = f"com.claude.{APP}-ui"
NOTIFIER_ID = f"com.claude.{APP}-notifier"
NOTIFIER_NAME = "Clockmaster"

# systemd --user (Linux): same rule, `clockmaster-ui` is not `clockmaster.*`.
UNIT_PREFIX = f"{APP}."
UI_UNIT = f"{APP}-ui.service"

# Windows Task Scheduler folder
WIN_FOLDER = f"\\{APP}"


def home():
    return Path.home()


def data_dir():
    env = os.environ.get(ENV_HOME)
    return Path(env).expanduser() if env else home() / ".claude" / APP


def tasks_dir():
    return data_dir() / "tasks"


def runs_dir():
    return data_dir() / "runs"


def platform():
    return {"darwin": "darwin", "win32": "win32"}.get(sys.platform, "linux")
