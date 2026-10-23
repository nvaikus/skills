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

EXITS = ("exit: 0 ok · 1 Vinted/network/runtime failure · 2 usage, unknown name, listing not found"
         " · 3 Vinted broke: blocked (Cloudflare / 403) or the page data changed · 130 interrupt")
GLOBALS = "global: -j/--json · --fields A,B · --no-header (on every command)"


def top_help():
    lines = ["usage: vinted <command> [args]        vinted <command> -h",
             "",
             "Buyer-side Vinted search (vinted.pt by default; --site fr es de it pl lt nl be co.uk ...) through",
             "Vinted's own web pages (unofficial): listings, item cards, category / brand / size / condition / color",
             "ids, saved searches that report only new listings and price drops. Output: TSV (-j JSON); data on",
             "stdout, notes on stderr as '# ...'. Read-only: never sells, messages sellers or buys."]
    width = max(map(len, registry.COMMANDS))
    for key, heading in registry.AREAS.items():
        lines += ["", f"{heading}:"]
        lines += [f"  {n:<{width}}  {h}" for n, (_, h) in registry.COMMANDS.items() if registry.area(n) == key]
    return "\n".join(lines + ["", GLOBALS, EXITS])


def family_help(fam):
    cmds = [(n, h) for n, (_, h) in registry.COMMANDS.items() if n.split()[0] == fam]
    width = max(len(n) for n, _ in cmds)
    return "\n".join([f"usage: vinted {fam} <verb> [args]     vinted {fam} <verb> -h", ""]
                     + [f"  {n:<{width}}  {h}" for n, h in cmds])


def _streams():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", newline="\n")  # Windows CRLF would corrupt piped TSV
        except (AttributeError, ValueError):
            pass


def _parser(name, mod):
    p = argparse.ArgumentParser(prog=f"vinted {name}", description=registry.COMMANDS[name][1],
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
    sys.stderr.write(f"vinted: {err}\n")
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
        hint = f"; did you mean: {', '.join(close)}" if close else "; see vinted --help"
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
        sys.stderr.write("vinted: interrupted\n")
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
        sys.stderr.write(f"vinted: internal error: {type(e).__name__}: {e} at {os.path.basename(tb.filename)}:"
                         f"{tb.lineno} - bug in vinted, rerun with --trace\n")
        return 1
