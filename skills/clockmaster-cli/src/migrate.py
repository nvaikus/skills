"""`migrate`: adopt an old task-scheduler install.

1. copy tasks/*.yaml, runs/, notify.yaml, memory.md, memory/ into the data dir
   — an identical file is skipped, a differing one is a conflict and is never
   overwritten; a run still in progress is skipped (copied on a later migrate);
2. retire the old schedules: macOS LaunchAgents `com.claude.task-scheduler.*`
   and `com.claude.task-scheduler-ui`; Windows tasks in `\\claude-task-scheduler`
   (the old tool had no Linux scheduler);
3. sync, so the copied tasks run under the new names.

The old data dir is only read. Running it again is harmless (idempotent).
"""
import json
import os
import shutil
import subprocess

import identity
import ops
from errors import NotFound, ValidationError

OLD_ENV = "TASK_SCHEDULER_HOME"
OLD_LABEL_PREFIX = "com.claude.task-scheduler."
OLD_UI_LABEL = "com.claude.task-scheduler-ui"
OLD_WIN_FOLDER = "\\claude-task-scheduler"
SINGLE = ("notify.yaml", "memory.md")


def old_dir(arg=None):
    if arg:
        return os.path.expanduser(arg)
    return os.environ.get(OLD_ENV) or str(identity.home() / ".claude" / "task-scheduler")


def _running(run_dir):
    try:
        with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as fh:
            return json.load(fh).get("status") == "running"
    except (OSError, ValueError):
        return False


def plan(src, dst):
    """[(rel, src_file, dst_file)] of every file migrate considers, plus the
    run dirs skipped as still running."""
    files, running = [], []

    def add(rel):
        files.append((rel, os.path.join(src, rel), os.path.join(dst, rel)))

    tdir = os.path.join(src, "tasks")
    if os.path.isdir(tdir):
        for f in sorted(os.listdir(tdir)):
            if f.endswith(".yaml") and os.path.isfile(os.path.join(tdir, f)):
                add(os.path.join("tasks", f))
    for f in SINGLE:
        if os.path.isfile(os.path.join(src, f)):
            add(f)
    for tree in ("runs", "memory"):
        root = os.path.join(src, tree)
        if not os.path.isdir(root):
            continue
        for cur, dirs, names in os.walk(root):
            dirs.sort()
            if tree == "runs" and "meta.json" in names and _running(cur):
                running.append(os.path.relpath(cur, src))
                dirs[:] = []
                continue
            for f in sorted(names):
                add(os.path.relpath(os.path.join(cur, f), src))
    return files, running


def _same(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() == fb.read()


def copy_files(files, dry):
    copied, same, conflicts = [], [], []
    for rel, s, d in files:
        if os.path.exists(d):
            (same if os.path.isfile(d) and _same(s, d) else conflicts).append(rel)
            continue
        copied.append(rel)
        if not dry:
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
    return copied, same, conflicts


# ---------- retire old schedules ----------

def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, errors="replace")


def old_launchd(dry):
    agents = identity.home() / "Library" / "LaunchAgents"
    if not agents.is_dir():
        return []
    out = []
    for p in sorted(agents.glob("com.claude.task-scheduler*.plist")):
        lbl = p.name[:-len(".plist")]
        if not (lbl.startswith(OLD_LABEL_PREFIX) or lbl == OLD_UI_LABEL):
            continue
        out.append(lbl)
        if not dry:
            _run(["launchctl", "bootout", f"gui/{os.getuid()}/{lbl}"])  # rc ignored: may be unloaded
            p.unlink()
    return out


def old_schtasks(dry):
    r = _run(["schtasks", "/query", "/fo", "CSV", "/nh", "/tn", OLD_WIN_FOLDER + "\\"])
    if r.returncode:
        return []
    prefix, out = OLD_WIN_FOLDER + "\\", []
    for line in r.stdout.splitlines():
        tn = line.split('","')[0].strip('"') if line.startswith('"') else ""
        if tn.startswith(prefix) and "\\" not in tn[len(prefix):] and tn not in out:
            out.append(tn)
    if not dry:
        for tn in out:
            _run(["schtasks", "/delete", "/tn", tn, "/f"])
    return out


def retire(dry):
    plat = identity.platform()
    if plat == "darwin":
        return [f"launchd agent {x}" for x in old_launchd(dry)]
    if plat == "win32":
        return [f"Task Scheduler task {x}" for x in old_schtasks(dry)]
    return []


# ---------- command ----------

def migrate(src, dry=False):
    """-> (rc, lines). rc 1 = done, but conflicts need a look."""
    dst = str(identity.data_dir())
    if not os.path.isdir(src):
        raise NotFound(f"no old install at {src} — pass --from DIR")
    if os.path.realpath(src) == os.path.realpath(dst):
        raise ValidationError(f"--from is the {identity.APP} data dir itself ({dst})")
    files, running = plan(src, dst)
    copied, same, conflicts = copy_files(files, dry)
    retired = retire(dry)
    would = "would " if dry else ""
    lines = [f"{'dry run: ' if dry else ''}migrate {src} -> {dst}"]
    lines += [f"+ {r}: {would}copy" if dry else f"+ {r}: copied" for r in copied if not r.startswith("runs")]
    nruns = sum(1 for r in copied if r.startswith("runs"))
    if nruns:
        lines.append(f"+ runs/: {nruns} file{'s' if nruns != 1 else ''} {'would copy' if dry else 'copied'}")
    lines += [f"! {r}: differs from the file already here — kept yours, compare by hand" for r in conflicts]
    lines += [f"… {r}: still running — skipped, run migrate again when it ends" for r in running]
    lines += [f"- {x}: {would}{'remove' if dry else 'removed'}" for x in retired]
    lines.append(f"{len(copied)} {would}{'copy' if dry else 'copied'}, {len(same)} identical, "
                 f"{len(conflicts)} conflict{'s' if len(conflicts) != 1 else ''}, "
                 f"{len(retired)} old schedule{'s' if len(retired) != 1 else ''} {would}{'retire' if dry else 'retired'}")
    if dry:
        lines.append(f"nothing changed; the old dir is never modified. Apply: {identity.APP} migrate")
        return (1 if conflicts else 0), lines
    ok, sync_lines = ops.sync()
    lines += sync_lines
    lines.append(f"the old dir is untouched — delete {src} yourself once happy")
    return (2 if not ok else 1 if conflicts else 0), lines


def main(args):
    dry = "--dry-run" in args
    src = None
    if "--from" in args:
        i = args.index("--from")
        if i + 1 >= len(args):
            raise ValidationError("--from needs a directory")
        src = args[i + 1]
    extra = [a for i, a in enumerate(args) if a not in ("--dry-run", "--from") and not (i and args[i - 1] == "--from")]
    if extra:
        raise ValidationError(f"unexpected argument '{extra[0]}' — usage: {identity.APP} migrate [--dry-run] [--from DIR]")
    rc, lines = migrate(old_dir(src), dry)
    for line in lines:
        print(line)
    return rc
