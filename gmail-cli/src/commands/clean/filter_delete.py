"""filter delete: remove Gmail filters by id (mail already filtered stays as it is)."""
from ...api import filters

WRITE = True
FIELDS = ["profile", "id", "criteria", "actions"]
EPILOG = """examples:
  gmail filter list --profile work
  gmail filter delete --profile work ANe1Bmj...

Ids come from `gmail filter list` and are per account (--profile). Labels the filter set stay on
the mail. Needs the Gmail settings permission (see `gmail filter create -h`).
"""


def add_args(p):
    p.add_argument("ids", nargs="+", metavar="FILTER_ID")


def run(ctx, args):
    prof = ctx.profile
    filters.need_settings(prof)
    names = filters.mail.label_names(prof)
    rows = [filters.row(prof, filters.delete(prof, i), names) for i in dict.fromkeys(args.ids)]
    ctx.write(rows, FIELDS)
