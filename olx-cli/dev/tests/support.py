"""Shared test environment: temp OLX_ROOT, no pacing gap. Import before src."""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
TMP = tempfile.mkdtemp(prefix="olx-test-")
os.environ.update(OLX_ROOT=f"{TMP}/root", OLX_GAP="0")
os.environ.pop("OLX_SITE", None)
sys.path.insert(0, str(ROOT))

from src import main as main_mod  # noqa: E402


def fixture(name):
    text = (FIX / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


def write_config(**cfg):
    p = Path(f"{TMP}/root/config.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg))


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main_mod.main(list(argv))
        except SystemExit as e:  # argparse -h / usage
            rc = e.code
    return rc, out.getvalue(), err.getvalue()
