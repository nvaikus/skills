"""Shared test environment: one temp root for every test module (paths read env at call time,
so two modules setting different roots at import would break each other)."""
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TMP = tempfile.mkdtemp(prefix="gdrive-test-")
os.environ.update(GDRIVE_HOME=f"{TMP}/home", GDRIVE_CONF_DIR=f"{TMP}/conf", GDRIVE_CACHE_DIR=f"{TMP}/cache",
                  GDRIVE_ROOT=f"{TMP}/root")
for k in ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REMOTE", "GDRIVE_CACHE_LIMIT", "GDRIVE_PROFILE"):
    os.environ.pop(k, None)
os.makedirs(f"{TMP}/root/t", exist_ok=True)
Path(f"{TMP}/root/t/config.json").write_text("{}")  # the one standing test profile
sys.path.insert(0, str(ROOT))

from src import main as main_mod  # noqa: E402
from src.core import profile  # noqa: E402

profile.resolve("t", "required")  # api calls made directly by tests (outside main) use profile t


def run(*argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    stdin_obj = io.StringIO(stdin) if stdin is not None else io.StringIO("")
    stdin_obj.isatty = lambda: stdin is None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(sys, "stdin", stdin_obj):
        rc = main_mod.main(list(argv))
    profile.resolve("t", "create")  # a command may have switched the active profile
    return rc, out.getvalue(), err.getvalue()
