"""ls: a Drive folder's children by path, straight from the API (no mount needed)."""
from ...api import address, drive

FIELDS = ["name", "kind", "size", "modified", "id"]
EPILOG = """examples:
  gdrive ls /Projects
  gdrive ls "shared:Team Drive/Specs" --fields name,kind
  gdrive ls /Projects/Plan.docx -j        # one item: a file prints itself
  gdrive ls shared-with-me:               # what others shared with this account (flat list)
  gdrive ls "shared-with-me:/Brief 2026"  # inside a shared folder

kind: folder · doc · sheet · slides · file · shortcut · form. Duplicate names are normal on
Drive: address one as name@id (the id column) in every other command.
"""


def add_args(p):
    p.add_argument("path", nargs="?", default="/", help="Drive path (default: My Drive root)")
    p.add_argument("-n", "--limit", type=int, default=1000, help="max items (default 1000)")


def run(ctx, args):
    f = drive.resolve(ctx.remote, address.of(args.path))
    if f.get("mimeType") != drive.FOLDER:
        return ctx.write([drive.row(f)], FIELDS)
    items = drive.children(ctx.remote, f, limit=args.limit + 1)
    if len(items) > args.limit:
        ctx.note(f"showing the first {args.limit} items; raise --limit for more")
    ctx.write([drive.row(x) for x in items[: args.limit]], FIELDS)
