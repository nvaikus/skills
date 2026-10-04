"""onboard: guided, resumable setup of one profile (Apple ID). Prints ONLY the next step."""
from ...api import onboarding
from ...core import config, profile
from ...core.errors import CliError

PROFILE = "create"
WRITE = True
EXIT_WAITING = 5
EPILOG = """examples:
  icloud-calendar onboard                                  # start, or show where it stands (profile `main`)
  icloud-calendar onboard --apple-id me@icloud.com         # the user's answer to the first step
  icloud-calendar onboard --profile work --password-env ICLOUD_APP_PASSWORD_WORK   # second Apple ID

Driving it (agent): run, relay the text under "say to the user" WORD FOR WORD, get the answer,
run the command under "then run" with it, repeat until DONE. Exit 5 = waiting on the user; 0 = done.
The password is never typed into the chat or passed as an argument: the user stores it, a shell
export exposes it as $ICLOUD_APP_PASSWORD (name per profile: --password-env), Claude restarts.
--password-cmd 'CMD': a command that prints the password (keyring, pass, secret-tool), used when
the env var is empty. Every run re-checks live; DONE also caches the calendar home.
"""


def add_args(p):
    p.add_argument("--apple-id", metavar="EMAIL", help="the Apple ID (email) the user named")
    p.add_argument("--apple-id-env", metavar="VAR", help="env var with the Apple ID (default ICLOUD_APPLE_ID)")
    p.add_argument("--password-env", metavar="VAR", help="env var with the app-specific password (default ICLOUD_APP_PASSWORD)")
    p.add_argument("--password-cmd", metavar="CMD", help="command printing the password when the env var is empty")


def _text(r, prof):
    head = f"DONE profile {prof}" if r["status"] == "done" else f"WAITING {r['id']} (profile {prof})"
    out = [head, "--- say to the user ---", r["say"]]
    if r.get("next"):
        out += ["--- then run ---", r["next"]]
    return "\n".join(out) + "\n"


def run(ctx, args):
    prof = profile.active()
    cfg = config.update(prof) if prof not in profile.names() else config.load(prof)
    cfg = onboarding.apply(cfg, {k: getattr(args, k) for k in ("apple_id", "apple_id_env", "password_env",
                                                                 "password_cmd")}, prof)
    r = onboarding.advance(cfg, prof, ctx.note)
    ctx.text(_text(r, prof), {**r, "profile": prof})
    if r["status"] == "waiting":
        raise CliError(f"onboarding waits on the user ({r['id']}): relay the text, then run the command under "
                       "'then run'", code=EXIT_WAITING)
