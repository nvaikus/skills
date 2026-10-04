"""onboard: guided, resumable setup of one profile (Gmail account). Prints ONLY the next step."""
from ...api import onboarding
from ...core import config, profile
from ...core.errors import CliError, Deadline

PROFILE = "create"
WRITE = True
EXIT_WAITING = 5
EPILOG = """examples:
  gmail onboard --profile work                   # start, or show where it stands
  gmail onboard --profile work --done apis       # the user switched the Gmail API on
  printf '%s' '<address the user pasted>' | gmail --profile work login --finish && gmail --profile work onboard
  gmail onboard --profile work --client-from gdrive:personal   # pick another reusable key
  gmail onboard --profile work --client-file ~/Downloads/client_secret_123.json

Driving it (agent): run, relay the text under "say to the user" WORD FOR WORD, get the answer,
run the command under "then run" with it, repeat until DONE. "then run (right away ...)": run it
at once (exit 6 = Google still switching the API on; wait ~1 min first). Every run re-checks live.
Exit 5 = waiting on the user; 0 = done.
Key (OAuth client): reused automatically from another gmail profile, else a gdrive profile (same
name first) - one key serves every account. None here: console steps (project, Gmail API,
consent screen, branding, publish, key file) like gdrive's; --new-client forces them.
The first finished profile becomes the default one. --relogin: login step for a working profile
(filters need a permission older logins lack; the old login keeps working until the new one lands).
"""


def add_args(p):
    p.add_argument("--done", action="append", choices=onboarding.DONE_STEPS, metavar="STEP",
                   help="the user finished a console step: apis | consent | branding | publish")
    p.add_argument("--project", metavar="ID", help="Google Cloud Project ID the user created (new key only)")
    p.add_argument("--account", metavar="EMAIL", help="the user's Gmail address, if known: tunes the texts")
    p.add_argument("--audience", choices=("internal", "external"), help="what the user chose on the consent screen")
    p.add_argument("--keep-testing", action="store_true", help="do not publish: login renewed every 7 days")
    p.add_argument("--client-from", metavar="SRC", help="reuse the key of gdrive:NAME or gmail:NAME (bare NAME = gdrive)")
    p.add_argument("--client-file", metavar="PATH", help="the downloaded Desktop-app client JSON")
    p.add_argument("--new-client", action="store_true", help="do not reuse a key: create a new one (console steps)")
    p.add_argument("--relogin", action="store_true",
                   help="log a working profile in again (adds permissions requested later, e.g. filters)")


def _text(r, prof):
    head = (f"DONE profile {prof}" if r["status"] == "done" else
            f"WAITING {r['id']} (profile {prof})" if r["status"] == "waiting" else f"RUNNING {r['id']} (profile {prof})")
    out = [head, "--- say to the user ---", r["say"]]
    if r.get("next"):
        out += ["--- then run (right away, no answer needed) ---" if r.get("now") else "--- then run ---", r["next"]]
    return "\n".join(out) + "\n"


def run(ctx, args):
    prof = profile.active()
    cfg = config.update(prof) if prof not in profile.names() else config.load(prof)
    answers = {k: getattr(args, k) for k in ("done", "project", "account", "audience", "keep_testing",
                                              "client_from", "client_file", "new_client")}
    cfg = onboarding.apply(cfg, answers, prof, ctx.note)
    r = onboarding.advance(onboarding.LiveEnv(prof), cfg, prof, ctx.note, relogin=args.relogin)
    ctx.text(_text(r, prof), {**r, "profile": prof})
    if r["status"] == "waiting":
        raise CliError(f"onboarding waits on the user ({r['id']}): relay the text, then run the command under "
                       "'then run'", code=EXIT_WAITING)
    if r["status"] == "running":
        raise Deadline(f"Google is still switching the Gmail API on - nothing undone; wait ~1 min, rerun "
                       f"`gmail --profile {prof} onboard`")
