"""index status: how complete and how fresh each profile's text index is."""
from datetime import datetime, timezone

from ...api import indexer, providers, service
from ...core import config, profile

PROFILE = "none"  # every profile unless --profile
FIELDS = ["profile", "scope", "sections", "files", "indexed", "pending", "errors", "updated", "age_min", "running", "service"]
EPILOG = """examples:
  gdrive index status
  gdrive --profile work index status -j        # + index_dir, meta_only, cursor, log

pending = files whose text is missing or older than the file (a build or catch-up is due).
age_min = minutes since the last complete update; the service runs every 5 min, so > 15 means
it is not running (service off, machine asleep, or login expired - see the log).
errors = files whose text could not be extracted (the .md holds a metadata line and the reason).
sections = what a profile mounting / indexes: my-drive always; shared-with-me, shared-drives,
shared:<Drive> only after `gdrive index include` (the mount shows them all anyway).
running = pid of an update in progress. Search: rg -n "words" <index_dir>
"""


def add_args(p):
    pass


def _age(ts):
    if not ts:
        return None
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return int((datetime.now(timezone.utc) - t).total_seconds() // 60)


def run(ctx, args):
    names = [profile.active()] if profile.explicit() else profile.names()
    rows = []
    for name in names:
        cfg = config.load(name)
        secs = ",".join(providers.sections(cfg)) if (cfg.get("mount") or {}).get("what") == "/" else None
        if not indexer.manifest_path(name).exists():
            rows.append({"profile": name, "scope": (cfg.get("mount") or {}).get("what"), "sections": secs, "files": None,
                         "updated": None, "running": indexer.Lock(name).holder(), "service": service.state(name),
                         "index_dir": str(indexer.index_dir(name)), "log": str(indexer.log_path(name))})
            continue
        man = indexer.open_manifest(name)
        try:
            c = man.counts()
            upd = man.meta("last_update")
            rows.append({"profile": name, "scope": (cfg.get("mount") or {}).get("what"), "sections": secs, **c, "updated": upd,
                         "age_min": _age(upd), "running": indexer.Lock(name).holder(), "service": service.state(name),
                         "cursor": man.meta("cursor"), "index_dir": str(indexer.index_dir(name)),
                         "log": str(indexer.log_path(name))})
        finally:
            man.close()
    if not rows:
        ctx.note("no profiles yet: gdrive onboard --profile NAME")
    ctx.write(rows, FIELDS)
