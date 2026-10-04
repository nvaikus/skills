"""`ui --share / --unshare`: publish the UI on the tailnet through
`tailscale serve` (HTTPS, tailnet only — never funnel), behind web/gate.py.
Two shapes: a Tailscale Service `svc:NAME` (own MagicDNS name, https 443;
tagged hosts only — the default there) or an https port on the node's name.

Order matters: allow file written, UI up under autostart, gate proven on the
running server — only then the serve entry goes live. Other serve entries are
never touched; a port that serves something else is refused.
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

import backends
import identity
import procs
from errors import Conflict, ValidationError
from web import control, gate, server

DEFAULT_PORT = 8443
MAC_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
PROBE_IP = "203.0.113.7"  # TEST-NET-3: a "proxied" request in the gate probe
SVC_NAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


def cli():
    exe = shutil.which("tailscale") or (MAC_CLI if os.path.exists(MAC_CLI) else None)
    if not exe:
        raise ValidationError("tailscale CLI not found — install Tailscale and log in first")
    return exe


def ts(*args, write=False):
    """Run tailscale; a write denied to a non-operator retries via `sudo -n`."""
    exe = cli()
    p = subprocess.run([exe, *args], capture_output=True, text=True, timeout=30)
    denied = p.returncode and "denied" in (p.stdout + p.stderr).lower()
    if write and denied and hasattr(os, "geteuid") and os.geteuid() != 0 and shutil.which("sudo"):
        p = subprocess.run(["sudo", "-n", exe, *args], capture_output=True, text=True, timeout=30)
        if p.returncode:
            raise Conflict("tailscale refused the serve change and passwordless sudo is not available — run once: "
                           "sudo tailscale set --operator=$USER   then retry")
    if p.returncode:
        raise Conflict(f"tailscale {' '.join(args)} failed: {(p.stderr or p.stdout).strip()}")
    return p.stdout


def status():
    st = json.loads(ts("status", "--json") or "{}")
    if st.get("BackendState") != "Running":
        raise Conflict(f"tailscale is not running (state: {st.get('BackendState') or '?'}) — `tailscale up` first")
    return st


def serve_config():
    out = ts("serve", "status", "--json").strip()
    return json.loads(out) if out else {}


def dns_name(st):
    name = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not name:
        raise Conflict("this node has no tailnet DNS name (MagicDNS / HTTPS certificates off in the admin console?)")
    return name


def owner_login(st):
    """The login this node belongs to; None for a tagged node (no owner)."""
    me = st.get("Self") or {}
    if me.get("Tags"):
        return None
    user = (st.get("User") or {}).get(str(me.get("UserID"))) or {}
    return user.get("LoginName") or None


def tagged(st):
    return bool((st.get("Self") or {}).get("Tags"))


def suffix(st):
    """MagicDNS suffix of the tailnet (`tail1234.ts.net`)."""
    sfx = st.get("MagicDNSSuffix") or (st.get("CurrentTailnet") or {}).get("MagicDNSSuffix") or ""
    return sfx.strip(".") or dns_name(st).partition(".")[2]


def service_name(value):
    name = (value or identity.APP).strip().lower()
    name = name[4:] if name.startswith("svc:") else name
    if not SVC_NAME.fullmatch(name):
        raise ValidationError(f"bad service name '{value}' — a DNS label: a-z, 0-9, '-'")
    return name


def _ours(target, ui_port):
    return bool(re.fullmatch(rf"(https?://)?(127\.0\.0\.1|localhost|\[::1\]):{ui_port}/?", target or ""))


def _web_ours(web, ui_port):
    handlers = (web or {}).get("Handlers") or {}
    return bool(handlers) and all(_ours(h.get("Proxy"), ui_port) for h in handlers.values())


def entries(cfg, ui_port, host=None, sfx=None):
    """Serve entries pointing at this UI: [{service: "svc:X"|None, port, url, stale}].
    stale = keyed by a DNS name this node no longer has (tailnet or node renamed);
    unknown host/sfx = never stale."""
    out = []
    blocks = [(None, cfg)] + [(k, v or {}) for k, v in (cfg.get("Services") or {}).items()]
    for svc, block in blocks:
        want = (f"{svc[4:]}.{sfx}" if sfx else None) if svc else host
        for hostport, web in (block.get("Web") or {}).items():
            if not _web_ours(web, ui_port):
                continue
            h, _, port = hostport.rpartition(":")
            out.append({"service": svc, "port": int(port), "stale": bool(want) and h.lower() != want.lower(),
                        "url": f"https://{h}{'' if port == '443' else ':' + port}/"})
    return out


def shares(cfg, ui_port):
    """{https_port: url} of node-level (port mode) entries served by this UI."""
    return {e["port"]: e["url"] for e in entries(cfg, ui_port) if not e["service"]}


def stale_hint(e):
    if e["service"]:
        return f"fix: {identity.APP} ui --unshare --service {e['service'][4:]}   then share again"
    return ("tailscale cannot remove it per port (\"handler does not exist\"); fix: sudo tailscale serve reset — "
            f"drops EVERY serve entry and service, re-add the others — then {identity.APP} ui --share")


def stale_line(e):
    return (f"tailnet: STALE {e['url']} -> this UI   (keyed by a DNS name this node no longer has: "
            f"tailnet or node renamed) — {stale_hint(e)}")


def port_busy(cfg, host, port, ui_port):
    """What else serves `port`, or None."""
    tcp = (cfg.get("TCP") or {}).get(str(port))
    web = (cfg.get("Web") or {}).get(f"{host}:{port}")
    if web:
        others = [h.get("Proxy") or h.get("Path") or h.get("Text") or "?"
                  for h in (web.get("Handlers") or {}).values() if not _ours(h.get("Proxy"), ui_port)]
        return ", ".join(others) or None
    if tcp and not tcp.get("HTTPS"):
        return f"tcp forward to {tcp.get('TCPForward') or '?'}"
    return None


def svc_all_ours(block, ui_port):
    """Nothing but this UI's handlers in a service block (safe to `serve clear`)."""
    webs = (block.get("Web") or {}).values()
    tcp_ok = all(t.get("HTTPS") for t in (block.get("TCP") or {}).values())
    return tcp_ok and all(_web_ours(w, ui_port) for w in webs)


def probe(ui_port, headers):
    req = urllib.request.Request(f"http://127.0.0.1:{ui_port}/api/app", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return None


def prove_gate(ui_port, login):
    """The running UI must refuse a proxied request without an allowed login
    and accept the owner — else (an older UI build, a stranger) no share."""
    hint = f"restart it: {identity.APP} ui"
    anon = probe(ui_port, {"X-Forwarded-For": PROBE_IP})
    if anon is None:
        raise Conflict(f"no UI answers on 127.0.0.1:{ui_port} — {hint}")
    if anon != 403:
        raise Conflict(f"the running UI does not enforce the owner gate (proxied anonymous request -> {anon}) — {hint}")
    forged = probe(ui_port, {"X-Forwarded-For": PROBE_IP, gate.LOGIN: "intruder@example.invalid"})
    owner = probe(ui_port, {"X-Forwarded-For": PROBE_IP, gate.LOGIN: login})
    if forged != 403 or owner != 200:
        raise Conflict(f"owner gate misbehaves (stranger -> {forged}, {login} -> {owner}) — {hint}")


def ensure_ui(be, ui_port):
    """UI up and surviving reboots; lines to print."""
    if procs.IS_WIN:
        live = [p for p, c in procs.listeners(ui_port) if server.is_ours(c)]
        lines = [] if live else control.start_detached(ui_port)
        return lines + ["autostart: not available on Windows — after a reboot run "
                        f"`{identity.APP} ui` or the shared URL is dead"]
    st = be.ui_autostart_state()
    if not st:
        return control.autostart(be, "on", ui_port)
    if st["port"] != ui_port:
        raise ValidationError(f"autostart serves port {st['port']} — share that one (--port is the https port; "
                              f"the UI port follows autostart)")
    if not [p for p, c in procs.listeners(ui_port) if server.is_ours(c)]:
        return control.restart_service(be, st, ui_port)
    return [f"autostart: on    ({st['detail']})"]


def gate_login(st, extra_login):
    """(login to probe the gate with, lines). A tagged node has no owner: an
    allow list that already has someone will do; it is never wiped."""
    login = (extra_login or owner_login(st) or "").strip().lower()
    if login:
        return login, [f"allowed: {login}   (file: {gate.allow_file()})"] if gate.allow(login) else []
    have = sorted(gate.allowed())
    if have:
        return have[0], []
    raise ValidationError("this node is tagged (no owner login) and the allow list is empty — "
                          "pass --allow <tailscale-login>")


def share(ui_port, https_port=None, extra_login=None, service=None):
    """service: a name (or "" = the app name) for a Tailscale Service; None with
    no https_port = service on a tagged node, port 8443 otherwise."""
    st = status()
    host = dns_name(st)
    if service is None and https_port is None and tagged(st):
        service = ""
    if service is not None:
        if https_port is not None:
            raise ValidationError("--service serves on https 443 of its own name — drop the port")
        return share_service(st, ui_port, service_name(service), extra_login)
    https_port = https_port or DEFAULT_PORT
    login, out = gate_login(st, extra_login)
    cfg = serve_config()
    busy = port_busy(cfg, host, https_port, ui_port)
    if busy:
        raise Conflict(f"https port {https_port} already serves {busy} — pick another: ui --share <port>")
    stale = [e for e in entries(cfg, ui_port, host) if not e["service"] and e["stale"] and e["port"] == https_port]
    if stale:
        raise Conflict(stale_line(stale[0])[len("tailnet: "):])
    out += ensure_ui(backends.current(), ui_port)
    prove_gate(ui_port, login)
    url = shares(cfg, ui_port).get(https_port)
    if not url:
        ts("serve", "--bg", f"--https={https_port}", f"http://127.0.0.1:{ui_port}", write=True)
        url = f"https://{host}{'' if https_port == 443 else f':{https_port}'}/"
    who = ", ".join(sorted(gate.allowed()))
    return out + [f"tailnet: {url}   (tailnet only; allowed: {who})",
                  f"unshare: {identity.APP} ui --unshare"]


def share_service(st, ui_port, name, extra_login):
    svc = f"svc:{name}"
    if not tagged(st):
        raise ValidationError(f"{svc} needs a tagged host (Tailscale Services serve from tagged nodes only) — "
                              f"tag this node, or share by port: {identity.APP} ui --share 8443")
    login, out = gate_login(st, extra_login)
    fqdn = f"{name}.{suffix(st)}"
    block = (serve_config().get("Services") or {}).get(svc) or {}
    busy = port_busy(block, fqdn, 443, ui_port)
    if busy:
        raise Conflict(f"{svc} already serves {busy} on 443 — pick another name: ui --share --service <name>")
    mine = [e for e in entries({"Services": {svc: block}}, ui_port, sfx=suffix(st))]
    out += ensure_ui(backends.current(), ui_port)
    prove_gate(ui_port, login)
    if any(e["stale"] for e in mine) and svc_all_ours(block, ui_port):
        ts("serve", "clear", svc, write=True)
        out.append(f"cleared stale {svc} entries ({', '.join(e['url'] for e in mine if e['stale'])})")
        mine = []
    live = svc_live(st, svc)
    if not any(e["port"] == 443 and not e["stale"] for e in mine):
        said = ts("serve", f"--service={svc}", "--https=443", f"http://127.0.0.1:{ui_port}", write=True)
        live = wait_live(svc, live)
        if live is None and "approval" in said.lower():
            live = False
    if live is False:
        out.append(f"pending: {svc} is not approved for this host yet (an autoApprover needs up to ~30 s after "
                   f"a fresh advertise; re-check: {identity.APP} ui). If it stays: admin console -> Services -> "
                   "Define a Service (endpoint tcp:443), then approve this host or add an autoApprover "
                   "(references/tailnet.md)")
    who = ", ".join(sorted(gate.allowed()))
    return out + [f"tailnet: https://{fqdn}/   ({svc}; tailnet only; allowed: {who})",
                  "test from another device — a host cannot reach its own service address",
                  f"unshare: {identity.APP} ui --unshare --service {name}"]


def svc_live(st, svc):
    """True = the control plane lets this host serve svc (CapMap service-host),
    False = not (undefined or not approved), None = unknown (no such CapMap)."""
    cap = (st.get("Self") or {}).get("CapMap") or {}
    if "service-host" not in cap:
        return None
    return any(svc in (m or {}) for m in cap.get("service-host") or [])


def wait_live(svc, live, secs=10):
    """An autoApprover approves a fresh advertisement within ~10-30 s. CapMap
    lags both ways: right after an unshare it may still list svc (accepted)."""
    deadline = time.time() + secs
    while live is False and time.time() < deadline:
        time.sleep(0.5)
        live = svc_live(status(), svc)
    return live if live is not None else svc_live(status(), svc)


def unshare(ui_port, https_port=None, service=None):
    """Remove this UI's serve entries: one port, one service, or (neither) all."""
    cfg = serve_config()
    try:
        st = status()
        host, sfx = dns_name(st), suffix(st)
    except (Conflict, ValidationError, ValueError):
        host = sfx = None
    svc = f"svc:{service_name(service)}" if service is not None else None
    mine = [e for e in entries(cfg, ui_port, host, sfx)
            if (svc and e["service"] == svc) or (https_port and not e["service"] and e["port"] == https_port)
            or (svc is None and https_port is None)]
    if not mine:
        what = f" as {svc}" if svc else f" on port {https_port}" if https_port else ""
        return [f"tailnet: not shared{what}"]
    out = []
    for name in sorted({e["service"] for e in mine if e["service"]}):
        block = cfg["Services"][name]
        own = [e for e in mine if e["service"] == name]
        if svc_all_ours(block, ui_port):
            ts("serve", "clear", name, write=True)
        else:  # the service also serves something else: drop only our ports
            for e in own:
                if not e["stale"]:
                    ts("serve", f"--service={name}", f"--https={e['port']}", "off", write=True)
            out += [stale_line(e) for e in own if e["stale"]]
            own = [e for e in own if not e["stale"]]
        out += [f"unshared {e['url']}   ({name})" for e in own]
    for e in [e for e in mine if not e["service"]]:
        if e["stale"]:
            out.append(stale_line(e))
            continue
        try:
            ts("serve", f"--https={e['port']}", "off", write=True)
        except Conflict as err:
            if "does not exist" not in str(err):
                raise
            out.append(stale_line(e))
            continue
        out.append(f"unshared {e['url']}")
    return out + [f"allow list kept: {gate.allow_file()}"]


def state_line(ui_port):
    """Status lines for `ui`; empty when tailscale is absent or unreadable."""
    try:
        cli()
        cfg = serve_config()
    except (ValidationError, Conflict, ValueError, OSError, subprocess.SubprocessError):
        return []
    try:
        st = status()
        host, sfx = dns_name(st), suffix(st)
    except (ValidationError, Conflict, ValueError, OSError, subprocess.SubprocessError):
        st, host, sfx = {}, None, None
    mine = entries(cfg, ui_port, host, sfx)
    if not mine:
        return [f"tailnet: not shared   (phone access: {identity.APP} ui --share)"]
    who = ", ".join(sorted(gate.allowed())) or "nobody — every proxied request gets 403"
    def svc_note(e):
        if not e["service"]:
            return ""
        pending = svc_live(st, e["service"]) is False
        return e["service"] + ("; NOT approved for this host yet, see references/tailnet.md" if pending else "") + "; "
    return [stale_line(e) if e["stale"] else f"tailnet: {e['url']}   ({svc_note(e)}allowed: {who})" for e in mine]
