"""Which local user opened a connection (Linux). The UI listens on 127.0.0.1,
which every user of the machine can reach; a task = a shell command run as the
server's user, so only that user (and root: `tailscale serve`, then gate.py
applies) may talk to it.

- Lookup: the client socket is the /proc/net/tcp{,6} row whose local address is
  the client's (ip, port) and remote address is ours; its `uid` column = owner.
- A row with inode 0 is an orphan / TIME_WAIT socket whose uid reads 0: never
  trusted (a client that sent its request and closed would pass as root).
- Not Linux: no check (macOS/Windows behave as before). Linux and no row:
  refused (fail closed).
"""
import ipaddress
import os
import struct
import sys

TABLES = ("/proc/net/tcp", "/proc/net/tcp6")
UNKNOWN = object()  # Linux, lookup failed


def enabled():
    return sys.platform.startswith("linux")


def _addr(field):
    """`0100007F:1F90` -> ('127.0.0.1', 8080); v6 words are host-order u32s;
    v4-mapped v6 collapses to v4."""
    hexip, hexport = field.split(":")
    words = [int(hexip[i:i + 8], 16) for i in range(0, len(hexip), 8)]
    ip = ipaddress.ip_address(b"".join(struct.pack("=I", w) for w in words))
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip), int(hexport, 16)


def _norm(addr):
    ip = ipaddress.ip_address(addr[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip), int(addr[1])


def parse(text):
    """Rows of one table -> [(local, remote, uid, inode)]; malformed rows skipped."""
    out = []
    for line in text.splitlines()[1:]:
        f = line.split()
        try:
            out.append((_addr(f[1]), _addr(f[2]), int(f[7]), int(f[9])))
        except (IndexError, ValueError):
            continue
    return out


def find(rows, client, server):
    client, server = _norm(client), _norm(server)
    for local, remote, uid, inode in rows:
        if local == client and remote == server and inode:
            return uid
    return None


def lookup(client, server, tables=TABLES):
    """Owner uid of the socket at `client` connected to `server`; None = not found."""
    rows = []
    for t in tables:
        try:
            with open(t, encoding="ascii", errors="replace") as fh:
                rows += parse(fh.read())
        except OSError:
            continue
    return find(rows, client, server)


def owner(client, server):
    """None off Linux (no check), UNKNOWN on a failed lookup, else the uid."""
    if not enabled():
        return None
    try:
        uid = lookup(client, server)
    except Exception:  # never let a parse bug open the door
        uid = None
    return UNKNOWN if uid is None else uid


def check(uid):
    """None = let it through (gate.py still applies); else the reason for a 403."""
    if uid is None or uid in (0, os.getuid()):
        return None
    if uid is UNKNOWN:
        return "could not tell which local user opened this connection"
    return f"local uid {uid} is not the owner of this UI"
