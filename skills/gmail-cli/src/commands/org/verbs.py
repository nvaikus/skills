"""archive, unarchive, mark-read, mark-unread, star, unstar, trash, untrash: one module, the verb
is args.command."""
from ...api import targets

PROFILE = "locate"
WRITE = True
FIELDS = targets.FIELDS
VERBS = {"archive": ((), ("INBOX",)), "unarchive": (("INBOX",), ()),
         "mark-read": ((), ("UNREAD",)), "mark-unread": (("UNREAD",), ()),
         "star": (("STARRED",), ()), "unstar": ((), ("STARRED",))}
EPILOG = """examples:
  gmail archive 18f2a9c0d1e2f3a4 18f2a9c0d1e2f3b7
  gmail mark-read -q 'in:inbox category:promotions'
  gmail archive -q 'in:inbox older_than:30d' --dry-run
  gmail trash --threads 18f2a9c0d1e2f3a4

Acts on the given messages; --threads widens to their whole conversations (Gmail's web UI acts on
conversations). trash = Trash folder, Gmail deletes it for good after 30 days; untrash restores.
Receipt: profile, action, matched, changed.
"""


def add_args(p):
    targets.add_args(p)


def run(ctx, args):
    verb = args.command
    if verb in VERBS:
        add, remove = VERBS[verb]
        return targets.change(ctx, args, verb, add, remove)
    targets.change(ctx, args, verb, trash=verb == "trash")
