"""The text index of one profile: index/<mount path>.md files + index.sqlite (api/manifest).

One run = sync metadata (full listing once, then the change feed from the stored cursor)
-> reconcile (every item's mount path is recomputed; renamed/moved texts are moved, gone ones
deleted - no re-download) -> extract what is new or changed (download to a temp dir, extract,
discard the original). Provider-agnostic: it only talks to api/provider.Provider."""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from ..core import paths, proc, profile
from ..core.errors import CliError, UsageError
from . import extract
from .manifest import Manifest, now
from .provider import Transient

IMAGE_OCR_MAX = 10 * 1024 * 1024  # Drive image→Doc conversion: 10.0 MB JPEG ok, 11.1 MB → 413 (live)
HEADER_KEYS = ("id", "md5", "modified", "path", "address", "extractor", "indexed")


# ---- where things live ---------------------------------------------------------------------

def index_dir(name=None):
    return paths.sub(profile.dir(name), "index")


def manifest_path(name=None):
    return profile.dir(name) / "index.sqlite"


def open_manifest(name=None):
    return Manifest(manifest_path(name))


# ---- mount path <-> index path (pure) ------------------------------------------------------

def display(row):
    """The name the mount shows: '/' inside a name becomes '／' (rclone), plus the export suffix."""
    return row["name"].replace("/", "／") + (row.get("ext") or "")


def segments(rows):
    """Siblings -> {id: path segment}. Names equal ignoring case (the Drive allows duplicates;
    macOS/Windows file systems fold case) get '<name>@<id>' - a form every gdrive command accepts."""
    groups = {}
    for r in rows:
        if r.get("ext") is not None:
            groups.setdefault(display(r).casefold(), []).append(r)
    out = {}
    for group in groups.values():
        for r in group:
            out[r["id"]] = display(r) if len(group) == 1 else f"{display(r)}@{r['id']}"
    return out


def compute_paths(rows, root_id):
    """All rows -> {id: mount-relative path or None (outside the scope / not shown by the mount)}."""
    kids = {}
    for r in rows:
        kids.setdefault(r.get("parent"), []).append(r)
    out = {r["id"]: None for r in rows}
    stack, seen = [(root_id, "")], {root_id}
    while stack:
        pid, base = stack.pop()
        segs = segments(kids.get(pid, []))
        for r in kids.get(pid, []):
            seg = segs.get(r["id"])
            if seg is None:
                continue
            path = f"{base}/{seg}" if base else seg
            out[r["id"]] = path
            if r.get("folder") and r["id"] not in seen:
                seen.add(r["id"])
                stack.append((r["id"], path))
    return out


def md_path(idx, rel):
    return Path(idx) / (rel + ".md")


def rel_of_md(idx, md):
    """index/<rel>.md -> rel (the mount-relative path)."""
    rel = os.path.relpath(os.path.abspath(md), os.path.abspath(idx)).replace(os.sep, "/")
    return rel[:-3] if rel.endswith(".md") else rel


# ---- index files ---------------------------------------------------------------------------

def render(row, address, extractor, body):
    head = {"id": row["id"], "md5": row.get("md5") or "-", "modified": row.get("modified") or "-",
            "path": row["path"], "address": address, "extractor": extractor, "indexed": now()}
    return "---\n" + "".join(f"{k}: {head[k]}\n" for k in HEADER_KEYS) + "---\n" + body


def parse(text):
    """-> (header dict, body). A file without a header -> ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 3)
    if end < 0:
        return {}, text
    head = dict(ln.split(": ", 1) for ln in text[4:end].splitlines() if ": " in ln)
    return head, text[end + 5:]


def write_md(idx, rel, text):
    p = md_path(idx, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def prune(idx):
    """Remove empty folders left behind by moves/deletes."""
    for d, _, _ in os.walk(idx, topdown=False):  # bottom-up; listing re-read: children may be gone now
        if d != str(idx) and not os.listdir(d):
            try:
                os.rmdir(d)
            except OSError:
                pass


# ---- reconcile -----------------------------------------------------------------------------

def reconcile(man, idx, address, gone=()):
    """Recompute every path; move texts of renamed/moved items (header rewritten, no download),
    delete texts of removed or out-of-scope items. -> {"moved": n, "deleted": n}."""
    root = man.meta("root_id")
    rows = man.rows()
    new = compute_paths(rows, root)
    changed = {r["id"]: new[r["id"]] for r in rows if r.get("path") != new[r["id"]]}
    stats = {"moved": 0, "deleted": 0}
    for g in gone:
        if not g.get("folder") and g.get("path") and md_path(idx, g["path"]).exists():
            md_path(idx, g["path"]).unlink()
            stats["deleted"] += 1
    staged = []
    stage = Path(idx) / ".moving"
    for r in rows:
        if r["id"] not in changed or r.get("folder") or not r.get("path"):
            continue
        old = md_path(idx, r["path"])
        if not old.exists():
            continue
        if changed[r["id"]] is None:
            old.unlink()
            stats["deleted"] += 1
            continue
        stage.mkdir(exist_ok=True)  # two phases: a swap of two names must not overwrite a text
        tmp = stage / f"{r['id']}.md"
        os.replace(old, tmp)
        staged.append((r, tmp))
    for r, tmp in staged:
        rel = changed[r["id"]]
        head, body = parse(tmp.read_text(encoding="utf-8"))
        row = {**r, "path": rel}
        write_md(idx, rel, render(row, address(rel), head.get("extractor", r.get("extractor") or "?"), body))
        tmp.unlink()
        stats["moved"] += 1
    if changed:
        man.set_paths(changed)
    if stats["moved"] or stats["deleted"]:
        shutil.rmtree(stage, ignore_errors=True)
        prune(idx)
    return stats


# ---- metadata sync -------------------------------------------------------------------------

def sync_meta(prov, man, idx, deadline=None):
    """-> (gone rows, "full"|"changes", finished). A scope change wipes the index first."""
    old = man.meta("scope")
    if old != prov.scope_key():
        if old and prov.compatible(old):  # same corpus, other layout/sections: relist, texts move
            man.set_meta(scope=prov.scope_key(), root_id=prov.root_id(), cursor=None)
        else:
            man.reset()
            shutil.rmtree(idx, ignore_errors=True)
            Path(idx).mkdir(parents=True, exist_ok=True)
            man.set_meta(scope=prov.scope_key(), root_id=prov.root_id(), provider=prov.name)
    cursor = man.meta("cursor")
    if not cursor:
        start = prov.start_cursor()  # before listing: a change made meanwhile is replayed, not lost
        seen = set()
        for batch in prov.list_all():
            man.upsert(batch)
            seen.update(it["id"] for it in batch)
        gone = man.remove_except(seen)
        man.set_meta(cursor=start, root_id=prov.root_id(), listed=now())
        return gone, "full", True
    gone = []
    for ups, removed, nxt in prov.changes(cursor):
        man.upsert(ups)
        gone += man.remove(removed)
        man.set_meta(cursor=nxt)  # per page: an interrupted run resumes here
        if deadline is not None and time.monotonic() > deadline:
            return gone, "changes", False
    return gone, "changes", True


# ---- extraction ----------------------------------------------------------------------------

def text_of(prov, row, cfg, tmp):
    """-> (extractor, body). Raises Transient (retry later) or CliError (recorded)."""
    name, mime, size = row["name"], row["mime"], row.get("size")
    if row.get("native"):
        got = prov.export_text(row, tmp)
        if not got:
            return "meta", extract.meta_line(name, mime, size, "no text form")
        return got[1], extract.cap(got[0])
    k = extract.kind(mime, name)
    if not k:
        return "meta", extract.meta_line(name, mime, size)
    limit = int(cfg.get("index_max_mb") or 50) * 1024 * 1024
    if size and size > limit:
        return "meta", extract.meta_line(name, mime, size, f"larger than index_max_mb={cfg.get('index_max_mb')}")
    ocr_ok = cfg.get("ocr", "auto") != "off" and (size or 0) <= int(cfg.get("ocr_max_mb") or 20) * 1024 * 1024
    if k == "image":
        if not ocr_ok:
            return "meta", extract.meta_line(name, mime, size, "OCR off or file above ocr_max_mb")
        if (size or 0) > IMAGE_OCR_MAX:
            return "meta", extract.meta_line(name, mime, size, "image above Drive OCR limit (10 MB)")
        body = prov.ocr_text(row, tmp)
        return ("ocr", body) if body is not None else ("meta", extract.meta_line(name, mime, size))
    dest = Path(tmp) / f"orig-{row['id']}"
    try:
        prov.fetch(row, dest)
        if k == "text":
            body = extract.text(dest)
            return ("text", body) if body is not None else ("meta", extract.meta_line(name, mime, size, "binary"))
        if k == "pdf":
            body = extract.pdf(dest)
            if body is not None and extract.meaningful(body):
                return "pdftotext", body
            if ocr_ok:
                got = prov.ocr_text(row, tmp)
                if got is not None:
                    return "ocr", extract.cap(got)
            why = "scanned PDF, OCR off or above ocr_max_mb" if body is not None else "no pdftotext and OCR off"
            return "meta", extract.meta_line(name, mime, size, why)
        try:
            return k, extract.office(k, dest)
        except ValueError as e:
            return "meta", extract.meta_line(name, mime, size, str(e))
    finally:
        dest.unlink(missing_ok=True)  # the original is never kept


def index_one(prov, man, idx, row, cfg, tmp, force=False):
    """Extract one row now. -> 'indexed' | 'current' | 'retry' | 'error'."""
    fresh = man.get(row["id"])  # a parallel run may have moved or indexed it meanwhile
    if not fresh or not fresh.get("path") or fresh.get("folder") or fresh.get("ext") is None:
        return "current"
    if not force and fresh.get("idx_key") == fresh.get("key"):
        return "current"
    try:
        extractor, body = text_of(prov, fresh, cfg, tmp)
        err = None
    except Transient:
        return "retry"
    except CliError as e:
        extractor, err = "error", str(e).splitlines()[0][:300]
        body = extract.meta_line(fresh["name"], fresh["mime"], fresh.get("size"), err)
    write_md(idx, fresh["path"], render(fresh, prov.address(fresh["path"]), extractor, body))
    man.mark(fresh["id"], fresh.get("key"), extractor, err)
    return "error" if err else "indexed"


def extract_pending(prov, man, idx, cfg, deadline=None, prefix=None, on_progress=None):
    """-> (counts dict, finished)."""
    counts = {"indexed": 0, "error": 0, "retry": 0, "current": 0}
    with tempfile.TemporaryDirectory(prefix="gdrive-index-") as tmp:
        for row in man.pending(prefix):
            if deadline is not None and time.monotonic() > deadline:
                return counts, False
            counts[index_one(prov, man, idx, row, cfg, tmp)] += 1
            if on_progress:
                on_progress(counts)
    return counts, True


# ---- one run -------------------------------------------------------------------------------

def update(prov, man, idx, cfg, deadline=None, on_progress=None):
    """Full cycle. -> receipt dict; finished=False when the deadline stopped it (state kept)."""
    man.set_meta(last_start=now())
    swept = prov.sweep()
    gone, how, done = sync_meta(prov, man, idx, deadline)
    moved = reconcile(man, idx, prov.address, gone)
    counts, finished = extract_pending(prov, man, idx, cfg, deadline, on_progress=on_progress) if done else ({}, False)
    if done and finished:
        man.set_meta(last_update=now())
    return {"sync": how, "moved": moved["moved"], "deleted": moved["deleted"], "swept": swept,
            "extracted": counts.get("indexed", 0), "failed": counts.get("error", 0), "retry": counts.get("retry", 0),
            "finished": done and finished, **man.counts()}


def update_item(prov, man, idx, cfg, item_id, force):
    """Re-index one file (or a folder's subtree) now, outside the change feed. -> rows."""
    if not man.meta("cursor"):
        raise UsageError("the index was never built for this profile: run `gdrive index update` first")
    it = prov.get(item_id)
    if it is None:
        gone = man.remove([item_id])
        reconcile(man, idx, prov.address, gone)
        return [{"id": item_id, "path": (gone[0]["path"] if gone else None), "status": "removed"}]
    batch = [it]
    if it["folder"]:
        todo = [it["id"]]
        while todo:
            kids = prov.list_children(todo.pop())
            batch += kids
            todo += [k["id"] for k in kids if k["folder"]]
    man.upsert(batch)
    reconcile(man, idx, prov.address)
    rows = []
    with tempfile.TemporaryDirectory(prefix="gdrive-index-") as tmp:
        for b in batch:
            row = man.get(b["id"])
            if row["folder"]:
                continue
            if row.get("path") is None:
                rows.append({"id": row["id"], "path": None, "status": "outside the index (gdrive index include -h)"})
                continue
            st = index_one(prov, man, idx, row, cfg, tmp, force=force)
            rows.append({"id": row["id"], "path": row["path"], "status": st})
    return rows


def md_target(text):
    """An index file path (~/.claude/gdrive/<profile>/index/<rel>.md) -> (profile, item id) or None."""
    p = Path(os.path.abspath(os.path.expanduser(text)))
    root = paths.root_peek().expanduser().resolve()
    try:
        rel = p.resolve().relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 3 or parts[1] != "index" or not p.name.endswith(".md"):
        return None
    prof = parts[0]
    if p.exists():
        head, _ = parse(p.read_text(encoding="utf-8")[:4096])
        if head.get("id"):
            return prof, head["id"]
    man = open_manifest(prof)
    try:
        row = man.by_path("/".join(parts[2:])[:-3])
    finally:
        man.close()
    if not row:
        raise UsageError(f"{text}: not a file of the {prof!r} index")
    return prof, row["id"]


# ---- one run at a time ---------------------------------------------------------------------

class Busy(Exception):
    def __init__(self, pid):
        super().__init__(pid)
        self.pid = pid


class Lock:
    """index.lock with the holder's pid; a dead holder's lock is taken over."""

    def __init__(self, name=None):
        self.path = profile.dir(name) / "index.lock"

    def holder(self):
        try:
            pid = int(self.path.read_text().strip() or 0)
        except (OSError, ValueError):
            return None
        return pid if proc.alive(pid) and pid != os.getpid() else None

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                pid = self.holder()
                if pid:
                    raise Busy(pid) from None
                self.path.unlink(missing_ok=True)
        raise Busy(None)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def log_path(name=None):
    return paths.sub(paths.data(), "logs") / f"index-{name or profile.active()}.log"


def command(name):
    """argv of a detached `gdrive index update` for a profile (also what the service runs)."""
    entry = Path(__file__).resolve().parents[2] / "gdrive.py"
    return [sys.executable, str(entry), "--profile", name, "index", "update", "--unbounded"]


def spawn(name):
    """Start a background run now. -> pid."""
    return proc.spawn(command(name), log_path(name))
