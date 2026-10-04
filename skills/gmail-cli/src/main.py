"""argv dispatch, global flags, exit codes, stream setup. Knows no domain noun."""
import argparse
import difflib
import importlib
import os
import sys
import traceback

from . import VERSION, registry
from .context import Context
from .core import config, profile
from .core.errors import CliError, UsageError
from .core.output import Writer

EXITS = ("exit: 0 ok · 1 Google/runtime failure · 2 usage, config, not logged in, id/label not found"
         " · 5 onboard waits on the user (relay the step, rerun) · 6 still in progress, nothing undone (rerun)"
         " · 130 interrupt")
GLOBALS = ("global: --profile NAME (before or after the command) · -j/--json · --fields A,B · --no-header\n"
           "profiles: search = every profile unless --profile; an ID finds its own profile; anything else ="
           " the default profile (`gmail profiles`)")


def top_help():
    lines = ["usage: gmail [--profile NAME] <command> [args]        gmail <command> -h",
             "",
             "Gmail for agents: search (Gmail query syntax, all accounts at once), read threads as compact",
             "markdown, labels and bulk organizing, drafts and send. New account: `gmail onboard --profile NAME`.",
             "Output: TSV; -j for JSON. Data on stdout, notes on stderr as '# ...'.",
             "ID: a message or thread id from `gmail search` (id / thread_id columns)."]
    width = max(map(len, registry.COMMANDS))
    for key, heading in registry.AREAS.items():
        lines += ["", f"{heading}:"]
        lines += [f"  {n:<{width}}  {h}" for n, (_, h) in registry.COMMANDS.items() if registry.area(n) == key]
    return "\n".join(lines + ["", GLOBALS, EXITS])


def family_help(fam):
    cmds = [(n, h) for n, (_, h) in registry.COMMANDS.items() if n.split()[0] == fam]
    width = max(len(n) for n, _ in cmds)
    return "\n".join([f"usage: gmail {fam} <verb> [args]     gmail {fam} <verb> -h", ""]
                     + [f"  {n:<{width}}  {h}" for n, h in cmds])


def _streams():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", newline="\n")  # Windows CRLF would corrupt piped TSV
        except (AttributeError, ValueError):
            pass


def _split_globals(argv):
    """Leading global options -> (profile, rest). --profile after the command is parsed by argparse."""
    prof, i = None, 0
    while i < len(argv) and argv[i].startswith("--profile"):
        a = argv[i]
        if a == "--profile":
            if i + 1 >= len(argv):
                raise UsageError("--profile needs a NAME")
            prof, i = argv[i + 1], i + 2
        else:
            prof, i = a.split("=", 1)[1], i + 1
    return prof, argv[i:]


def _parser(name, mod, prof):
    p = argparse.ArgumentParser(prog=f"gmail {name}", description=registry.COMMANDS[name][1],
                                epilog=getattr(mod, "EPILOG", None),
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                allow_abbrev=False)  # a prefix silently binding to another flag is a wrong run
    mod.add_args(p)
    g = p.add_argument_group("global")
    g.add_argument("--profile", default=prof, metavar="NAME", help="Gmail account profile (see `gmail profiles`)")
    g.add_argument("-j", "--json", action="store_true", help="JSON instead of TSV")
    g.add_argument("--fields", metavar="A,B", help="columns to output, TSV and JSON alike")
    g.add_argument("--no-header", action="store_true", help="TSV without the header row")
    g.add_argument("--trace", action="store_true", help=argparse.SUPPRESS)
    return p


def _fail(err):
    sys.stderr.write(f"gmail: {err}\n")
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
        names = list(registry.COMMANDS) + list(registry.FAMILIES)
        close = difflib.get_close_matches(rest[0], names, n=3)
        hint = f"; did you mean: {', '.join(close)}" if close else "; see gmail --help"
        raise UsageError(f"unknown command {rest[0]!r}{hint}")
    return rest[0], rest[1:]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _streams()
    trace = "--trace" in argv
    rest = [a for a in argv if a != "--trace"]
    try:
        prof, rest = _split_globals(rest)
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
        args = _parser(name, mod, prof).parse_args(rest)
        args.command = name
        profile.resolve(args.profile, getattr(mod, "PROFILE", "required"))
        ctx = Context(args, Writer(args.json, args.fields, not args.no_header), config.load())
        rc = mod.run(ctx, args) or 0
        sys.stdout.flush()  # inside the try: on big output only the flush hits the closed pipe
        return rc
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        sys.stderr.write("gmail: interrupted\n")
        return 130
    except CliError as e:
        try:
            sys.stdout.flush()  # a receipt printed before the failure (exit 6) must reach the caller
        except BrokenPipeError:
            pass
        return _fail(e)
    except Exception as e:  # noqa: BLE001
        if trace:
            traceback.print_exc()
        tb = traceback.extract_tb(e.__traceback__)[-1]
        sys.stderr.write(f"gmail: internal error: {type(e).__name__}: {e} at {os.path.basename(tb.filename)}:"
                         f"{tb.lineno} - bug in gmail, rerun with --trace\n")
        return 1
