"""mount: Drive at a local dir in the background; returns once the dir is really usable."""
from ...api import mounting, mounts
from ...core import config
from ...core.errors import Deadline, UsageError

FIELDS = ["id", "profile", "mode", "what", "where", "state", "persist"]
WRITE = True
WAIT = True
EPILOG = """examples:
  gdrive mount                                     # what the profile's onboarding chose
  gdrive mount / ~/gdrive/work                     # everything: My Drive/, Shared with me/, Shared drives/<name>/
  gdrive --profile nj mount "shared:Team Drive" ~/gdrive/nj --persist   # back after reboot/login
  gdrive mount / ~/gdrive/work --mode sync          # a local folder kept in sync (no mount)

Mechanism: Linux rclone mount (FUSE) · macOS rclone nfsmount (no admin) · Windows mount with
WinFsp. No FUSE/WinFsp (containers) -> sync folder: a two-way `rclone bisync`; run `gdrive sync`
after writing and before reading fresh remote changes. Sync folders skip Google Docs/Sheets.
Writes land in a local VFS cache (--vfs-cache-mode full, ~/.cache/gdrive/<profile>/<id>) and
upload ~5 s later: `gdrive sync <dir>` waits for them, `gdrive umount` refuses while any are
pending. TRAP: Google Docs/Sheets/Slides show as .docx/.xlsx/.pptx exports - readable on Linux/
Windows; on macOS (nfsmount) they are 0 bytes and read EMPTY. Saving one creates a SEPARATE uploaded
Office file. Read and edit them with `gdrive doc|sheet` (a mount path works).
Layout of /: <where>/My Drive/..., <where>/Shared with me/... (flat list of what others shared),
<where>/Shared drives/<name>/... (only when the account has any; the list is fixed at mount time -
remount to see a new one). TRAP: a file saved at the top of Shared with me lands in the My Drive
root; inside items shared view-only it never uploads (`gdrive sync` reports it) - write under My Drive/. A / mount made before this layout is switched to it by the next `gdrive mount`.
WHERE must be empty or new (Windows: must not exist). Exit 6: still starting, nothing undone.
"""


def add_args(p):
    p.add_argument("what", nargs="?", help="/ , /Folder/Sub , or shared:<Shared drive>[/Sub] (default: profile config)")
    p.add_argument("where", nargs="?", help="local directory, created if missing (default: profile config)")
    p.add_argument("--mode", choices=mounts.MODES, default="auto", help="auto (default): mount if possible, else sync")
    p.add_argument("--persist", action="store_true", help="install autostart: systemd user unit / LaunchAgent")
    p.add_argument("--cache-limit", metavar="SIZE", help="VFS cache cap, e.g. 20G (default: config cache_limit, 10G)")


def run(ctx, args):
    chosen = ctx.cfg.get("mount") or {}
    what = args.what or chosen.get("what")
    where = args.where or chosen.get("where")
    if not what or not where:
        raise UsageError("give WHAT and WHERE (e.g. gdrive mount / ~/gdrive/work), or choose them once with `gdrive onboard`")
    keep = args.persist or (not args.what and bool(chosen.get("persist")))
    state, status = mounting.bring_up(ctx.cfg, what, where, args.mode, keep, args.cache_limit, args.wait, ctx.note)
    if args.what or args.where or args.persist:  # the last explicit mount becomes the profile's default
        config.update(mount={"what": state["what"], "where": state["where"], "persist": bool(state.get("persist"))})
    row = {**{k: state.get(k) for k in ("id", "profile", "mode", "what", "where", "persist")}, "state": status}
    ctx.write([row], FIELDS, receipt=True)
    if mounts.gdocs_note(state["mode"]):
        ctx.note(mounts.gdocs_note(state["mode"]))
    if status in ("starting", "syncing"):
        raise Deadline(f"not ready after {args.wait:g} s - NOTHING WAS UNDONE, it continues in the background; "
                       f"check `gdrive status`, or wait: `gdrive sync {state['where']}`")
