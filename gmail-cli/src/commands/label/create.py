"""label create: a new label; Parent/Child creates missing parents."""
from ...api import mail

WRITE = True
FIELDS = ["name", "id"]
EPILOG = """examples:
  gmail label create Clients/Acme       # creates Clients too when missing
  gmail label create Receipts && gmail modify -q 'subject:receipt' --add Receipts
Existing labels are left alone (no error); the output lists only what was created.
"""


def add_args(p):
    p.add_argument("name", metavar="NAME")


def run(ctx, args):
    made = mail.create_label(ctx.profile, args.name)
    if not made:
        ctx.note(f"label {args.name!r} already exists")
    ctx.write([{"name": m["name"], "id": m["id"]} for m in made], FIELDS)
