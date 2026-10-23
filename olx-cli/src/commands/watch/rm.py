"""watch rm: delete saved searches and their seen state."""
from ...api import watch

FIELDS = ["name", "removed"]
EPILOG = """examples:
  olx watch rm sofa
  olx watch rm a b c
"""


def add_args(p):
    p.add_argument("names", nargs="+", metavar="NAME")


def run(ctx, args):
    watch.remove(args.names)
    ctx.write([{"name": n, "removed": True} for n in args.names], FIELDS)
