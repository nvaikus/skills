"""onboard: guided, resumable setup of one profile (Google account). Prints ONLY the next step."""
import argparse

from ...api import autoconsole, onboarding
from ...core import config, profile
from ...core.errors import CliError, Deadline

PROFILE = "create"
WRITE = True
WAIT = True
EXIT_WAITING = 5
EPILOG = """examples:
  gdrive onboard --profile work                  # start, or show where it stands
  gdrive onboard --profile work --mode auto      # browser does steps 3-9; user signs in + 1 click
  gdrive onboard --profile work --project personal-drive-123456      # manual answers ...
  gdrive onboard --profile work --done apis      # ... apis | consent | branding | publish
  gdrive onboard --profile work --client-file ~/Downloads/client_secret_123.json
  printf '%s' '<address the user pasted>' | gdrive --profile work login --finish
  gdrive onboard --profile work --mount / --where ~/gdrive/work

Driving it (agent): run, relay the text under "say to the user" WORD FOR WORD, get the answer,
run the command under "then run" with it, repeat until DONE. "then run (right away ...)": run it
at once, no answer needed (auto mode: it waits up to --wait for the browser job). Every run
re-checks live and never repeats finished work. Exit 5 = waiting on the user; 0 = done;
6 = still working (browser job or mount starting): rerun.
--mode auto needs Node.js + Playwright + Chrome and a screen (not over SSH); a step it cannot do
falls back to its manual text, `--mode auto` again retries. Browser profile + screenshots:
~/.claude/gdrive/<profile>/auto/. --mode manual stops a running job.
--mount: / (all of My Drive) · /Folder · shared:<Shared drive>[/Folder]; default place ~/gdrive/<profile>.
Publish greyed out = Branding not saved (shared home/privacy pages on nvaikus.github.io work for
anyone); cannot publish at all: --keep-testing (7-day logins). Drive-less token = box unticked.
The first profile becomes the default one. Old ~/.gdrive.json is imported once if present.
"""


def add_args(p):
    p.add_argument("--mode", choices=("auto", "manual"),
                   help="step 2: auto = browser automation (again: retry it), manual = step texts")
    p.add_argument("--project", metavar="ID", help="Google Cloud Project ID the user created (step 3)")
    p.add_argument("--account", metavar="EMAIL", help="the user's Google address, if known: tunes the texts")
    p.add_argument("--done", action="append", choices=onboarding.DONE_STEPS, metavar="STEP",
                   help="the user finished a console step: apis (4) | consent (5) | branding (6) | publish (7)")
    p.add_argument("--apis-done", action="store_true", help=argparse.SUPPRESS)  # v0.2 spelling of --done apis
    p.add_argument("--audience", choices=("internal", "external"), help="what the user chose in step 5")
    p.add_argument("--keep-testing", action="store_true",
                   help="do not publish: Google's Testing mode, login renewed every 7 days (step 7)")
    p.add_argument("--client-file", metavar="PATH", help="the downloaded Desktop-app client JSON (step 8)")
    p.add_argument("--mount", metavar="WHAT", help="what to connect: / , /Folder or shared:<Drive> (step 10)")
    p.add_argument("--where", metavar="DIR", help="local folder for it (default ~/gdrive/<profile>)")
    p.add_argument("--persist", choices=("yes", "no"), help="reconnect after restart/login (step 11)")
    p.add_argument("--auto-job", action="store_true", help=argparse.SUPPRESS)  # the background browser job


def _text(r, prof):
    head = (f"DONE profile {prof}" if r["status"] == "done" else
            f"WAITING step {r['step']}/{r['total']} {r['id']} (profile {prof})" if r["status"] == "waiting" else
            f"RUNNING step {r['step']}/{r['total']} {r['id']} (profile {prof})")
    out = [head, "--- say to the user ---", r["say"]]
    if r.get("next"):
        out += ["--- then run (right away, no answer needed) ---" if r.get("now") else "--- then run ---", r["next"]]
    return "\n".join(out) + "\n"


def run(ctx, args):
    prof = profile.active()
    if args.auto_job:
        return autoconsole.run_job(prof, ctx.note)
    new = prof not in profile.names()
    cfg = config.update() if new else ctx.cfg  # creates the profile's config.json
    if not profile.root_config().get("default_profile"):
        profile.set_default(prof)
    answers = {k: getattr(args, k) for k in ("mode", "project", "account", "done", "apis_done", "audience",
                                              "keep_testing", "client_file", "mount", "where", "persist")}
    cfg = onboarding.apply(cfg, answers, ctx.note)
    env = onboarding.LiveEnv(cfg, prof, min(args.wait, 90), ctx.note, auto_wait_s=args.wait)
    if args.mode == "manual" and env.auto_stop():
        ctx.note("stopped the automatic setup; its Chrome window may be closed")
    r = onboarding.advance(env, cfg, prof, ctx.note, restart=args.mode == "auto")
    ctx.text(_text(r, prof), {**r, "profile": prof})  # -j: the fields + the same text
    if r["status"] == "waiting":
        raise CliError(f"onboarding waits on the user (step {r['step']}/{r['total']} {r['id']}): relay the text, "
                       "then run the command under 'then run'", code=EXIT_WAITING)
    if r["status"] == "running":
        what = "the mount is still starting" if r["id"] == "mount-starting" else "the browser setup is still working"
        raise Deadline(f"{what} - nothing undone; rerun `gdrive --profile {prof} onboard`")
