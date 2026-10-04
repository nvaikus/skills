"""share: who has access to a Drive item; grant or revoke one person's access."""
from ...api import address, drive
from ...core.errors import UsageError

FIELDS = ["who", "type", "role", "inherited", "id"]
WRITE = True  # --user / --remove only
EPILOG = """examples:
  gdrive share /Projects                               # list access: who, type, role, inherited
  gdrive share /Projects --user ann@x.com              # CHANGES SHARING: Ann can view (no email sent)
  gdrive share /Projects --user ann@x.com --role writer --notify
  gdrive share /Projects --remove ann@x.com            # revoke Ann's direct access

Without --user/--remove nothing changes. Share only when the user asked for that person.
inherited=yes: the access comes from a parent folder - it is lost when the item moves out of
that folder, and --remove on the child refuses: remove it on the folder that grants it.
--user on someone who already has access changes their role.
"""


def add_args(p):
    p.add_argument("path", help="Drive path, name@id, URL, or a local path inside a mount")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--user", metavar="EMAIL", help="grant this person access")
    g.add_argument("--remove", metavar="EMAIL", help="revoke this person's direct access")
    p.add_argument("--role", choices=["reader", "commenter", "writer"], default="reader",
                   help="with --user (default reader)")
    p.add_argument("--notify", action="store_true", help="with --user: Drive emails the person (off by default)")


def _row(p):
    return {"who": drive.perm_who(p), "type": p.get("type"), "role": p.get("role"),
            "inherited": "yes" if p.get("inherited") else "no", "id": p.get("id")}


def run(ctx, args):
    if (args.role != "reader" or args.notify) and not args.user:
        raise UsageError("--role/--notify go with --user EMAIL")
    f = drive.resolve(ctx.remote, address.of(args.path))
    if args.user:
        drive.share_user(ctx.remote, f, args.user, args.role, args.notify)
    elif args.remove:
        email = args.remove.lower()
        mine = [p for p in drive.permissions(ctx.remote, f) if (p.get("emailAddress") or "").lower() == email]
        if not mine:
            raise UsageError(f"{args.remove} has no access to {f.get('name')} (list it: gdrive share PATH)")
        direct = [p for p in mine if not p.get("inherited")]
        if not direct:
            raise UsageError(f"{args.remove}'s access to {f.get('name')} is inherited from a parent folder: "
                             "remove it there")
        for p in direct:
            drive.unshare(ctx.remote, f, p["id"])
    ctx.write([_row(p) for p in drive.permissions(ctx.remote, f)], FIELDS)
