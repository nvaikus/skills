"""Shared test environment: one temp root for every test module (paths read env at call time)."""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TMP = tempfile.mkdtemp(prefix="gmail-test-")
os.environ.update(GMAIL_ROOT=f"{TMP}/root", GDRIVE_ROOT=f"{TMP}/gdrive", GMAIL_DOWNLOADS=f"{TMP}/dl")
for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_PROFILE"):
    os.environ.pop(k, None)
CLIENT = {"client_id": "cid.apps.googleusercontent.com", "client_secret": "sec", "gmail_api": True,
          "apis_confirmed": True, "account": {"email": "me@x.com"}}


def make_profile(name, **cfg):
    os.makedirs(f"{TMP}/root/{name}", exist_ok=True)
    Path(f"{TMP}/root/{name}/config.json").write_text(json.dumps({**CLIENT, **cfg}))


make_profile("t")  # the one standing test profile
sys.path.insert(0, str(ROOT))

from src import main as main_mod  # noqa: E402
from src.core import profile  # noqa: E402

profile.resolve("t", "required")


def run(*argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    stdin_obj = io.StringIO(stdin) if stdin is not None else io.StringIO("")
    stdin_obj.isatty = lambda: stdin is None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(sys, "stdin", stdin_obj):
        rc = main_mod.main(list(argv))
    profile.resolve("t", "create")
    return rc, out.getvalue(), err.getvalue()
