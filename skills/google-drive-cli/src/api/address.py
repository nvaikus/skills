"""A command's PATH argument: a local path inside a mount/sync folder maps to the Drive path it
mirrors (and to the profile that owns that mount); anything else is a Drive address (see
api/drive.py for the grammar)."""
from ..core import profile
from . import mounts


def of(text):
    addr, prof = mounts.to_drive_profile(text)
    if not addr:
        return text
    if prof:
        profile.switch(prof)  # the mount's own account; exit 2 when --profile names another
    return addr
