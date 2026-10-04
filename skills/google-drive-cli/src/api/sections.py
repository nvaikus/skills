"""Index sections of a what=/ profile: My Drive is always indexed; Shared with me, all Shared drives
or one Shared drive only after `gdrive index include`. The mount shows every section regardless."""
from ..core import config, profile
from ..core.errors import UsageError
from . import drive, indexer, providers

NAMES = ("shared-with-me", "shared-drives")


def normalize(remote, text):
    """User input -> stored section: shared-with-me | shared-drives | shared:<Drive> | shared:@<id>."""
    t = text.strip()
    low = t.lower().rstrip("/")
    if low in NAMES:
        return low
    if low in ("my-drive", "/"):
        return "my-drive"
    if low in (drive.SWM.rstrip(":"), drive.SWM, drive.SWM_DIR.lower()):
        return "shared-with-me"
    if low == drive.DRIVES_DIR.lower():
        return "shared-drives"
    if t.startswith("shared:") and t[len("shared:"):].strip("/"):
        name = t[len("shared:"):].strip("/")
        if "/" in name:
            raise UsageError("a section is a whole Shared drive (shared:<Drive>), not a folder inside it")
        if not name.startswith("@"):
            drive.shared_drive(remote, name)  # exit 2 with the list of drives when it does not exist
        return f"shared:{name}"
    raise UsageError(f"unknown section {text!r}: shared-with-me | shared-drives | shared:<Drive>")


def prefix(sec, prov):
    """Section -> its folder in the index/mount layout ('' = all of it)."""
    if sec == "shared-with-me":
        return drive.SWM_DIR
    if sec == "shared-drives":
        return drive.DRIVES_DIR
    if sec.startswith("shared:"):
        want = sec[len("shared:"):]
        d = next((d for d in prov.drives if want in (d["name"], f"@{d['id']}")), None)
        return f"{drive.DRIVES_DIR}/{prov.segs[d['id']]}" if d else None
    return drive.MY_DIR


def require_everything(cfg):
    what = providers.scope(cfg)
    if what != "/":
        raise UsageError(f"index sections exist only for a profile that mounts everything (/); this one mounts "
                         f"{what} and indexes just that")


def change(cfg, sec, add, note):
    """Store the new section list, relist metadata (texts of a removed section are deleted, of a
    re-added one kept), start the text extraction in the background. -> receipt row."""
    prof = profile.active()
    cur = providers.sections(cfg)
    if sec == "my-drive":
        if add:
            return {"profile": prof, "section": sec, "status": "always indexed"}
        raise UsageError("My Drive is always indexed")
    if (sec in cur) == add:
        status = "already indexed" if add else "not indexed"
        return {"profile": prof, "section": sec, "status": status}
    new = cur + [sec] if add else [s for s in cur if s != sec]
    cfg = config.update(index_sections=new)
    if not providers.new_layout(prof):
        note("the mount still has the old layout: the change applies after `gdrive mount` upgrades it")
        return {"profile": prof, "section": sec, "status": "included" if add else "excluded"}
    prov = providers.for_profile(cfg)
    row = {"profile": prof, "section": sec, "status": "included" if add else "excluded"}
    try:
        with indexer.Lock():
            man = indexer.open_manifest()
            try:
                gone, _, _ = indexer.sync_meta(prov, man, indexer.index_dir())
                moved = indexer.reconcile(man, indexer.index_dir(), prov.address, gone)
                pre = prefix(sec, prov)
                c = man.counts(pre) if add and pre else {}
            finally:
                man.close()
    except indexer.Busy as b:
        note(f"an index update is running (pid {b.pid}); the next run (within 5 min) applies this")
        return row
    if add:
        row.update(files=c.get("files"), pending=c.get("pending"), folder=pre)
        if c.get("pending"):
            row["pid"] = indexer.spawn(prof)
            note(f"indexing {c['pending']} file(s) in the background; progress: gdrive index status")
    else:
        row.update(deleted=moved["deleted"])
    return row
