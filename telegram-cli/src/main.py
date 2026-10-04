"""argv dispatch, global flags, exit codes, stream setup. Knows no domain noun."""
import argparse
import difflib
import importlib
import os
import sys
import traceback

from . import VERSION, registry
from .context import Context
from .core import config, tg
from .core.errors import CliError, UsageError
from .core.output import Writer

EXITS = ("exit: 0 ok · 1 Telegram/runtime failure · 2 usage, config, not logged in, target not found or ambiguous"
         " · 3 refused, nothing sent · 4 needs Telegram Premium · 130 interrupt")
GLOBALS = ("global: --account NAME (before or after the command; default: config default_account)"
           " · -j/--json · --fields A,B · --no-header")


def top_help():
    lines = ["usage: tg-cli [--account NAME] <command> [args]      tg-cli <command> -h",
             "",
             "Telegram CLI over your own user account (MTProto via Telethon). Output: TSV; -j for JSON.",
             "Data on stdout, notes on stderr as '# ...'.",
             "",
             "First run (a person, in a real terminal - not through an agent):",
             "  1. tg-cli deps     2. tg-cli keys (from my.telegram.org)     3. tg-cli login (QR)"]
    width = max(map(len, registry.COMMANDS))
    for key, heading in registry.AREAS.items():
        lines += ["", f"{heading}:"]
        lines += [f"  {n:<{width}}  {h}" for n, (_, h) in registry.COMMANDS.items() if registry.area(n) == key]
    return "\n".join(lines + ["", GLOBALS, EXITS])


def _streams():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", newline="\n")  # Windows CRLF would corrupt piped TSV
        except (AttributeError, ValueError):
            pass


def _split_globals(argv):
    """Leading global options -> (account, trace, rest)."""
    account, trace, i = None, False, 0
    while i < len(argv) and argv[i].startswith("-"):
        a = argv[i]
        if a == "--account":
            if i + 1 >= len(argv):
                raise UsageError("--account needs a NAME")
            account, i = argv[i + 1], i + 2
        elif a.startswith("--account="):
            account, i = a.split("=", 1)[1], i + 1
        elif a == "--trace":
            trace, i = True, i + 1
        else:
            break
    return account, trace, argv[i:]


def _parser(name, mod, account):
    module, help_ = registry.COMMANDS[name]
    p = argparse.ArgumentParser(prog=f"tg-cli {name}", description=help_, epilog=getattr(mod, "EPILOG", None),
                                formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    mod.add_args(p)
    g = p.add_argument_group("global")
    g.add_argument("--account", default=account, metavar="NAME", help="session to use (default: config default_account)")
    g.add_argument("-j", "--json", action="store_true", help="JSON instead of TSV")
    g.add_argument("--fields", metavar="A,B", help="columns to output, TSV and JSON alike")
    g.add_argument("--no-header", action="store_true", help="TSV without the header row")
    g.add_argument("--trace", action="store_true", help=argparse.SUPPRESS)
    return p


def _fail(err, trace):
    sys.stderr.write(f"tg-cli: {err}\n")
    for row in err.payload or []:
        sys.stderr.write("#   " + "\t".join("" if v is None else str(v) for v in row.values()) + "\n")
    return err.code


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _streams()
    ctx, trace = None, "--trace" in argv
    try:
        account, trace, rest = _split_globals(argv)
        if not rest or rest[0] in ("-h", "--help", "help"):
            print(top_help())
            return 0 if rest else 2
        if rest[0] == "--version":
            print(VERSION)
            return 0
        name, rest = rest[0], rest[1:]
        if name not in registry.COMMANDS:
            close = difflib.get_close_matches(name, registry.COMMANDS, n=3)
            hint = f"; did you mean: {', '.join(close)}" if close else "; see tg-cli --help"
            raise UsageError(f"unknown command {name!r}{hint}")
        mod = importlib.import_module(registry.COMMANDS[name][0])
        args = _parser(name, mod, account).parse_args(rest)
        trace = trace or args.trace
        ctx = Context(args, Writer(args.json, args.fields, not args.no_header), config.load())
        rc = mod.run(ctx, args) or 0
        sys.stdout.flush()  # inside the try: on big output only the flush hits the closed pipe
        return rc
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        sys.stderr.write("tg-cli: interrupted\n")
        return 130
    except CliError as e:
        return _fail(e, trace)
    except Exception as e:  # noqa: BLE001
        known = tg.translate(e)
        if known:
            return _fail(known, trace)
        if trace:
            traceback.print_exc()
        tb = traceback.extract_tb(e.__traceback__)[-1]
        sys.stderr.write(f"tg-cli: internal error: {type(e).__name__}: {e} at {os.path.basename(tb.filename)}:"
                         f"{tb.lineno} - bug in tg-cli, rerun with --trace\n")
        return 1
    finally:
        if ctx:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001  (disconnect noise must not mask the real exit code)
                pass
