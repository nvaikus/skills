#!/usr/bin/env python3
"""Entry point: wa-cli (see `wa-cli --help`)."""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = Path(os.environ.get("WA_CLI_HOME", "~/.wa-cli")).expanduser() / "venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

# neonize lives in a private venv (`wa-cli deps`): re-run under it when present.
# WA_CLI_IN_VENV guards against an exec loop when sys.prefix does not match.
if PY.exists() and not os.environ.get("WA_CLI_IN_VENV") and Path(sys.prefix).resolve() != VENV.resolve():
    os.environ["WA_CLI_IN_VENV"] = "1"
    argv = [str(PY), str(Path(__file__).resolve()), *sys.argv[1:]]
    if os.name == "nt":
        sys.exit(subprocess.call(argv))
    os.execv(str(PY), argv)

sys.path.insert(0, str(HERE))
from src.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
