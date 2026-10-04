"""whoami: live address + mailbox size of each profile (all, or --profile)."""
from ...api import mail
from ...core.errors import CliError

PROFILE = "all"
FIELDS = ["profile", "email", "messages", "threads"]
EPILOG = """examples:
  gmail whoami                 # every profile; a broken login shows its error in the 'error' column
  gmail whoami --profile work
"""


def add_args(p):
    pass


def run(ctx, args):
    def one(prof):
        try:
            st = mail.mailbox(prof)
            return {"profile": prof, "email": st.get("emailAddress"), "messages": st.get("messagesTotal"),
                    "threads": st.get("threadsTotal"), "error": ""}
        except CliError as e:
            return {"profile": prof, "email": None, "messages": None, "threads": None, "error": str(e)}
    rows = mail.pmap(one, ctx.profiles)
    fields = FIELDS + (["error"] if any(r["error"] for r in rows) else [])
    ctx.write(rows, fields)
    return 1 if rows and all(r["error"] for r in rows) else 0
