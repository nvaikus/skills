"""Command rail: a destructive step shows what it would lose and refuses (exit 3) without --force."""
from .errors import Refused


def confirm(ctx, rows, fields, force, why):
    """rows = the loss preview (stdout, so it can be piped); nothing happens without --force."""
    if force or not rows:
        return
    ctx.write(rows, fields)
    raise Refused(f"{why} - nothing was changed; rerun with --force to proceed anyway")
