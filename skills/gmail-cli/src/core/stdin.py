"""Text arguments that may come from stdin ('-')."""
import sys

from .errors import UsageError


def text_arg(value, what="text"):
    if value != "-":
        return value
    if sys.stdin.isatty():
        raise UsageError(f"{what} is '-' but nothing is piped in")
    return sys.stdin.read()


def piped(what):
    if sys.stdin.isatty():
        raise UsageError(f"pipe {what} in on stdin")
    return sys.stdin.read()
