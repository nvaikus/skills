"""Shared test environment: temp EBAY_ROOT, fake keys in env, Keychain off. Import before src."""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
TMP = tempfile.mkdtemp(prefix="ebay-test-")
os.environ.update(EBAY_ROOT=f"{TMP}/root", EBAY_NO_KEYCHAIN="1", EBAY_CLIENT_ID="app-id-123",
                  EBAY_CLIENT_SECRET="cert-secret-456")
for k in ("EBAY_MARKET", "EBAY_SHIP_TO", "EBAY_ZIP"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))

from src import main as main_mod  # noqa: E402


def fixture(name):
    return json.loads((FIX / name).read_text())


def write_config(**cfg):
    p = Path(f"{TMP}/root/config.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg))


def run(*argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    stdin_obj = io.StringIO(stdin) if stdin is not None else io.StringIO("")
    stdin_obj.isatty = lambda: stdin is None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(sys, "stdin", stdin_obj):
        try:
            rc = main_mod.main(list(argv))
        except SystemExit as e:  # argparse -h / usage
            rc = e.code
    return rc, out.getvalue(), err.getvalue()
