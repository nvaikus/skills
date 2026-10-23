"""photos: download a listing's photos, one TSV row per file."""
from ...api import offers, photos, query
from ...core.errors import UsageError

FIELDS = ["n", "path", "bytes"]
EPILOG = """examples:
  olx photos 674668916                        # -> ./olx-674668916/674668916-01.jpg ...
  olx photos "https://www.olx.pt/d/anuncio/...-IDJEQcI.html" -o /tmp/bike --max 4
  olx photos 674668916 --sheet                # + 674668916-sheet.jpg: all photos in one grid (needs ffmpeg)

Photos come at their original size (OLX's own width x height). Files are named <id>-NN.jpg and
overwritten on rerun. -j adds url. Listing without photos -> nothing written, a note.
"""


def add_args(p):
    p.add_argument("ref", metavar="ID|URL", help="numeric listing id or an OLX listing URL")
    p.add_argument("-o", "--out", metavar="DIR", help="target dir (default ./olx-<id>)")
    p.add_argument("--max", type=int, metavar="N", help="first N photos only")
    p.add_argument("--sheet", action="store_true", help="also one contact-sheet JPEG (4 per row; needs ffmpeg)")
    query.add_site_arg(p)


def run(ctx, args):
    if args.max is not None and args.max < 1:
        raise UsageError("--max must be >= 1")
    o, _ = offers.lookup(args.ref, query.site(query.flags_of(args), ctx.cfg))
    out = args.out or f"olx-{o['id']}"
    rows = photos.download(o, out, args.max)
    if not rows:
        ctx.note(f"listing {o['id']} has no photos")
    elif args.sheet:
        rows.append(photos.sheet(o, rows, out))
    ctx.write(rows, FIELDS)
