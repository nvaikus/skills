"""label list: every label of one profile."""
from ...api import mail

FIELDS = ["name", "id", "type"]
EPILOG = """examples:
  gmail label list                      # user labels, then system ones
  gmail label list --counts             # + messages, unread, threads (one call per label)
  gmail label list --user --fields name
Search a label: gmail search 'label:Parent/Child' (spaces: label:"My Label" or label:my-label).
"""


def add_args(p):
    p.add_argument("--counts", action="store_true", help="add messages / unread / threads totals")
    p.add_argument("--user", action="store_true", help="only your own labels")


def run(ctx, args):
    prof = ctx.profile
    labs = [lb for lb in mail.labels(prof) if not args.user or lb.get("type") != "system"]
    labs.sort(key=lambda lb: (lb.get("type") == "system", lb["name"].lower()))
    rows = [{"name": mail.show_label(lb["id"], {lb["id"]: lb["name"]}) if lb.get("type") == "system" else lb["name"],
             "id": lb["id"], "type": lb.get("type", "user")} for lb in labs]
    fields = FIELDS
    if args.counts:
        full = mail.label_details(prof, labs)
        for r, f in zip(rows, full):
            r.update(messages=f.get("messagesTotal", 0), unread=f.get("messagesUnread", 0),
                     threads=f.get("threadsTotal", 0))
        fields = FIELDS + ["messages", "unread", "threads"]
    ctx.write(rows, fields)
