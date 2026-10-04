"""What an organize command acts on: message ids (each finds its profile) or every match of -q."""
from ..core import profile
from ..core.errors import UsageError
from . import mail


def add_args(p):
    p.add_argument("ids", nargs="*", metavar="ID", help="message ids (or thread ids) from `gmail search`")
    p.add_argument("-q", "--query", metavar="QUERY", help="act on every message this Gmail query matches instead of IDs")
    p.add_argument("--threads", action="store_true", help="act on whole conversations, not just the given messages")
    p.add_argument("--limit", type=int, metavar="N", help="with -q: at most N newest matches")
    p.add_argument("--dry-run", action="store_true", help="count what would change, change nothing")


def resolve(ctx, args):
    """-> {profile: [message ids]}. IDs: each located (default profile first). -q: one profile
    (--profile or the default), every match."""
    if bool(args.ids) == bool(args.query):
        raise UsageError("give message IDs or -q QUERY (one of them)")
    if args.query is not None:
        prof = ctx.profile
        if not prof:
            raise UsageError("-q needs one profile: pass --profile NAME (or set `gmail profiles --default NAME`)")
        if not profile.explicit() and len(ctx.profiles) > 1:
            ctx.note(f"profile {prof} (default); --profile NAME for another account")
        ids = mail.list_ids(prof, args.query, args.limit, threads=args.threads)
        if args.threads:
            ids = mail.thread_messages(prof, ids)
        return {prof: ids}
    out = {}
    for i in dict.fromkeys(args.ids):
        prof = ctx.profile if profile.explicit() else mail.locate(i, ctx.profiles)
        out.setdefault(prof, []).append(i)
    for prof, ids in out.items():
        out[prof] = mail.thread_messages(prof, ids) if args.threads else _messages(prof, ids)
    return out


def _messages(prof, ids):
    """A thread id given without --threads stands for its messages; message ids pass through."""
    out = []
    for i in ids:
        try:
            mail.message(prof, i, "minimal")
            out.append(i)
        except UsageError as e:
            if e.status not in (400, 404):
                raise
            out += [m["id"] for m in mail.thread_of(prof, i, "minimal").get("messages", [])]
    return list(dict.fromkeys(out))


FIELDS = ["profile", "action", "matched", "changed"]


def change(ctx, args, action, add=(), remove=(), trash=None):
    """Resolve targets, apply labels (or trash/untrash when trash is True/False), write the receipt."""
    rows = []
    for prof, ids in resolve(ctx, args).items():
        if trash is not None:
            n = 0 if args.dry_run or not ids else mail.trash(prof, ids, undo=not trash)
        else:
            add_ids = [mail.find_label(prof, x)["id"] for x in add]
            rem_ids = [mail.find_label(prof, x)["id"] for x in remove]
            n = 0 if args.dry_run or not ids else mail.batch_modify(prof, ids, add_ids, rem_ids)
        rows.append({"profile": prof, "action": action, "matched": len(ids), "changed": n})
    if args.dry_run:
        ctx.note("dry run: nothing changed")
    ctx.write(rows, FIELDS)
