#!/usr/bin/env python3
"""skilltap - install single Claude Code skills from git repos and keep them current.

One file, Python 3.8+ stdlib only, macOS / Linux / Windows.
MIT License - https://github.com/nvaikus/skills/tree/main/skilltap
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VERSION = "1.0.0"
HOME_REPO = "https://github.com/nvaikus/skills/tree/main/skilltap"
SELF = "skilltap"
IGNORED_NAMES = {".git", "__pycache__", ".DS_Store"}
IGNORED_SUFFIXES = (".pyc",)
IS_WIN = os.name == "nt"
HOOK_TIMEOUT = 120
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_rename = os.rename  # indirection so tests can simulate a locked target


class Fail(Exception):
    """User-facing error: printed as one line, exit 1."""


# ---------------------------------------------------------------- paths

def config_root():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")).expanduser().absolute()


def state_dir():
    return config_root() / "skilltap"


def skills_dir():
    return config_root() / "skills"


def sources_dir():
    return state_dir() / "sources"


def lock_file():
    return state_dir() / "lock.json"


def default_list():
    return config_root() / "baseline" / "skills.json"


def config_file():
    return state_dir() / "config.json"


# ---------------------------------------------------------------- output

class Out:
    quiet = False
    warned = False


def say(msg):
    """A change worth reporting - always printed (hooks show it to the model)."""
    print(f"skilltap: {msg}", flush=True)


def info(msg):
    """Chatter - suppressed by --quiet."""
    if not Out.quiet:
        print(msg, flush=True)


def warn(msg):
    Out.warned = True
    print(f"skilltap: warning: {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- json io

def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except ValueError as e:
        raise Fail(f"{path}: invalid JSON ({e})")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def load_lock():
    data = read_json(lock_file(), {})
    data.setdefault("version", 1)
    data.setdefault("skills", {})
    return data


def save_lock(data):
    write_json(lock_file(), data)


# ---------------------------------------------------------------- mutex

class Mutex:
    """Cross-process lock via mkdir (atomic everywhere). Stale after 10 min."""

    STALE = 600

    def __init__(self, wait):
        self.dir = state_dir() / ".busy"
        self.wait = wait
        self.held = False

    def __enter__(self):
        self.dir.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.wait
        while True:
            try:
                self.dir.mkdir()
                self.held = True
                return True
            except FileExistsError:
                try:
                    if time.time() - self.dir.stat().st_mtime > self.STALE:
                        shutil.rmtree(str(self.dir), ignore_errors=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() >= deadline:
                    return False
                time.sleep(0.2)

    def __exit__(self, *exc):
        if self.held:
            shutil.rmtree(str(self.dir), ignore_errors=True)


def locked(wait=120):
    return Mutex(wait)


# ---------------------------------------------------------------- git

def git_timeout(kind="net"):
    base = int(os.environ.get("SKILLTAP_GIT_TIMEOUT", "60"))
    return base * 5 if kind == "clone" else base


def git(args, cwd=None, check=True, timeout=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    cmd = ["git", "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=20"] + list(args)
    limit = timeout or git_timeout()
    try:
        r = subprocess.run(cmd, cwd=None if cwd is None else str(cwd), env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           errors="replace", timeout=limit)
    except subprocess.TimeoutExpired:
        raise Fail(f"git {args[0]} timed out after {limit}s (offline?)")
    except FileNotFoundError:
        raise Fail("git not found on PATH")
    if check and r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()
        raise Fail(f"git {args[0]} failed: {tail[-1] if tail else 'exit ' + str(r.returncode)}")
    return r


def head(repo_dir):
    r = git(["rev-parse", "HEAD"], cwd=repo_dir, check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def behind_count(repo_dir):
    r = git(["rev-list", "--count", "HEAD..@{u}"], cwd=repo_dir, check=False)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def norm_url(url):
    """Comparable form of a repo URL: host/owner/repo, no scheme/user/.git."""
    u = url.strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    u = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)
    m = re.match(r"^([^/:]+):(?!\d+/)(.*)$", u)  # scp-like host:path
    if m and not re.match(r"^[A-Za-z]$", m.group(1)):
        u = m.group(1) + "/" + m.group(2)
    return u.replace("\\", "/").lower()


def same_repo(a, b):
    return norm_url(a) == norm_url(b)


def remap_url(url):
    """Per-host source override from <root>/skilltap/config.json {"remap": {"<from>": "<to>"}}.

    Keys match any URL form of the same repo (scheme, .git, trailing slash, case)."""
    table = read_json(config_file(), {}).get("remap") or {}
    if not isinstance(table, dict):
        raise Fail(f"{config_file()}: 'remap' must be an object of repo URL -> repo URL")
    for src, dst in table.items():
        if same_repo(src, url):
            return dst
    return url


def slug(url):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", norm_url(url)).strip("-.")
    if len(s) > 80:
        s = s[:60] + "-" + hashlib.sha1(s.encode()).hexdigest()[:10]
    return s or "repo"


def upstream(repo_dir):
    r = git(["rev-parse", "@{u}"], cwd=repo_dir, check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def pull(repo_dir):
    """Fetch + rebase onto upstream (local commits and edits survive). Returns True if HEAD moved.

    Upstream history rewritten (force push, repo recreated) and the clone holds no own work
    (HEAD was the old upstream, tree clean) -> reset to the new upstream instead of failing."""
    before, up_before = head(repo_dir), upstream(repo_dir)
    r = git(["pull", "--rebase", "--autostash", "--quiet"], cwd=repo_dir, check=False)
    if r.returncode != 0:
        gitdir = Path(repo_dir) / ".git"
        if (gitdir / "rebase-merge").exists() or (gitdir / "rebase-apply").exists():
            git(["rebase", "--abort"], cwd=repo_dir, check=False)
        up_now = upstream(repo_dir)
        clean = not git(["status", "--porcelain"], cwd=repo_dir, check=False).stdout.strip()
        if before and before == up_before and up_now and up_now != up_before and clean:
            git(["reset", "--hard", "--quiet", "@{u}"], cwd=repo_dir)
            say(f"{Path(repo_dir).name}: upstream history was rewritten; clone reset to it")
            return head(repo_dir) != before
        tail = (r.stderr or r.stdout).strip().splitlines()
        raise Fail(f"pull failed in {repo_dir}: {tail[-1] if tail else 'exit ' + str(r.returncode)}")
    return head(repo_dir) != before


def ensure_source(repo, update):
    """Clone the repo if needed; optionally pull it. Returns the clone dir."""
    d = sources_dir() / slug(repo)
    if (d / ".git").exists():
        if update:
            try:
                pull(d)
            except Fail as e:
                warn(str(e))
        return d
    d.parent.mkdir(parents=True, exist_ok=True)
    tmp = d.with_name(f".{d.name}.partial-{uuid.uuid4().hex[:8]}")
    try:
        git(["clone", "--quiet", repo, str(tmp)], timeout=git_timeout("clone"))
        _rename(str(tmp), str(d))
    finally:
        if tmp.exists():
            rmtree(tmp)
    return d


def clone_is_clean(repo_dir):
    st = git(["status", "--porcelain"], cwd=repo_dir, check=False)
    ahead = git(["rev-list", "--count", "@{u}..HEAD"], cwd=repo_dir, check=False)
    return st.returncode == 0 and not st.stdout.strip() and ahead.stdout.strip() in ("0", "")


# ---------------------------------------------------------------- trees

def rmtree(path):
    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    p = str(path)
    if os.path.islink(p):
        os.unlink(p)
    elif os.path.exists(p):
        shutil.rmtree(p, onerror=onerror)


def walk(root):
    """Yield (posix relpath, kind) for files ('F') and symlinks ('L'), sorted, filtered."""
    root = str(root)
    for cur, dirs, files in os.walk(root):
        keep = []
        for d in sorted(dirs):
            if d in IGNORED_NAMES:
                continue
            full = os.path.join(cur, d)
            if os.path.islink(full):
                yield os.path.relpath(full, root).replace(os.sep, "/"), "L"
            else:
                keep.append(d)
        dirs[:] = keep
        for f in sorted(files):
            if f in IGNORED_NAMES or f.endswith(IGNORED_SUFFIXES):
                continue
            full = os.path.join(cur, f)
            kind = "L" if os.path.islink(full) else "F"
            yield os.path.relpath(full, root).replace(os.sep, "/"), kind


def tree_hash(root):
    root = Path(root)
    if not root.is_dir():
        return None
    h = hashlib.sha256()
    for rel, kind in sorted(walk(root)):
        full = root / rel
        h.update(kind.encode() + rel.encode("utf-8", "surrogateescape") + b"\0")
        if kind == "L":
            h.update(os.readlink(str(full)).encode("utf-8", "surrogateescape"))
        else:
            if not IS_WIN:
                h.update(b"x" if full.stat().st_mode & 0o111 else b"-")
            with open(str(full), "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 16), b""):
                    h.update(chunk)
        h.update(b"\0")
    return h.hexdigest()


def copy_tree(src, dst):
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True)
    for rel, kind in walk(src):
        s, t = src / rel, dst / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        if kind == "L":
            try:
                os.symlink(os.readlink(str(s)), str(t))
                continue
            except OSError:
                if s.is_dir():
                    shutil.copytree(str(s), str(t))
                    continue
        shutil.copy2(str(s), str(t))


def staging_base():
    base = state_dir() / "staging"
    base.mkdir(parents=True, exist_ok=True)
    skills_dir().mkdir(parents=True, exist_ok=True)
    if os.stat(str(base)).st_dev != os.stat(str(skills_dir())).st_dev:
        base = skills_dir().resolve().parent / ".skilltap-staging"
        base.mkdir(parents=True, exist_ok=True)
    return base


def swap_in(src, name):
    """Build a copy of src outside skills/, then swap it in by rename.

    Returns False (old copy kept) when the installed folder cannot be moved,
    e.g. a file in it is open on Windows."""
    target = skills_dir() / name
    base = staging_base()
    tag = uuid.uuid4().hex[:8]
    stage, old = base / f"{name}.new-{tag}", base / f"{name}.old-{tag}"
    copy_tree(src, stage)
    moved_old = False
    try:
        if target.exists() or target.is_symlink():
            try:
                _rename(str(target), str(old))
                moved_old = True
            except OSError as e:
                warn(f"{name}: installed copy is in use ({e.strerror or e}); kept the old version, retry later")
                return False
        try:
            _rename(str(stage), str(target))
        except OSError as e:
            if moved_old:
                _rename(str(old), str(target))
                moved_old = False
            raise Fail(f"{name}: could not install new copy ({e.strerror or e}); old copy kept")
        return True
    finally:
        rmtree(stage)
        if moved_old:
            rmtree(old)


def backup_installed(name):
    src = skills_dir() / name
    dst = state_dir() / "backups" / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while dst.exists():
        dst = dst.with_name(f"{dst.name}-{n}")
        n += 1
    copy_tree(src, dst)
    return dst


# ---------------------------------------------------------------- skill helpers

def frontmatter_name(skill_md):
    try:
        lines = Path(skill_md).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^name\s*:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip("'\"") or None
    return None


def derive_name(skill_path, repo, path):
    name = frontmatter_name(Path(skill_path) / "SKILL.md")
    if not name:
        name = Path(path).name if path else norm_url(repo).rsplit("/", 1)[-1]
    return name


def parse_target(target):
    """['<url>'] or ['<git-url>', '<path>'] -> (repo, path, ref)."""
    if len(target) == 2:
        return target[0], target[1].strip("/").replace("\\", "/"), None
    if len(target) != 1:
        raise Fail("expected <url> or <git-url> <path>")
    url = target[0].strip()
    m = re.match(r"^(https?://[^/]+/.+?)(?:/-)?/(?:blob|tree)/([^/]+)(?:/(.*))?$", url)
    if m:
        repo, ref, path = m.group(1), m.group(2), (m.group(3) or "")
        if not repo.endswith(".git"):
            repo += ".git"
        return repo, path.strip("/"), ref
    if re.match(r"^https?://", url) and not url.rstrip("/").endswith(".git"):
        url = url.rstrip("/") + ".git"
    return url, "", None


def source_of(entry):
    return sources_dir() / entry.get("source", slug(entry["repo"]))


def short_source(entry):
    return f"{norm_url(entry['repo'])}:{entry.get('path') or '.'}"


def sync_one(name, entry, keep_edits=True):
    """Mirror one skill from its clone. Returns a change verb or None."""
    clone = source_of(entry)
    src = clone / entry.get("path", "")
    if not (src / "SKILL.md").is_file():
        warn(f"{name}: no SKILL.md at {short_source(entry)} - skipped")
        return None
    target = skills_dir() / name
    if target.is_symlink():
        warn(f"{name}: {target} is a symlink, not managed by skilltap - skipped")
        return None
    src_hash = tree_hash(src)
    cur_hash = tree_hash(target)
    if cur_hash is not None and src_hash == cur_hash:
        changed = entry.get("hash") != src_hash
        entry["hash"], entry["commit"] = src_hash, head(clone)
        return "adopted" if changed else None
    verb = "installed" if cur_hash is None else "updated"
    note = ""
    if keep_edits and cur_hash is not None and cur_hash != entry.get("hash"):
        note = f" (local edits saved to {backup_installed(name)})"
    if not swap_in(src, name):
        return None
    entry["hash"], entry["commit"] = src_hash, head(clone)
    return verb + note


def wrapper_body():
    if IS_WIN:
        return ('@echo off\r\nif defined CLAUDE_CONFIG_DIR (\r\n'
                '  python "%CLAUDE_CONFIG_DIR%\\skills\\skilltap\\skilltap.py" %*\r\n'
                ') else (\r\n  python "%USERPROFILE%\\.claude\\skills\\skilltap\\skilltap.py" %*\r\n)\r\n')
    return '#!/bin/sh\nexec python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/skilltap/skilltap.py" "$@"\n'


def ensure_wrapper():
    bindir = Path.home() / ".local" / "bin"
    f = bindir / ("skilltap.cmd" if IS_WIN else "skilltap")
    body = wrapper_body()
    try:
        if f.is_file() and f.read_text(encoding="utf-8", errors="replace") == body:
            return
        if (f.exists() or f.is_symlink()) and "skilltap" not in (f.read_text(errors="replace") if f.is_file() else ""):
            warn(f"{f} exists and is not a skilltap wrapper - left alone")
            return
        bindir.mkdir(parents=True, exist_ok=True)
        if f.is_symlink():
            f.unlink()
        f.write_text(body, encoding="utf-8", newline="")
        if not IS_WIN:
            f.chmod(0o755)
        info(f"wrapper: {f}")
        if str(bindir) not in os.environ.get("PATH", "").split(os.pathsep):
            info(f"note: {bindir} is not on PATH")
    except OSError as e:
        warn(f"could not write wrapper {f}: {e}")


def drop_source_if_orphan(lock, entry):
    sl = entry.get("source", slug(entry["repo"]))
    if any(e.get("source", slug(e["repo"])) == sl for e in lock["skills"].values()):
        return
    d = sources_dir() / sl
    if (d / ".git").exists() and clone_is_clean(d):
        rmtree(d)
    elif d.exists():
        info(f"kept clone {d} (uncommitted or unpushed work)")


# ---------------------------------------------------------------- install core

def install(lock, name, repo, path, origin, update_clone=True, force=False):
    """Track + mirror one skill. Returns change verb or None. Raises Fail."""
    clone = ensure_source(repo, update=update_clone)
    if (clone / path).is_file():
        parent = Path(path).parent.as_posix()
        path = "" if parent == "." else parent
    if path and not (clone / path).is_dir():
        raise Fail(f"path '{path}' not found in {repo}")
    if not (clone / path / "SKILL.md").is_file():
        raise Fail(f"no SKILL.md in {repo} at '{path or '.'}'")
    if name is None:
        name = derive_name(clone / path, repo, path)
    if not NAME_RE.match(name):
        raise Fail(f"bad skill name '{name}' (use --name)")
    cur = lock["skills"].get(name)
    target = skills_dir() / name
    if cur and not (same_repo(cur["repo"], repo) and cur.get("path", "") == path) and not force:
        raise Fail(f"{name} is already tracked from {short_source(cur)}; --force switches it")
    if not cur and (target.exists() or target.is_symlink()):
        if not force:
            raise Fail(f"{target} exists and is not tracked; --force replaces it (old copy backed up)")
        if target.is_symlink():
            target.unlink()
        else:
            info(f"backup: {backup_installed(name)}")
    entry = {"repo": repo, "path": path, "origin": origin, "source": slug(repo)}
    if cur:
        entry["hash"] = cur.get("hash")                 # last synced copy: edits are judged against it
    verb = sync_one(name, entry, keep_edits=bool(cur))
    if tree_hash(target) is None:
        raise Fail(f"{name}: install failed")
    lock["skills"][name] = entry
    if cur and cur.get("source", slug(cur["repo"])) != entry["source"]:
        drop_source_if_orphan(lock, cur)                # source switched: old clone may be unused now
    return name, verb


# ---------------------------------------------------------------- commands

def cmd_get(a):
    repo, path, ref = parse_target(a.target)
    mapped = remap_url(repo)
    if not same_repo(mapped, repo):
        info(f"remap: {norm_url(repo)} -> {norm_url(mapped)} ({config_file()})")
        repo = mapped
    with locked() as ok:
        if not ok:
            raise Fail("another skilltap run holds the lock; retry")
        lock = load_lock()
        name, verb = install(lock, a.name, repo, path, "user", force=a.force)
        save_lock(lock)
    entry = lock["skills"][name]
    clone = source_of(entry)
    if ref:
        br = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=clone, check=False).stdout.strip()
        if br and br != ref and not re.match(r"^[0-9a-f]{7,40}$", ref):
            warn(f"URL names ref '{ref}', skilltap tracks the clone's branch '{br}'")
    print(f"{name}: {verb or 'up to date'} <- {short_source(entry)}")
    if name == SELF:
        ensure_wrapper()
    return 0


def refresh_sources(lock):
    repos = {}
    for e in lock["skills"].values():
        repos.setdefault(e.get("source", slug(e["repo"])), e["repo"])

    def one(item):
        sl, repo = item
        d = sources_dir() / sl
        try:
            if (d / ".git").exists():
                pull(d)
            else:
                ensure_source(repo, update=False)
        except Fail as e:
            return str(e)
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for err in pool.map(one, sorted(repos.items())):
            if err:
                warn(err)


def apply_list(lock, list_path):
    list_path = Path(list_path).expanduser().absolute()
    tag = f"list:{list_path}"
    wanted = read_json(list_path, None)
    if wanted is None:
        raise Fail(f"list not found: {list_path}")
    wanted = {n: dict(s, repo=remap_url(s["repo"]), path=s.get("path", "").strip("/"))
              for n, s in wanted.get("skills", {}).items()}
    stale = set()                                     # list is newer than the clone: pull it first
    for spec in wanted.values():
        clone = sources_dir() / slug(spec["repo"])
        if (clone / ".git").exists() and not (clone / spec["path"] / "SKILL.md").is_file():
            stale.add(clone)
    for clone in sorted(stale):
        try:
            pull(clone)
        except Fail as e:
            warn(str(e))
    for name, spec in sorted(wanted.items()):
        cur = lock["skills"].get(name)
        same = cur and same_repo(cur["repo"], spec["repo"]) and cur.get("path", "") == spec.get("path", "").strip("/")
        if same:
            continue                                  # incl. a user's own copy of the same skill
        if cur and cur.get("origin") != tag:
            continue                                  # user's or another list's skill under this name
        target = skills_dir() / name
        if not cur and (target.exists() or target.is_symlink()):
            info(f"skilltap: {name} skipped (list): untracked folder {target} is in the way; "
                 f"replace it with: skilltap get {spec['repo']} {spec.get('path', '') or '.'} --force")
            continue                                  # untracked real dir: not ours
        try:
            _, verb = install(lock, name, spec["repo"], spec.get("path", "").strip("/"), tag,
                              update_clone=False, force=bool(cur))
            say(f"{name} {'switched source' if cur else 'installed'} (list)")
        except Fail as e:
            warn(f"{name}: {e}")
    for name, e in sorted(lock["skills"].items()):
        if e.get("origin") == tag and name not in wanted:
            del lock["skills"][name]
            rmtree(skills_dir() / name)
            drop_source_if_orphan(lock, e)
            say(f"{name} removed (dropped from list)")


def cmd_apply(a):
    with locked(wait=0 if a.quiet else 120) as ok:
        if not ok:
            return 0 if a.quiet else fail_busy()
        lock = load_lock()
        apply_list(lock, a.list)
        save_lock(lock)
    return 0


def fail_busy():
    raise Fail("another skilltap run holds the lock; retry")


def cmd_refresh(a):
    with locked(wait=0 if a.quiet else 120) as ok:
        if not ok:
            return 0 if a.quiet else fail_busy()
        lock = load_lock()
        if a.apply:
            if Path(a.apply).expanduser().exists():
                apply_list(lock, a.apply)
                save_lock(lock)
            elif not a.quiet:
                warn(f"list not found: {a.apply}")
        last = lock.get("refreshed_at", 0)
        if a.if_older is not None and time.time() - last < a.if_older * 3600:
            info(f"fresh (last refresh {int((time.time() - last) / 60)} min ago)")
            return 0
        refresh_sources(lock)
        changed = 0
        for name, entry in sorted(lock["skills"].items()):
            try:
                verb = sync_one(name, entry)
            except (Fail, OSError) as e:
                warn(f"{name}: {e}")
                continue
            if verb and verb != "adopted":
                say(f"{name} {verb}")
                changed += 1
        lock["refreshed_at"] = int(time.time())
        save_lock(lock)
    if SELF in lock["skills"]:
        ensure_wrapper()
    if not changed:
        info("all skills up to date")
    return 1 if (Out.warned and not a.quiet) else 0


def cmd_forget(a, delete=False):
    with locked() as ok:
        if not ok:
            fail_busy()
        lock = load_lock()
        entry = lock["skills"].pop(a.name, None)
        if entry is None:
            raise Fail(f"{a.name} is not tracked (see: skilltap status)")
        if delete:
            rmtree(skills_dir() / a.name)
        drop_source_if_orphan(lock, entry)
        save_lock(lock)
    print(f"{a.name}: {'removed' if delete else 'no longer tracked; folder kept'}")
    return 0


def skill_state(name, entry):
    target = skills_dir() / name
    cur = tree_hash(target)
    if cur is None:
        return "missing"
    if cur != entry.get("hash"):
        return "local edits"
    clone = source_of(entry)
    if not (clone / ".git").exists():
        return "outdated"
    if tree_hash(clone / entry.get("path", "")) != entry.get("hash") or behind_count(clone) > 0:
        return "outdated"
    return "ok"


def cmd_status(a):
    lock = load_lock()
    rows = []
    for name, e in sorted(lock["skills"].items()):
        rows.append({"name": name, "source": short_source(e), "origin": e.get("origin", "user"),
                     "state": skill_state(name, e), "clone": str(source_of(e) / e.get("path", ""))})
    if a.json:
        print(json.dumps({"root": str(config_root()), "refreshed_at": lock.get("refreshed_at"),
                          "skills": rows}, indent=2))
        return 0
    if not rows:
        print("no tracked skills")
        return 0
    cols = ["name", "source", "origin", "state"]
    width = {c: max(len(c), *(len(r[c]) for r in rows)) for c in cols}
    print("  ".join(c.upper().ljust(width[c]) for c in cols).rstrip())
    for r in rows:
        print("  ".join(r[c].ljust(width[c]) for c in cols).rstrip())
    return 0


def cmd_where(a):
    lock = load_lock()
    e = lock["skills"].get(a.name)
    if e is None:
        raise Fail(f"{a.name} is not tracked")
    print(source_of(e) / e.get("path", ""))
    return 0


def hook_command(with_list):
    py = "python" if IS_WIN else "python3"
    script = config_root() / "skills" / SELF / "skilltap.py"
    cmd = f'{py} "{script}" refresh --quiet --if-older 24'
    if with_list:
        cmd += f' --apply "{default_list()}"'
    return cmd


def edit_session_hooks(drop):
    """Remove SessionStart hook commands for which drop(cmd) is true. Returns removed count."""
    path = config_root() / "settings.json"
    data = read_json(path, {})
    groups = data.get("hooks", {}).get("SessionStart", [])
    removed = 0
    for g in groups:
        keep = [h for h in g.get("hooks", []) if not drop(h.get("command", ""))]
        removed += len(g.get("hooks", [])) - len(keep)
        g["hooks"] = keep
    if removed:
        data["hooks"]["SessionStart"] = [g for g in groups if g.get("hooks")]
        write_json(path, data)
    return removed


def install_hook():
    path = config_root() / "settings.json"
    data = read_json(path, {})
    want = {"type": "command", "command": hook_command(default_list().exists()), "timeout": HOOK_TIMEOUT}
    groups = data.setdefault("hooks", {}).setdefault("SessionStart", [])
    found = False
    changed = False
    for g in groups:
        keep = []
        for h in g.get("hooks", []):
            if "skilltap.py" not in h.get("command", ""):
                keep.append(h)
            elif not found and g.get("matcher") == "startup":
                found = True
                if h != want:
                    h.clear()
                    h.update(want)
                    changed = True
                keep.append(h)
            else:
                changed = True                  # duplicate or wrong matcher: drop
        g["hooks"] = keep
    if not found:
        groups.append({"matcher": "startup", "hooks": [want]})
        changed = True
    data["hooks"]["SessionStart"] = [g for g in groups if g.get("hooks")]
    if changed:
        write_json(path, data)
    return changed


def cmd_hook(a):
    changed = install_hook()
    print(f"SessionStart hook {'written' if changed else 'already set'}: {config_root() / 'settings.json'}")
    ensure_wrapper()
    return 0


def is_old_tool_hook(cmd):
    return "skillsync" in cmd or "baseline-skills" in cmd


def cmd_migrate(a):
    old = config_root() / "skillsync"
    manifest = read_json(old / "manifest.json", None)
    if manifest is None:
        raise Fail(f"nothing to migrate: {old / 'manifest.json'} not found")
    adopted = set(read_json(old / "baseline-state.json", {}).get("installed", []))
    tag = f"list:{default_list()}"
    with locked() as ok:
        if not ok:
            fail_busy()
        lock = load_lock()
        for name, spec in sorted(manifest.get("skills", {}).items()):
            repo, path = spec["repo"], spec.get("path", "").strip("/")
            dst = sources_dir() / slug(repo)
            olddir = old / "repos" / spec.get("dir", "-")
            if not (dst / ".git").exists() and (olddir / ".git").exists():
                remote = git(["remote", "get-url", "origin"], cwd=olddir, check=False).stdout.strip()
                if same_repo(remote, repo):
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(olddir), str(dst))
                    print(f"moved clone {olddir} -> {dst}")
            try:
                ensure_source(repo, update=False)
            except Fail as e:
                warn(f"{name}: {e} - not migrated")
                continue
            entry = {"repo": repo, "path": path, "origin": tag if name in adopted else "user",
                     "source": slug(repo)}
            try:
                verb = sync_one(name, entry)
            except (Fail, OSError) as e:
                warn(f"{name}: {e} - not migrated")
                continue
            if entry.get("hash") is None:
                warn(f"{name}: could not mirror - not migrated")
                continue
            lock["skills"][name] = entry
            print(f"{name}: tracked ({entry['origin']}){', ' + verb if verb and verb != 'adopted' else ''}")
        save_lock(lock)
    removed = edit_session_hooks(is_old_tool_hook)
    if removed:
        print(f"removed {removed} old SessionStart hook(s)")
    install_hook()
    print("skilltap SessionStart hook set")
    if Out.warned:
        raise Fail(f"migration incomplete; {old} kept - fix warnings and rerun")
    rmtree(old)
    rmtree(skills_dir() / "skillsync")
    for w in ("skillsync", "skillsync.cmd"):
        f = Path.home() / ".local" / "bin" / w
        if f.is_file() and "skillsync" in f.read_text(errors="replace"):
            f.unlink()
    print(f"deleted {old} and {skills_dir() / 'skillsync'}")
    ensure_wrapper()
    return 0


# ---------------------------------------------------------------- cli

def build_parser():
    p = argparse.ArgumentParser(
        prog="skilltap",
        description="Install single Claude Code skills from git repos and keep them current. "
                    "Root: $CLAUDE_CONFIG_DIR or ~/.claude; state in <root>/skilltap/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 ok, 1 failed (or refresh had warnings), 2 usage.")
    p.add_argument("--version", action="version", version=f"skilltap {VERSION}")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")
    sub.required = True
    raw = argparse.RawDescriptionHelpFormatter

    s = sub.add_parser("get", formatter_class=raw, help="install a skill from a git repo and track it",
                       epilog="Examples:\n"
                              "  skilltap get https://github.com/o/r/tree/main/skills/foo\n"
                              "  skilltap get https://github.com/o/r/blob/main/skills/foo/SKILL.md\n"
                              "  skilltap get https://gitlab.example.com/g/r/-/tree/main/foo\n"
                              "  skilltap get https://github.com/o/r          # SKILL.md at repo root\n"
                              "  skilltap get git@github.com:o/r.git skills/foo\n"
                              "Name = SKILL.md frontmatter 'name:', else the folder name. The clone's\n"
                              "default branch is tracked; a /tree/<ref>/ in the URL does not pin it.")
    s.add_argument("target", nargs="+", metavar="<url> | <git-url> <path>")
    s.add_argument("--name", help="install under this name instead")
    s.add_argument("--force", action="store_true",
                   help="replace an untracked folder (backed up) or switch a tracked skill's source")
    s.set_defaults(fn=cmd_get)

    s = sub.add_parser("refresh", formatter_class=raw, help="pull all sources and mirror tracked skills",
                       epilog="Pulls each clone (rebase + autostash, never pushes), then swaps changed\n"
                              "skills into <root>/skills/ atomically. Edits found in an installed copy\n"
                              "are backed up to <root>/skilltap/backups/ and overwritten.\n"
                              "Examples:\n"
                              "  skilltap refresh\n"
                              "  skilltap refresh --quiet --if-older 24 --apply ~/.claude/baseline/skills.json")
    s.add_argument("--quiet", action="store_true", help="print only changes; never fail; skip if busy")
    s.add_argument("--if-older", type=float, metavar="HOURS", help="skip when the last refresh is newer")
    s.add_argument("--apply", metavar="LIST", help="first reconcile this list (see 'apply'); missing file is ignored")
    s.set_defaults(fn=cmd_refresh)

    s = sub.add_parser("apply", formatter_class=raw, help="reconcile an admin-managed skill list",
                       epilog='List format: {"skills": {"<name>": {"repo": "<git-url>", "path": "<dir>"}}}\n'
                              "Installs missing ones (origin list:<path>), removes ones this list installed\n"
                              "and no longer names. Never touches origin 'user' skills or untracked folders;\n"
                              "a user skill with the same repo+path stays 'user'. List repos (and 'get' URLs)\n"
                              "pass through the remap in <root>/skilltap/config.json first.")
    s.add_argument("list")
    s.add_argument("--quiet", action="store_true", help="skip silently if busy")
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("status", help="table: name, source, origin, state (ok/outdated/missing/local edits)")
    s.add_argument("--json", action="store_true", help="JSON, includes each skill's clone path")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("where", help="print the source-clone folder of a tracked skill (edit there)")
    s.add_argument("name")
    s.set_defaults(fn=cmd_where)

    s = sub.add_parser("forget", help="stop tracking a skill; keep its folder")
    s.add_argument("name")
    s.set_defaults(fn=lambda a: cmd_forget(a, delete=False))

    s = sub.add_parser("remove", help="stop tracking a skill and delete its folder")
    s.add_argument("name")
    s.set_defaults(fn=lambda a: cmd_forget(a, delete=True))

    s = sub.add_parser("hook", help="add the SessionStart auto-refresh hook to settings.json (idempotent)")
    s.set_defaults(fn=cmd_hook)

    s = sub.add_parser("migrate-from-skillsync", help="take over skills managed by the older skillsync tool")
    s.set_defaults(fn=cmd_migrate)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    Out.quiet = bool(getattr(a, "quiet", False))
    Out.warned = False
    try:
        return a.fn(a) or 0
    except Fail as e:
        if Out.quiet:
            warn(str(e))
            return 0
        print(f"skilltap: error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # a session hook must never blow up loudly
        if Out.quiet:
            warn(f"unexpected: {e!r}")
            return 0
        raise


if __name__ == "__main__":
    sys.exit(main())
