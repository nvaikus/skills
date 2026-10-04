"""link: the web link of a Drive item; --public makes it viewable by anyone with the link."""
from ...api import address, drive

FIELDS = ["name", "kind", "url", "public"]
WRITE = True  # --public only
EPILOG = """examples:
  gdrive link /Projects/Plan                   # link for people who already have access
  gdrive link ~/gdrive/Projects/report.pdf     # a path inside a mount works too
  gdrive link /Projects/report.pdf --public    # CHANGES SHARING: anyone with the link can view

Without --public nothing changes on Drive. --public adds an "anyone with the link: viewer"
permission (same as `rclone link`) and it stays until removed in Drive's Share dialog - use it only when
the user asked to share with people outside.
"""


def add_args(p):
    p.add_argument("path", help="Drive path, name@id, URL, or a local path inside a mount")
    p.add_argument("--public", action="store_true", help="create an anyone-with-link viewer share")


def run(ctx, args):
    addr = address.of(args.path)
    f = drive.resolve(ctx.remote, addr)
    url = f.get("webViewLink")
    if args.public:
        url = drive.share_public(ctx.remote, f)
    ctx.write([{"name": f.get("name"), "kind": drive.kind(f), "url": url, "public": args.public}], FIELDS)
