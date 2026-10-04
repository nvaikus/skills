"""label delete: remove a label; its messages stay where they are."""
from ...api import mail

WRITE = True
FIELDS = ["name", "id"]
EPILOG = """examples:
  gmail label delete Old/Stuff
Messages are not deleted, they only lose this label. Nested labels (Old/Stuff/x) stay; delete them
separately. System labels cannot be deleted.
"""


def add_args(p):
    p.add_argument("name", metavar="NAME")


def run(ctx, args):
    lb = mail.delete_label(ctx.profile, args.name)
    ctx.write([{"name": lb["name"], "id": lb["id"]}], FIELDS, receipt=True)
