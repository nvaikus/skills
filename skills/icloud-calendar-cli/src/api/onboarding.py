"""Onboarding: one step per run. Each step = {status, id, say, next}. The texts are relayed to the
user word for word; the password itself never passes through the chat, argv or a file."""
import os
import platform

from ..core import config, profile
from ..core.errors import AuthError, UsageError
from . import calendars
from .dav import Session

APPLE_PAGE = "https://account.apple.com"


def _store_text(var, system=None):
    system = system or platform.system()
    if system == "Darwin":
        return (f"4. Store it in the macOS Keychain: with the password still copied, run in Terminal\n"
                f"   (nothing is shown, the password never appears on screen):\n"
                f"   security add-generic-password -U -a \"$USER\" -s {var} -w \"$(pbpaste | tr -d '[:space:]')\"\n"
                f"5. Make it visible to programs - add this line to ~/.zshrc:\n"
                f"   export {var}=\"$(security find-generic-password -a \"$USER\" -s {var} -w 2>/dev/null)\"\n"
                f"   (I can add that line for you - it holds no secret.)")
    if system == "Windows":
        return (f"4. Store it as your user environment variable: in PowerShell run\n"
                f"   [Environment]::SetEnvironmentVariable('{var}', (Get-Clipboard).Trim(), 'User')")
    return (f"4. Store it where your shell can read it without writing it into a plain file, e.g. with\n"
            f"   secret-tool:  secret-tool store --label={var} service {var}   (paste when asked)\n"
            f"   then add to ~/.bashrc or ~/.zshrc:\n"
            f"   export {var}=\"$(secret-tool lookup service {var})\"\n"
            f"   No keyring on this machine (headless server)? Pass it in from another machine's\n"
            f"   environment, or tell me the command that prints it (`--password-cmd`).")


def steps_say(step, cfg, prof, system=None):
    var = cfg.get("password_env") or "ICLOUD_APP_PASSWORD"
    idvar = cfg.get("apple_id_env") or "ICLOUD_APPLE_ID"
    if step == "apple-id":
        return ("iCloud Calendar setup.\n"
                "Which Apple ID (the email you sign in to iCloud with) holds your calendars?",
                f"icloud-calendar onboard --profile {prof} --apple-id EMAIL")
    if step == "app-password":
        return ("iCloud Calendar needs an app-specific password (your normal Apple password is never used).\n\n"
                f"1. Open {APPLE_PAGE} and sign in with {cfg.get('apple_id') or 'your Apple ID'}.\n"
                "2. Go to \"Sign-In and Security\" -> \"App-Specific Passwords\" -> \"+\" (or \"Generate\").\n"
                "   Name it \"icloud-calendar\". Apple shows a password like abcd-efgh-ijkl-mnop.\n"
                "3. Copy it (Apple shows it only once). Do NOT paste it into this chat.\n"
                + _store_text(var, system) + "\n"
                "6. Restart Claude (so it sees the new variable) and tell me \"done\".",
                f"icloud-calendar onboard --profile {prof}")
    if step == "password-rejected":
        return ("iCloud did not accept the Apple ID / app-specific password.\n"
                f"- Check the Apple ID: {cfg.get('apple_id') or '$' + idvar}\n"
                f"- The password in {var} may be revoked or mistyped: create a new one at {APPLE_PAGE}\n"
                "  (\"Sign-In and Security\" -> \"App-Specific Passwords\"), store it the same way as before\n"
                "  (the store command replaces the old one), restart Claude and tell me \"done\".",
                f"icloud-calendar onboard --profile {prof}")
    raise KeyError(step)


def apply(cfg, args, prof):
    changes = {}
    if args.get("apple_id"):
        if "@" not in args["apple_id"]:
            raise UsageError(f"{args['apple_id']!r} does not look like an Apple ID email")
        changes["apple_id"] = args["apple_id"].strip()
    for k in ("apple_id_env", "password_env", "password_cmd"):
        if args.get(k):
            changes[k] = args[k]
    return config.update(prof, **changes) if changes else cfg


def advance(cfg, prof, note):
    apple_id = os.environ.get(cfg.get("apple_id_env") or "ICLOUD_APPLE_ID") or cfg.get("apple_id")
    if not apple_id:
        return _wait("apple-id", cfg, prof)
    try:
        session = Session(cfg)
    except UsageError:
        return _wait("app-password", cfg, prof)
    try:
        cfg = calendars.discover(session, prof)
    except AuthError:
        return _wait("password-rejected", cfg, prof)
    session.cfg = cfg
    if not cfg.get("apple_id"):
        cfg = config.update(prof, apple_id=apple_id)
    cals = calendars.list_all(session, cfg)
    if not profile.root_config().get("default_profile"):
        profile.set_default(prof)
    events = [c for c in cals if c["events"]]
    rw = [c for c in events if c["access"] == "rw" and c["kind"] != "subscribed"]
    lines = [f"Connected to iCloud as {apple_id}: {len(events)} event calendars "
             f"({len(rw)} you can add to), {len(cals) - len(events)} reminder lists."]
    nxt = None
    if not cfg.get("default_calendar") and len(rw) > 1:
        lines.append("Which calendar should new events go to when you don't name one? "
                     f"({', '.join(c['name'] for c in rw)})")
        nxt = f"icloud-calendar --profile {prof} calendars --set-default NAME"
    elif not cfg.get("default_calendar") and len(rw) == 1:
        config.update(prof, default_calendar=rw[0]["id"])
        lines.append(f"New events go to {rw[0]['name']!r}.")
    return {"status": "done", "id": "done", "say": "\n".join(lines), "next": nxt, "calendars": len(cals)}


def _wait(step, cfg, prof):
    say, nxt = steps_say(step, cfg, prof)
    return {"status": "waiting", "id": step, "say": say, "next": nxt}

