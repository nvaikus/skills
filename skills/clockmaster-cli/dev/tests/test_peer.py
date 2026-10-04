"""Local-user gate (web/peer.py): /proc/net/tcp parsing on fake tables and the
server's verdicts with a patched owner lookup."""
import os
import shutil
import socket
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import base  # noqa: F401  (src/ on sys.path)
from test_tailnet import OWNER, ServerCase
from web import gate, peer

HEAD = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"


def hx(ip, port):
    raw = socket.inet_pton(socket.AF_INET6 if ":" in ip else socket.AF_INET, ip)
    words = struct.unpack(f"={len(raw) // 4}I", raw)
    return "".join(f"{w:08X}" for w in words) + f":{port:04X}"


def row(local, remote, uid, inode=12345, st="01"):
    return (f"   0: {hx(*local)} {hx(*remote)} {st} 00000000:00000000 00:00000000 00000000 "
            f"{uid:5d}        0 {inode} 1 0000000000000000 20 4 30 10 -1\n")


SERVER = ("127.0.0.1", 7788)
CLIENT = ("127.0.0.1", 51000)


class Parse(unittest.TestCase):
    def test_v4_little_endian_sample(self):
        # literal kernel line: 127.0.0.1:36517 listening, uid 1000
        text = HEAD + "   1: 0100007F:8EA5 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 15928 2 0 100 0 0 10 0\n"
        if sys.byteorder == "little":
            self.assertEqual(peer.parse(text), [(("127.0.0.1", 36517), ("0.0.0.0", 0), 1000, 15928)])

    def test_find_v4_client_row_not_server_row(self):
        rows = peer.parse(HEAD + row(SERVER, CLIENT, 1000) + row(CLIENT, SERVER, 1001) + "garbage\n")
        self.assertEqual(peer.find(rows, CLIENT, SERVER), 1001)
        self.assertIsNone(peer.find(rows, ("127.0.0.1", 51001), SERVER))

    def test_v6_and_mapped(self):
        v6c, v6s = ("::1", 40000), ("::1", 7788)
        mapped = ("::ffff:127.0.0.1", 51000)
        rows = peer.parse(HEAD + row(v6c, v6s, 1002) + row(mapped, ("::ffff:127.0.0.1", 7788), 1003))
        self.assertEqual(peer.find(rows, v6c, v6s), 1002)
        self.assertEqual(peer.find(rows, CLIENT, SERVER), 1003)  # mapped row, v4 query
        self.assertEqual(peer.find(rows, mapped, ("::ffff:127.0.0.1", 7788)), 1003)

    def test_orphan_row_untrusted(self):
        rows = peer.parse(HEAD + row(CLIENT, SERVER, 0, inode=0, st="06"))
        self.assertIsNone(peer.find(rows, CLIENT, SERVER))

    def test_lookup_reads_tables_and_tolerates_missing(self):
        t = tempfile.mkdtemp(prefix="cm-peer-")
        self.addCleanup(shutil.rmtree, t, True)
        d = Path(t) / "t"
        d.write_text(HEAD + row(CLIENT, SERVER, 1004), encoding="ascii")
        self.assertEqual(peer.lookup(CLIENT, SERVER, (str(d) + ".missing", str(d))), 1004)
        self.assertIsNone(peer.lookup(CLIENT, SERVER, (str(d) + ".missing",)))

    def test_check_verdicts(self):
        self.assertIsNone(peer.check(None))
        self.assertIsNone(peer.check(os.getuid()))
        self.assertIsNone(peer.check(0))
        self.assertIn("not the owner", peer.check(os.getuid() + 1))
        self.assertIn("could not tell", peer.check(peer.UNKNOWN))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux /proc")
    def test_real_socket_is_own_uid(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        c = socket.create_connection(srv.getsockname())
        try:
            self.assertEqual(peer.owner(c.getsockname(), srv.getsockname()), os.getuid())
        finally:
            c.close()
            srv.close()


class Server(ServerCase):
    def setUp(self):
        super().setUp()
        gate.allow(OWNER)
        self._owner = peer.owner
        self.uid = os.getuid()
        peer.owner = lambda client, server: self.uid

    def tearDown(self):
        peer.owner = self._owner
        super().tearDown()

    def test_own_uid_allowed(self):
        self.assertEqual(self.req(), 200)

    def test_foreign_uid_refused(self):
        self.uid = os.getuid() + 1
        self.assertEqual(self.req(), 403)
        self.assertEqual(self.req("POST", "/api/sync"), 403)

    def test_lookup_failure_refused(self):
        self.uid = peer.UNKNOWN
        self.assertEqual(self.req(), 403)

    def test_root_direct_allowed_and_proxy_gated(self):
        self.uid = 0
        self.assertEqual(self.req(), 200)
        h = {"Host": "box.example:8443", "X-Forwarded-For": "198.51.100.9"}
        self.assertEqual(self.req(headers=h), 403)
        self.assertEqual(self.req(headers={**h, gate.LOGIN: "other@example.com"}), 403)
        self.assertEqual(self.req(headers={**h, gate.LOGIN: OWNER}), 200)

    def test_off_linux_no_check(self):
        self.uid = None
        self.assertEqual(self.req(), 200)
