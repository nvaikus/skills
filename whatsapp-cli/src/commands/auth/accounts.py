"""accounts: linked accounts on this machine. No network."""
from ...core import config
from ...core.store import Store

FIELDS = ["account", "default", "jid", "messages", "synced"]
EPILOG = """examples:
  wa-cli accounts
  wa-cli --account work whoami     # check a session is still alive (network)
"""


def add_args(p):
    pass


def run(ctx, args):
    from ...api.peers import iso_ts
    rows = []
    for a in config.accounts():
        r = {"account": a, "default": a == ctx.cfg["default_account"], "jid": None, "messages": 0, "synced": None,
             "session": str(config.session_path(a))}
        if config.store_path(a).exists():
            st = Store(config.store_path(a))
            r.update(jid=st.get_meta("me_jid"), messages=st.counts()["messages"],
                     synced=iso_ts(int(st.get_meta("synced", 0) or 0)))
            st.close()
        rows.append(r)
    ctx.write(rows, FIELDS)
    if not rows:
        ctx.note("no accounts on this machine - a person runs: wa-cli login")
