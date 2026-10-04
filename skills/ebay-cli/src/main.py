"""argv dispatch, global flags, exit codes, stream setup. Knows no domain noun."""
import argparse
import difflib
import importlib
import os
import sys
import traceback

from . import VERSION, registry
from .context import Context
from .core import config
from .core.errors import CliError, UsageError
from .core.output import Writer

EXITS = ("exit: 0 ok · 1 eBay/runtime failure (incl. rate limit) · 2 usage, config, no keys, item not found"
         " · 5 setup waits on the user (relay the step, rerun) · 130 interrupt")
GLOBALS = "global: -j/--json · --fields A,B · --no-header (on every command)"


def top_help():
    lines = ["usage: ebay <command> [args]        ebay <command> -h",
             "",
             "Buyer-side eBay search via the official Browse API: listings with shipping priced for your",
             "country, item cards, category ids, saved searches that report only new items and price drops.",
             "First run: `ebay setup`. Output: TSV (-j JSON); data on stdout, notes on stderr as '# ...'.",
             "No bidding/buying, no sold-price history, no seller tools (eBay keeps those APIs partner-only)."]
    width = max(map(len, registry.COMMANDS))
    for key, heading in registry.AREAS.items():
        lines += ["", f"{heading}:"]
        lines += [f"  {n:<{width}}  {h}" for n, (_, h) in registry.COMMANDS.items() if registry.area(n) == key]
    return "\n".join(lines + ["", GLOBALS, EXITS])


def family_help(fam):
    cmds = [(n, h) for n, (_, h) in registry.COMMANDS.items() if n.split()[0] == fam]
    width = max(len(n) for n, _ in cmds)
    return "\n".join([f"usage: ebay {fam} <verb> [args]     ebay {fam} <verb> -h", ""]
                     + [f"  {n:<{width}}  {h}" for n, h in cmds])


def _streams():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", newline="\n")  # Windows CRLF would corrupt piped TSV
        except (AttributeError, ValueError):
            pass


def _parser(name, mod):
    p = argparse.ArgumentParser(prog=f"ebay {name}", description=registry.COMMANDS[name][1],
                                epilog=getattr(mod, "EPILOG", None),
                                formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    mod.add_args(p)
    g = p.add_argument_group("global")
    g.add_argument("-j", "--json", action="store_true", help="JSON instead of TSV (more fields)")
    g.add_argument("--fields", metavar="A,B", help="columns to output, TSV and JSON alike")
    g.add_argument("--no-header", action="store_true", help="TSV without the header row")
    g.add_argument("--trace", action="store_true", help=argparse.SUPPRESS)
    return p


def _fail(err):
    sys.stderr.write(f"ebay: {err}\n")
    for row in err.payload or []:
        sys.stderr.write("#   " + "\t".join("" if v is None else str(v) for v in row.values()) + "\n")
    return err.code


def _resolve(rest):
    if rest[0] in registry.FAMILIES:
        if len(rest) < 2 or rest[1] in ("-h", "--help", "help"):
            return None, rest
        name = f"{rest[0]} {rest[1]}"
        if name not in registry.COMMANDS:
            verbs = [n.split()[1] for n in registry.COMMANDS if n.split()[0] == rest[0]]
            close = difflib.get_close_matches(rest[1], verbs, n=3)
            hint = f"; did you mean: {', '.join(close)}" if close else f"; verbs: {', '.join(verbs)}"
            raise UsageError(f"unknown command '{name}'{hint}")
        return name, rest[2:]
    if rest[0] not in registry.COMMANDS:
        close = difflib.get_close_matches(rest[0], list(registry.COMMANDS) + list(registry.FAMILIES), n=3)
        hint = f"; did you mean: {', '.join(close)}" if close else "; see ebay --help"
        raise UsageError(f"unknown command {rest[0]!r}{hint}")
    return rest[0], rest[1:]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _streams()
    trace = "--trace" in argv
    rest = [a for a in argv if a != "--trace"]
    try:
        if not rest or rest[0] in ("-h", "--help", "help"):
            print(top_help())
            return 0 if rest else 2
        if rest[0] == "--version":
            print(VERSION)
            return 0
        name, rest = _resolve(rest)
        if name is None:
            print(family_help(rest[0]))
            return 0 if len(rest) > 1 else 2
        mod = importlib.import_module(registry.COMMANDS[name][0])
        args = _parser(name, mod).parse_args(rest)
        args.command = name
        ctx = Context(args, Writer(args.json, args.fields, not args.no_header), config.load())
        rc = mod.run(ctx, args) or 0
        sys.stdout.flush()
        return rc
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        sys.stderr.write("ebay: interrupted\n")
        return 130
    except CliError as e:
        try:
            sys.stdout.flush()  # rows printed before the failure (watch run) must reach the caller
        except BrokenPipeError:
            pass
        return _fail(e)
    except Exception as e:  # noqa: BLE001
        if trace:
            traceback.print_exc()
        tb = traceback.extract_tb(e.__traceback__)[-1]
        sys.stderr.write(f"ebay: internal error: {type(e).__name__}: {e} at {os.path.basename(tb.filename)}:"
                         f"{tb.lineno} - bug in ebay, rerun with --trace\n")
        return 1
