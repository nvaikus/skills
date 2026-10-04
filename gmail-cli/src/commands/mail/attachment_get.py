"""attachment get: download attachments of a message by number or file name."""
from pathlib import Path

from ...api import mail, render
from ...core import paths, profile
from ...core.errors import UsageError

PROFILE = "locate"
WRITE = True
FIELDS = ["n", "name", "size", "path"]
EPILOG = """examples:
  gmail attachment get 18f2a9c0d1e2f3a4 1                  # -> <tmp>/gmail/<name>, path printed
  gmail attachment get 18f2a9c0d1e2f3a4 invoice.pdf -o ~/Documents/
  gmail attachment get 18f2a9c0d1e2f3a4 all -o ./in/       # every non-inline attachment

WHICH: numbers from `gmail read` / `attachment list`, a file name, or all. -o: a directory (ends
with / or exists) or a file path (one attachment). Default dir: the system temp dir + /gmail.
An existing file is overwritten.
"""


def add_args(p):
    p.add_argument("id", metavar="MESSAGE_ID")
    p.add_argument("which", nargs="+", metavar="WHICH", help="attachment number, file name, or all")
    p.add_argument("-o", "--out", metavar="PATH", help="target directory or file (default: <tmp>/gmail/)")


def pick(atts, which):
    if which == ["all"]:
        return [a for a in atts if not a["inline"]] or atts
    out = []
    for w in which:
        hit = [a for a in atts if (w.isdigit() and a["n"] == int(w)) or a["name"] == w] \
            or [a for a in atts if a["name"].lower() == w.lower()]
        if not hit:
            listing = "; ".join(f"{a['n']}. {a['name']}" for a in atts) or "none"
            raise UsageError(f"no attachment {w!r} in this message (has: {listing})")
        out.append(hit[0])
    return out


def run(ctx, args):
    prof = ctx.profile if profile.explicit() else mail.locate(args.id, ctx.profiles)
    atts = render.attachments(mail.message(prof, args.id).get("payload"))
    chosen = pick(atts, args.which)
    out = Path(args.out).expanduser() if args.out else paths.downloads()
    as_dir = not args.out or args.out.endswith(("/", "\\")) or out.is_dir() or len(chosen) > 1
    if as_dir:
        out.mkdir(parents=True, exist_ok=True)
    rows = []
    for a in chosen:
        data = mail.attachment_data(prof, args.id, a["part"])
        target = out / Path(a["name"]).name if as_dir else out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rows.append({"n": a["n"], "name": a["name"], "size": len(data), "path": str(target)})
    ctx.write(rows, FIELDS)
