"""Owner gate (real threaded server) and `ui --share/--unshare` against a
fake `tailscale` binary that keeps its serve config in a JSON file."""
import http.client
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

import base
from errors import Conflict, ValidationError
from web import control, gate, server, tailnet

OWNER = "owner@example.com"
SUFFIX = "tail0000.ts.net"
HOST = "box." + SUFFIX
SVC_HOST = "clockmaster." + SUFFIX

FAKE = r'''
import json, os, sys
d = os.environ["FAKE_TS_DIR"]
a = sys.argv[1:]
open(os.path.join(d, "calls.log"), "a").write(("sudo " if os.environ.get("FAKE_SUDO") else "") + " ".join(a) + "\n")
cfgp = os.path.join(d, "serve.json")
cfg = json.load(open(cfgp)) if os.path.exists(cfgp) else {}
if a == ["status", "--json"]:
    print(open(os.path.join(d, "status.json")).read()); sys.exit(0)
if a == ["serve", "status", "--json"]:
    print(json.dumps(cfg) if cfg else ""); sys.exit(0)
if a and a[0] == "serve":
    if os.path.exists(os.path.join(d, "deny")) and not os.environ.get("FAKE_SUDO"):
        print("sending serve config: Access denied: serve config denied", file=sys.stderr); sys.exit(1)
    if a[1] == "clear":
        cfg.get("Services", {}).pop(a[2], None)
        json.dump(cfg, open(cfgp, "w")); sys.exit(0)
    svc = [x.split("=", 1)[1] for x in a if x.startswith("--service=")]
    port = [x for x in a if x.startswith("--https=")][0].split("=")[1]
    block, host = (cfg.setdefault("Services", {}).setdefault(svc[0], {}), svc[0][4:] + "." + SUFFIX) if svc else (cfg, HOST)
    if a[-1] == "off":
        key = "%s:%s" % (host, port)
        if key not in block.get("Web", {}):
            print("error: handler does not exist", file=sys.stderr); sys.exit(1)
        block.get("TCP", {}).pop(port, None); block["Web"].pop(key)
    else:
        block.setdefault("TCP", {})[port] = {"HTTPS": True}
        block.setdefault("Web", {})["%s:%s" % (host, port)] = {"Handlers": {"/": {"Proxy": a[-1]}}}
        if svc:
            print("This machine is configured as a service proxy for %s, but approval from an admin is required." % svc[0])
    json.dump(cfg, open(cfgp, "w")); sys.exit(0)
sys.exit(3)
'''.replace("HOST", repr(HOST)).replace("SUFFIX", repr(SUFFIX))

YAPDUB = {"TCP": {"443": {"HTTPS": True}},
          "Web": {f"{HOST}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}}}
OTHER_SVC = {"TCP": {"443": {"HTTPS": True}},
             "Web": {f"demo.{SUFFIX}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}}}


class ServerCase(base.Case):
    def setUp(self):
        super().setUp()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def req(self, method="GET", path="/api/app", headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        c.putrequest(method, path, skip_host="Host" in h)
        for k, v in h.items():
            for one in (v if isinstance(v, list) else [v]):
                c.putheader(k, one)
        data = body or b""
        c.putheader("Content-Length", str(len(data)))
        c.endheaders(data)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status


class Gate(ServerCase):
    def setUp(self):
        super().setUp()
        gate.allow(OWNER)

    def test_direct_local_passes(self):
        self.assertEqual(self.req(), 200)
        self.assertEqual(self.req(headers={"Host": f"localhost:{self.port}"}), 200)

    def test_proxied_without_identity_is_refused(self):
        self.assertEqual(self.req(headers={"X-Forwarded-For": "198.51.100.9"}), 403)
        self.assertEqual(self.req(headers={"Host": f"{HOST}:8443"}), 403)  # foreign Host, no headers
        self.assertEqual(self.req(headers={"Tailscale-Headers-Info": "x"}), 403)

    def test_wrong_login_and_funnel_refused(self):
        self.assertEqual(self.req(headers={"X-Forwarded-For": "198.51.100.9", gate.LOGIN: "other@example.com"}), 403)
        self.assertEqual(self.req(headers={"X-Forwarded-For": "1.2.3.4", gate.LOGIN: OWNER,
                                           "Tailscale-Funnel-Request": "?1"}), 403)
        self.assertEqual(self.req(headers={"X-Forwarded-For": "1.2.3.4",
                                           gate.LOGIN: [OWNER, "other@example.com"]}), 403)

    def test_owner_passes_case_insensitive(self):
        h = {"Host": f"{HOST}:8443", "X-Forwarded-For": "198.51.100.9", gate.LOGIN: OWNER.upper()}
        self.assertEqual(self.req(headers=h), 200)
        self.assertEqual(self.req(headers={**h, "Origin": f"https://{HOST}:8443"}, method="POST", path="/api/sync"), 200)

    def test_cross_origin_write_refused(self):
        self.assertEqual(self.req("POST", "/api/sync", {"Origin": "https://evil.example"}), 403)
        self.assertEqual(self.req("POST", "/api/sync", {"Origin": "null"}), 403)
        self.assertEqual(self.req("POST", "/api/sync", {"Sec-Fetch-Site": "cross-site"}), 403)
        self.assertEqual(self.req("POST", "/api/sync", {"Origin": f"http://127.0.0.1:{self.port}"}), 200)
        self.assertEqual(self.req("GET", "/api/app", {"Origin": "https://evil.example"}), 200)

    def test_allow_file_comments_and_dedupe(self):
        self.assertFalse(gate.allow(OWNER.upper()))
        gate.allow_file().write_text("# c\n\n a@b.c # note\n", encoding="utf-8")
        self.assertEqual(gate.allowed(), {"a@b.c"})


class Share(ServerCase):
    def setUp(self):
        super().setUp()
        self.ts = self.tmp / "ts"
        self.ts.mkdir()
        os.environ["FAKE_TS_DIR"] = str(self.ts)
        (self.ts / "fake.py").write_text(FAKE, encoding="utf-8")
        self.fake_bin("tailscale", f'exec "{sys.executable}" "{self.ts / "fake.py"}" "$@"\n')
        self.fake_bin("sudo", '[ "$1" = -n ] && shift\nFAKE_SUDO=1 exec "$@"\n')
        self.set_status()
        self.write_cfg(YAPDUB)
        self.ensured = []
        self._ensure = tailnet.ensure_ui
        tailnet.ensure_ui = lambda be, port: self.ensured.append(port) or ["autostart: on (fake)"]

    def tearDown(self):
        tailnet.ensure_ui = self._ensure
        os.environ.pop("FAKE_TS_DIR", None)
        super().tearDown()

    def set_status(self, tags=None, state="Running", live=None):
        me = {"DNSName": HOST + ".", "UserID": 42, **({"Tags": tags} if tags else {})}
        if live is not None:
            me["CapMap"] = {"service-host": [{s: ["100.64.0.9"] for s in live}]}
        st = {"BackendState": state, "Self": me, "User": {"42": {"LoginName": OWNER}}, "MagicDNSSuffix": SUFFIX}
        (self.ts / "status.json").write_text(json.dumps(st), encoding="utf-8")

    def write_cfg(self, cfg):
        (self.ts / "serve.json").write_text(json.dumps(cfg), encoding="utf-8")

    def cfg(self):
        return json.loads((self.ts / "serve.json").read_text(encoding="utf-8"))

    def calls(self):
        p = self.ts / "calls.log"
        return p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    def test_share_records_owner_proves_gate_and_keeps_other_entries(self):
        out = "\n".join(control.run(["--port", str(self.port), "--share"]))
        self.assertIn(f"https://{HOST}:8443/", out)
        self.assertEqual(gate.allowed(), {OWNER})
        self.assertEqual(self.ensured, [self.port])
        cfg = self.cfg()
        self.assertEqual(cfg["Web"][f"{HOST}:443"], YAPDUB["Web"][f"{HOST}:443"])
        self.assertEqual(cfg["Web"][f"{HOST}:8443"]["Handlers"]["/"]["Proxy"], f"http://127.0.0.1:{self.port}")
        self.assertIn(f"https://{HOST}:8443/", "\n".join(tailnet.state_line(self.port)))
        # idempotent: no second serve write
        control.run(["--port", str(self.port), "--share"])
        self.assertEqual(sum(c.startswith("serve --bg") for c in self.calls()), 1)
        # unshare removes only ours
        self.assertIn("unshared", "\n".join(control.run(["--port", str(self.port), "--unshare"])))
        self.assertEqual(set(self.cfg()["Web"]), {f"{HOST}:443"})
        self.assertIn("not shared", "\n".join(tailnet.state_line(self.port)))

    def test_denied_retries_with_sudo(self):
        (self.ts / "deny").write_text("", encoding="utf-8")
        control.run(["--port", str(self.port), "--share", "9443"])
        self.assertIn("sudo serve --bg --https=9443 " + f"http://127.0.0.1:{self.port}", self.calls())

    def test_refusals(self):
        with self.assertRaisesRegex(Conflict, "already serves http://127.0.0.1:8000"):
            control.run(["--port", str(self.port), "--share", "443"])
        self.set_status(tags=["tag:server"])
        gate.allow_file().unlink()
        with self.assertRaisesRegex(ValidationError, "--allow"):
            control.run(["--port", str(self.port), "--share"])
        with self.assertRaisesRegex(ValidationError, "drop the port"):
            control.run(["--port", str(self.port), "--share", "8443", "--service"])
        with self.assertRaisesRegex(ValidationError, "bad service name"):
            control.run(["--port", str(self.port), "--share", "--service", "No_Good", "--allow", OWNER])
        self.set_status()
        with self.assertRaisesRegex(ValidationError, "tagged host"):
            control.run(["--port", str(self.port), "--share", "--service"])
        self.set_status(state="NeedsLogin")
        with self.assertRaisesRegex(Conflict, "not running"):
            control.run(["--port", str(self.port), "--share"])
        self.assertNotIn(f"{HOST}:8443", self.cfg()["Web"])

    def test_tagged_node_with_explicit_allow(self):
        self.set_status(tags=["tag:server"])
        control.run(["--port", str(self.port), "--share", "8443", "--allow", "Me@Example.com"])
        self.assertEqual(gate.allowed(), {"me@example.com"})
        self.assertIn(f"{HOST}:8443", self.cfg()["Web"])

    def test_service_share_status_unshare(self):
        self.set_status(tags=["tag:server"])
        self.write_cfg({"Services": {"svc:demo": OTHER_SVC}})
        gate.allow(OWNER)  # tagged: a non-empty allow list stands in for --allow
        out = "\n".join(control.run(["--port", str(self.port), "--share"]))  # tagged -> service by default
        self.assertIn(f"https://{SVC_HOST}/", out)
        self.assertIn("not approved for this host yet", out)  # tailscale's own words, no CapMap here
        self.assertEqual(gate.allowed(), {OWNER})
        self.assertIn(f"serve --service=svc:clockmaster --https=443 http://127.0.0.1:{self.port}", self.calls())
        svc = self.cfg()["Services"]
        self.assertEqual(svc["svc:demo"], OTHER_SVC)
        self.assertEqual(svc["svc:clockmaster"]["Web"][f"{SVC_HOST}:443"]["Handlers"]["/"]["Proxy"],
                         f"http://127.0.0.1:{self.port}")
        self.assertIn(f"https://{SVC_HOST}/   (svc:clockmaster; allowed: {OWNER})",
                      "\n".join(tailnet.state_line(self.port)))
        control.run(["--port", str(self.port), "--share", "--service", "svc:clockmaster"])  # idempotent
        self.assertEqual(sum("--service=" in c for c in self.calls()), 1)
        self.assertIn("not shared", control.run(["--port", str(self.port), "--unshare", "--service", "other"])[0])
        out = "\n".join(control.run(["--port", str(self.port), "--unshare"]))
        self.assertIn(f"unshared https://{SVC_HOST}/", out)
        self.assertIn("serve clear svc:clockmaster", self.calls())
        self.assertEqual(self.cfg()["Services"], {"svc:demo": OTHER_SVC})

    def test_service_approval_from_capmap(self):
        self.set_status(tags=["tag:server"], live=["svc:clockmaster"])
        out = "\n".join(control.run(["--port", str(self.port), "--share", "--allow", OWNER]))
        self.assertNotIn("not approved", out)
        self.assertNotIn("NOT approved", "\n".join(tailnet.state_line(self.port)))
        self.set_status(tags=["tag:server"], live=["svc:demo"])
        self.assertIn("svc:clockmaster; NOT approved", "\n".join(tailnet.state_line(self.port)))

    def test_service_name_taken_by_other_target(self):
        self.set_status(tags=["tag:server"])
        self.write_cfg({"Services": {"svc:demo": OTHER_SVC}})
        with self.assertRaisesRegex(Conflict, "svc:demo already serves http://127.0.0.1:8000"):
            control.run(["--port", str(self.port), "--share", "--service", "demo", "--allow", OWNER])

    def test_stale_entries_after_tailnet_rename(self):
        old = "box.oldnet.ts.net"
        mine = {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{self.port}"}}}
        self.write_cfg({"TCP": {"8443": {"HTTPS": True}}, "Web": {f"{old}:8443": mine},
                        "Services": {"svc:clockmaster": {"TCP": {"443": {"HTTPS": True}},
                                                         "Web": {"clockmaster.oldnet.ts.net:443": mine}}}})
        lines = "\n".join(tailnet.state_line(self.port))
        self.assertIn(f"STALE https://{old}:8443/", lines)
        self.assertIn("sudo tailscale serve reset", lines)
        self.assertIn("STALE https://clockmaster.oldnet.ts.net/", lines)
        with self.assertRaisesRegex(Conflict, "serve reset"):
            control.run(["--port", str(self.port), "--share"])
        self.set_status(tags=["tag:server"])
        out = "\n".join(control.run(["--port", str(self.port), "--share", "--allow", OWNER]))
        self.assertIn("cleared stale svc:clockmaster", out)
        self.assertEqual(set(self.cfg()["Services"]["svc:clockmaster"]["Web"]), {f"{SVC_HOST}:443"})
        out = "\n".join(control.run(["--port", str(self.port), "--unshare"]))
        self.assertIn(f"STALE https://{old}:8443/", out)
        self.assertFalse([c for c in self.calls() if c.endswith("--https=8443 off")])
        self.assertIn(f"{old}:8443", self.cfg()["Web"])  # never reset automatically

    def test_ungated_ui_blocks_share(self):
        orig = gate.check
        gate.check = lambda method, headers: None  # an old UI build without the gate
        try:
            with self.assertRaisesRegex(Conflict, "does not enforce the owner gate"):
                control.run(["--port", str(self.port), "--share"])
        finally:
            gate.check = orig
        self.assertNotIn(f"{HOST}:8443", self.cfg()["Web"])

    def test_missing_tailscale(self):
        (self.bin / "tailscale").unlink()
        os.environ["PATH"] = str(self.bin)
        with self.assertRaisesRegex(ValidationError, "tailscale CLI not found"):
            control.run(["--port", str(self.port), "--share"])
        self.assertEqual(tailnet.state_line(self.port), [])
