"""index update: bring the text index up to date (change feed), or re-index one file now."""
import argparse
import shutil
import time

from ...api import address, indexer, providers
from ...core import config, profile
from ...core.errors import Deadline

FIELDS = ["profile", "status", "sync", "extracted", "failed", "retry", "moved", "deleted", "files", "pending"]
ITEM_FIELDS = ["path", "status", "id"]
WRITE = True
WAIT = True
EPILOG = """examples:
  gdrive index update ~/gdrive/work/Clients/Ivanov/smeta.xlsx   # after YOUR write: sync first, then this
  gdrive index update ~/.claude/gdrive/work/index/Clients/Ivanov/smeta.xlsx.md   # an index hit works too
  gdrive index update                     # catch up with Drive now (the service does this every 5 min)
  gdrive index update --background        # e.g. the first full build: returns at once

A file's text is rebuilt only when its checksum changed (--force: always). A write into the
mount reaches Drive seconds later: run `gdrive sync <dir>` BEFORE this, or the old version is read.
Renames and moves only move the .md; deleted/trashed files lose theirs. Google Docs/Sheets/
Slides are exported; PDFs use pdftotext when on PATH, scans and images Google's OCR.
Exit 6: stopped at the --wait deadline, progress kept - rerun (or --background) to continue.
Already running (the service or a --background run): exit 0, status 'running'.
"""


def add_args(p):
    p.add_argument("path", nargs="?", help="one file or folder: mount path, Drive path, or index .md path")
    p.add_argument("--force", action="store_true", help="re-extract PATH even when its checksum is unchanged")
    p.add_argument("--background", action="store_true", help="run detached; watch with `gdrive index status`")
    p.add_argument("--rebuild", action="store_true", help="drop the whole index and build it again")
    p.add_argument("--unbounded", action="store_true", help=argparse.SUPPRESS)  # the service's run: no deadline


def _one(ctx, args):
    hit = indexer.md_target(args.path)
    if hit:
        profile.switch(hit[0])
    else:
        addr = address.of(args.path)
    cfg = config.load()
    prov = providers.for_profile(cfg)
    item_id = hit[1] if hit else prov.resolve(addr)
    man = indexer.open_manifest()
    try:
        rows = indexer.update_item(prov, man, indexer.index_dir(), cfg, item_id, args.force)
    finally:
        man.close()
    ctx.write(rows, ITEM_FIELDS)


def run(ctx, args):
    if args.path:
        return _one(ctx, args)
    prof = profile.active()
    lock = indexer.Lock()
    if args.background:
        pid = lock.holder() or indexer.spawn(prof)
        ctx.note(f"log: {indexer.log_path(prof)} · progress: gdrive index status")
        return ctx.write([{"profile": prof, "status": "running", "pid": pid}], ["profile", "status", "pid"], receipt=True)
    prov = providers.for_profile(ctx.cfg)
    if providers.scope(ctx.cfg) == "/" and not providers.new_layout(prof):
        ctx.note("the mount has the old layout (My Drive only): `gdrive mount` switches it to My Drive / "
                 "Shared with me / Shared drives, and the index follows")
    for name in getattr(prov, "missing", ()):
        ctx.note(f"included Shared drive {name!r} is not visible to this account any more: "
                 f"gdrive index exclude 'shared:{name}'")
    try:
        with lock:
            man = indexer.open_manifest()
            try:
                if args.rebuild:
                    man.reset()
                    shutil.rmtree(indexer.index_dir(), ignore_errors=True)
                deadline = None if args.unbounded else time.monotonic() + args.wait
                step = {"n": 0}

                def progress(c):
                    step["n"] += 1
                    if step["n"] % 100 == 0:
                        ctx.note(f"{c['indexed']} indexed, {c['error']} failed, {c['retry']} to retry")

                got = indexer.update(prov, man, indexer.index_dir(), ctx.cfg, deadline, progress)
            finally:
                man.close()
    except indexer.Busy as b:
        ctx.note(f"an index update is already running (pid {b.pid}); progress: gdrive index status")
        return ctx.write([{"profile": prof, "status": "running"}], FIELDS, receipt=True)
    ctx.write([{"profile": prof, "status": "done" if got["finished"] else "partial", **got}], FIELDS, receipt=True)
    if not got["finished"]:
        raise Deadline(f"stopped after {args.wait:g} s with {got['pending']} file(s) left - NOTHING WAS UNDONE, "
                       "progress is kept; rerun, or `gdrive index update --background`")
