"""Contract tests with mocked HTTP. Run: python3 -m unittest discover -s dev/tests"""
import base64
import json
import os
import re
import shutil
import subprocess
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest import mock

from support import ROOT, TMP, make_profile, run  # noqa: E402  (sets the test environment first)

from src.api import auth, compose, google, mail  # noqa: E402
from src.core import http, profile  # noqa: E402
from src.core.errors import CliError  # noqa: E402


def enc(b):
    return base64.urlsafe_b64encode(b if isinstance(b, bytes) else b.encode()).decode().rstrip("=")


def part(mime, text=None, filename="", att=None, headers=()):
    p = {"mimeType": mime, "filename": filename, "headers": [{"name": n, "value": v} for n, v in headers],
         "body": {"size": len(text or "")}}
    if text is not None:
        p["body"]["data"] = enc(text)
    if att:
        p["body"] = {"attachmentId": att, "size": 5}
    return p


def msg(mid, tid, frm, subject, ts, text=None, htm=None, atts=(), labels=("INBOX",), to="me@x.com", q="",
        extra_headers=()):
    parts = []
    if text is not None:
        parts.append(part("text/plain", text, headers=[("Content-Type", "text/plain; charset=utf-8")]))
    if htm is not None:
        parts.append(part("text/html", htm))
    parts += list(atts)
    hdrs = [("From", frm), ("To", to), ("Subject", subject), ("Date", "x"),
            ("Message-ID", f"<{mid}@mail>")] + list(extra_headers)
    return {"id": mid, "threadId": tid, "internalDate": str(ts), "labelIds": list(labels),
            "snippet": (text or htm or "")[:50], "_q": f"{frm} {subject} {text or ''} {q}".lower(),
            "payload": {"mimeType": "multipart/mixed", "headers": [{"name": n, "value": v} for n, v in hdrs],
                        "parts": parts}}


class FakeGmail:
    """Routes by URL path; one mailbox per profile (the bearer token names it)."""

    def __init__(self):
        self.calls = []
        self.box = {"t": self._mailbox_t(), "w": self._mailbox_w()}
        self.disabled = set()

    def _mailbox_t(self):
        m = [msg("m1", "t1", "Anna <anna@x.com>", "Invoice March", 1_700_000_300_000,
                 "Hi, invoice attached.\n\nBest,\nAnna\n\nOn Mon, Mar 3, 2026 at 10:00 Bob <bob@x.com> wrote:\n> old stuff\n> more",
                 atts=[part("application/pdf", filename="invoice.pdf", att="ATT1",
                            headers=[("Content-Disposition", "attachment")]),
                       part("image/png", filename="logo.png", att="ATT2",
                            headers=[("Content-Disposition", "inline"), ("Content-ID", "<logo>")])]),
             msg("m2", "t1", "me@x.com", "Re: Invoice March", 1_700_000_400_000, "Thanks!\n-- \nMe\nCEO",
                 labels=("SENT",), to="anna@x.com"),
             msg("m3", "t3", "News <news@shop.com>", "Sale", 1_700_000_100_000,
                 htm="<html><style>p{}</style><p>Big <b>sale</b> <a href='https://shop.com/s'>here</a></p>"
                     "<blockquote>earlier mail</blockquote></html>", labels=("INBOX", "UNREAD", "CATEGORY_PROMOTIONS", "L1"))]
        return {"messages": {x["id"]: x for x in m},
                "labels": [{"id": "INBOX", "name": "INBOX", "type": "system"},
                           {"id": "UNREAD", "name": "UNREAD", "type": "system"},
                           {"id": "SENT", "name": "SENT", "type": "system"},
                           {"id": "STARRED", "name": "STARRED", "type": "system"},
                           {"id": "CATEGORY_PROMOTIONS", "name": "CATEGORY_PROMOTIONS", "type": "system"},
                           {"id": "L1", "name": "Shops", "type": "user"},
                           {"id": "L2", "name": "Shops/Old", "type": "user"}],
                "drafts": {}, "email": "me@x.com", "sent": []}

    def _mailbox_w(self):
        m = [msg("w1", "wt1", "Boss <boss@corp.com>", "Invoice review", 1_700_000_350_000, "Please review.",
                 to="me@corp.com")]
        return {"messages": {x["id"]: x for x in m}, "labels": [{"id": "INBOX", "name": "INBOX", "type": "system"}],
                "drafts": {}, "email": "me@corp.com", "sent": []}

    @staticmethod
    def err(status, reason="notFound", msg="Requested entity was not found."):
        return CliError(f"HTTP {status}", status=status, body={"error": {"message": msg, "errors": [{"reason": reason}]}})

    def view(self, m, fmt):
        out = {k: v for k, v in m.items() if not k.startswith("_")}
        if fmt == "minimal":
            out.pop("payload")
        elif fmt == "metadata":
            out["payload"] = {"headers": m["payload"]["headers"]}
        return out

    def threads(self, b):
        out = {}
        for m in sorted(b["messages"].values(), key=lambda x: int(x["internalDate"])):
            out.setdefault(m["threadId"], []).append(m)
        return out

    def __call__(self, method, url, params=None, body=None, headers=None, allow_mutate=False, data=None,
                 content_type=None, **kw):
        if method != "GET" and not allow_mutate:
            raise RuntimeError("transport rail")
        prof = headers["Authorization"].split("tok-")[1]
        self.calls.append((prof, method, url.split("users/me")[1], params, body))
        if prof in self.disabled:
            raise self.err(403, "accessNotConfigured", "Gmail API has not been used")
        b = self.box[prof]
        path = url.split("users/me", 1)[1]
        params = params or {}
        fmt = params.get("format", "full")
        if path == "/profile":
            return {"emailAddress": b["email"], "messagesTotal": len(b["messages"]), "threadsTotal": 2}
        if path == "/labels" and method == "GET":
            return {"labels": [dict(x) for x in b["labels"]]}
        if path == "/labels" and method == "POST":
            lb = {"id": f"L{len(b['labels']) + 10}", "name": body["name"], "type": "user"}
            b["labels"].append(lb)
            return lb
        lm = re.match(r"^/labels/(\w+)$", path)
        if lm:
            lb = next((x for x in b["labels"] if x["id"] == lm.group(1)), None)
            if not lb:
                raise self.err(404)
            if method == "PATCH":
                lb.update(body)
                return lb
            if method == "DELETE":
                b["labels"].remove(lb)
                return None
            n = [m for m in b["messages"].values() if lb["id"] in m["labelIds"]]
            return {**lb, "messagesTotal": len(n), "messagesUnread": sum("UNREAD" in m["labelIds"] for m in n),
                    "threadsTotal": len({m["threadId"] for m in n})}
        if path in ("/messages", "/threads") and method == "GET":
            q = (params.get("q") or "").lower().split()
            hits = [m for m in sorted(b["messages"].values(), key=lambda x: -int(x["internalDate"]))
                    if all(w in m["_q"] for w in q)]
            if path == "/threads":
                ids = list(dict.fromkeys(m["threadId"] for m in hits))
                return {"threads": [{"id": i} for i in ids[:params["maxResults"]]]}
            return {"messages": [{"id": m["id"], "threadId": m["threadId"]} for m in hits][:params["maxResults"]]}
        mm = re.match(r"^/messages/(\w+)(?:/(trash|untrash|attachments/(\w+)))?$", path)
        if mm and mm.group(1) not in ("batchModify", "send"):
            m = b["messages"].get(mm.group(1))
            if not m:
                raise self.err(404) if mm.group(1).startswith(("m", "w", "x")) else self.err(400, "invalidArgument", "Invalid id value")
            if mm.group(2) == "trash":
                m["labelIds"] = [x for x in m["labelIds"] if x != "INBOX"] + ["TRASH"]
                return self.view(m, "minimal")
            if mm.group(2) == "untrash":
                m["labelIds"] = [x for x in m["labelIds"] if x != "TRASH"]
                return self.view(m, "minimal")
            if mm.group(3):
                return {"data": enc(f"data-{mm.group(3)}"), "size": 9}
            return self.view(m, fmt)
        tm = re.match(r"^/threads/(\w+)$", path)
        if tm:
            t = self.threads(b).get(tm.group(1))
            if not t:
                raise self.err(404)
            return {"id": tm.group(1), "messages": [self.view(m, fmt) for m in t]}
        if path == "/messages/batchModify":
            for i in body["ids"]:
                m = b["messages"][i]
                m["labelIds"] = [x for x in m["labelIds"] if x not in body["removeLabelIds"]] + \
                    [x for x in body["addLabelIds"] if x not in m["labelIds"]]
            return None
        if path == "/drafts" and method == "POST":
            did = f"r{len(b['drafts']) + 1}"
            b["drafts"][did] = {"raw": body["message"]["raw"], "threadId": body["message"].get("threadId")}
            return {"id": did, "message": {"id": f"dm{did}", "threadId": body["message"].get("threadId") or "nt"}}
        if path == "/drafts" and method == "GET":
            return {"drafts": [{"id": d} for d in b["drafts"]]}
        if path == "/drafts/send":
            d = b["drafts"].pop(body["id"])
            b["sent"].append(d)
            return {"id": "sent1", "threadId": d["threadId"] or "nt", "labelIds": ["SENT"]}
        dm = re.match(r"^/drafts/(\w+)$", path)
        if dm:
            d = b["drafts"].get(dm.group(1))
            if not d:
                raise self.err(404)
            if method == "DELETE":
                del b["drafts"][dm.group(1)]
                return None
            if method == "PUT":
                d.update(raw=body["message"]["raw"], threadId=body["message"].get("threadId"))
                return {"id": dm.group(1), "message": {"id": "dm2", "threadId": d["threadId"]}}
            if fmt == "raw":
                return {"id": dm.group(1), "message": {"id": "dm1", "threadId": d["threadId"], "raw": d["raw"]}}
            return {"id": dm.group(1), "message": self.from_raw(d)}
        if path == "/messages/send":
            b["sent"].append(body)
            return {"id": "sent2", "threadId": body.get("threadId") or "nt"}
        raise AssertionError(f"unrouted {method} {path}")

    @staticmethod
    def from_raw(d):
        e = BytesParser(policy=policy.SMTP).parsebytes(base64.urlsafe_b64decode(d["raw"] + "=" * (-len(d["raw"]) % 4)))
        body = e.get_body(preferencelist=("plain",))
        parts = [part("text/plain", body.get_content())] if body else []
        for a in e.iter_attachments():
            parts.append(part(a.get_content_type(), filename=a.get_filename(), att="A",
                              headers=[("Content-Disposition", "attachment")]))
        return {"id": "dm1", "threadId": d["threadId"], "internalDate": "1700000500000", "labelIds": ["DRAFT"],
                "snippet": "", "payload": {"mimeType": "multipart/mixed", "parts": parts,
                                           "headers": [{"name": k, "value": str(v)} for k, v in e.items()]}}


def raw_of(d):
    return BytesParser(policy=policy.SMTP).parsebytes(base64.urlsafe_b64decode(d["raw"] + "=" * (-len(d["raw"]) % 4)))


class Base(unittest.TestCase):
    def setUp(self):
        self.g = FakeGmail()
        p1 = mock.patch.object(http, "request", self.g)
        p2 = mock.patch.object(auth, "access_token", lambda prof: f"tok-{prof}")
        p1.start(), p2.start()
        self.addCleanup(p1.stop), self.addCleanup(p2.stop)
        mail._labels.clear()
        compose._me.clear()
        google._pacers.clear()  # a fresh quota bucket: no test waits on units an earlier one spent
        for n in profile.names():
            if n not in ("t",):
                shutil.rmtree(f"{TMP}/root/{n}")
        cfg = Path(f"{TMP}/root/config.json")
        if cfg.exists():
            cfg.unlink()

    def two(self):
        make_profile("w", account={"email": "me@corp.com"})
        Path(f"{TMP}/root/config.json").write_text(json.dumps({"default_profile": "t"}))

    def tsv(self, out):
        lines = out.strip("\n").split("\n")
        head = lines[0].split("\t")
        return [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]


class TestSearchRead(Base):
    def test_search_columns_and_json(self):
        rc, out, err = run("search", "invoice")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertEqual(list(rows[0]), ["profile", "id", "thread_id", "date", "from", "subject", "labels", "snippet"])
        self.assertEqual([r["id"] for r in rows], ["m2", "m1"])
        rc, out, _ = run("search", "sale", "-j")
        data = json.loads(out)
        self.assertEqual(data[0]["labels"], "INBOX,UNREAD,PROMOTIONS,Shops")
        rc, out, _ = run("search", "sale", "--fields", "id,subject", "--no-header")
        self.assertEqual(out, "m3\tSale\n")

    def test_search_merges_profiles_by_date(self):
        self.two()
        rc, out, err = run("search", "invoice")
        self.assertEqual(rc, 0, err)
        self.assertEqual([(r["profile"], r["id"]) for r in self.tsv(out)], [("t", "m2"), ("w", "w1"), ("t", "m1")])
        rc, out, _ = run("search", "invoice", "--limit", "1")
        self.assertEqual(len(self.tsv(out)), 1)
        rc, out, _ = run("--profile", "w", "search", "invoice")
        self.assertEqual([r["id"] for r in self.tsv(out)], ["w1"])

    def test_search_skips_broken_profile(self):
        self.two()
        self.g.disabled.add("w")
        rc, out, err = run("search", "invoice")
        self.assertEqual(rc, 0)
        self.assertIn("# profile w skipped", err)
        self.assertEqual(len(self.tsv(out)), 2)

    def test_search_threads(self):
        rc, out, _ = run("search", "invoice", "--threads", "-j")
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["count"], 2)
        self.assertEqual(data[0]["subject"], "Invoice March")

    def test_read_thread_strips_quotes_and_signature(self):
        rc, out, err = run("read", "m1")
        self.assertEqual(rc, 0, err)
        self.assertIn("# Invoice March", out)
        self.assertIn("Hi, invoice attached.", out)
        self.assertNotIn("old stuff", out)
        self.assertIn("Thanks!", out)
        self.assertNotIn("CEO", out)
        self.assertIn("1. invoice.pdf", out)
        self.assertIn("+1 inline image", out)
        rc, out, _ = run("read", "t1", "--full")
        self.assertIn("old stuff", out)
        self.assertIn("CEO", out)

    def test_read_message_html(self):
        rc, out, err = run("read", "m3", "--message")
        self.assertEqual(rc, 0, err)
        self.assertIn("Big sale [here](https://shop.com/s)", out)
        self.assertNotIn("p{}", out)
        self.assertNotIn("earlier mail", out)
        rc, out, _ = run("read", "m3", "-j")
        self.assertEqual(json.loads(out)["profile"], "t")

    def test_read_locates_profile(self):
        self.two()
        rc, out, err = run("read", "w1")
        self.assertEqual(rc, 0, err)
        self.assertIn("profile: w", out)
        rc, _, err = run("read", "x404")
        self.assertEqual(rc, 2)
        self.assertIn("not found in any profile", err)

    def test_read_max(self):
        rc, out, _ = run("read", "m1", "--message", "--max", "5")
        self.assertIn("more chars: gmail read m1 --message --max 0", out)

    def test_attachments(self):
        rc, out, _ = run("attachment", "list", "m1")
        self.assertEqual([r["name"] for r in self.tsv(out)], ["invoice.pdf", "logo.png"])
        rc, out, err = run("attachment", "get", "m1", "invoice.pdf")
        self.assertEqual(rc, 0, err)
        path = self.tsv(out)[0]["path"]
        self.assertEqual(Path(path).read_bytes(), b"data-ATT1")
        dest = f"{TMP}/one.pdf"
        rc, out, _ = run("attachment", "get", "m1", "1", "-o", dest)
        self.assertEqual(Path(dest).read_bytes(), b"data-ATT1")
        rc, out, _ = run("attachment", "get", "m1", "all", "-o", f"{TMP}/all/")
        self.assertEqual(len(self.tsv(out)), 1)  # the inline logo is skipped
        rc, _, err = run("attachment", "get", "m1", "9")
        self.assertEqual(rc, 2)
        self.assertIn("1. invoice.pdf", err)


class TestOrganize(Base):
    def labels_of(self, mid, prof="t"):
        return self.g.box[prof]["messages"][mid]["labelIds"]

    def test_archive_star_read(self):
        rc, out, err = run("archive", "m1")
        self.assertEqual(rc, 0, err)
        self.assertNotIn("INBOX", self.labels_of("m1"))
        self.assertEqual(self.tsv(out)[0], {"profile": "t", "action": "archive", "matched": "1", "changed": "1"})
        run("star", "m3")
        run("mark-read", "m3")
        self.assertIn("STARRED", self.labels_of("m3"))
        self.assertNotIn("UNREAD", self.labels_of("m3"))

    def test_thread_widening(self):
        run("archive", "m1", "--threads")
        self.assertNotIn("INBOX", self.labels_of("m1"))
        batch = [c for c in self.g.calls if c[2] == "/messages/batchModify"][0]
        self.assertEqual(sorted(batch[4]["ids"]), ["m1", "m2"])
        self.g.calls.clear()
        run("mark-unread", "t1")  # a thread id without --threads = its messages
        batch = [c for c in self.g.calls if c[2] == "/messages/batchModify"][0]
        self.assertEqual(sorted(batch[4]["ids"]), ["m1", "m2"])

    def test_modify_query_and_dry_run(self):
        rc, out, err = run("modify", "-q", "invoice", "--add", "shops", "--remove", "INBOX", "--dry-run")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.tsv(out)[0]["matched"], "2")
        self.assertEqual(self.tsv(out)[0]["changed"], "0")
        self.assertIn("dry run", err)
        self.assertFalse([c for c in self.g.calls if c[1] != "GET"])
        rc, out, _ = run("modify", "-q", "invoice", "--add", "shops")
        self.assertIn("L1", self.labels_of("m1"))
        rc, _, err = run("modify", "m1", "--add", "Nope")
        self.assertEqual(rc, 2)
        self.assertIn("no label 'Nope'", err)
        rc, _, err = run("modify", "m1")
        self.assertEqual(rc, 2)

    def test_batch_chunks(self):
        with mock.patch.object(mail.google, "mutate") as mut:
            mail.batch_modify("t", [f"x{i}" for i in range(2500)], ["A"])
        self.assertEqual([len(c.args[3]["ids"]) for c in mut.call_args_list], [1000, 1000, 500])

    def test_trash_untrash(self):
        rc, out, err = run("trash", "m3")
        self.assertEqual(rc, 0, err)
        self.assertIn("TRASH", self.labels_of("m3"))
        run("untrash", "m3")
        self.assertNotIn("TRASH", self.labels_of("m3"))

    def test_query_uses_default_with_note(self):
        self.two()
        rc, out, err = run("archive", "-q", "invoice")
        self.assertEqual(rc, 0, err)
        self.assertIn("profile t (default)", err)
        rc, out, _ = run("archive", "w1")  # an id finds its own account
        self.assertEqual(self.tsv(out)[0]["profile"], "w")
        self.assertNotIn("INBOX", self.labels_of("w1", "w"))


class TestLabels(Base):
    def test_list_counts(self):
        rc, out, err = run("label", "list", "--user", "--counts")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertEqual([r["name"] for r in rows], ["Shops", "Shops/Old"])
        self.assertEqual(rows[0]["messages"], "1")

    def test_create_parents(self):
        rc, out, err = run("label", "create", "Clients/Acme/2026")
        self.assertEqual(rc, 0, err)
        self.assertEqual([r["name"] for r in self.tsv(out)], ["Clients", "Clients/Acme", "Clients/Acme/2026"])
        rc, out, err = run("label", "create", "Clients")
        self.assertIn("already exists", err)

    def test_rename_children(self):
        rc, out, err = run("label", "rename", "shops", "Stores")
        self.assertEqual(rc, 0, err)
        names = {x["name"] for x in self.g.box["t"]["labels"]}
        self.assertTrue({"Stores", "Stores/Old"} <= names)
        rc, _, err = run("label", "rename", "INBOX", "X")
        self.assertEqual(rc, 2)

    def test_delete(self):
        rc, out, err = run("label", "delete", "Shops/Old")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "Shops/Old\tL2\n")


class TestDrafts(Base):
    def test_create_show_send(self):
        rc, out, err = run("draft", "create", "--to", "Anna <anna@x.com>", "--subject", "Hi", "--body", "-",
                           "--md", "--attach", str(Path(__file__)), stdin="**bold** text\n\n- a\n- b\n")
        self.assertEqual(rc, 0, err)
        did = out.split("\t")[1]
        e = raw_of(self.g.box["t"]["drafts"][did])
        self.assertEqual(e["To"], "Anna <anna@x.com>")
        self.assertIn("<b>bold</b>", e.get_body(preferencelist=("html",)).get_content())
        self.assertEqual([a.get_filename() for a in e.iter_attachments()], ["test_cli.py"])
        rc, out, err = run("draft", "show", did)
        self.assertEqual(rc, 0, err)
        self.assertIn("**bold** text", out)
        self.assertIn("test_cli.py", out)
        rc, out, _ = run("draft", "list")
        self.assertEqual(self.tsv(out)[0]["subject"], "Hi")
        rc, out, err = run("draft", "send", did)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.split("\t")[1], "sent1")
        self.assertFalse(self.g.box["t"]["drafts"])

    def test_unknown_field_after_change_is_a_note(self):
        # the draft exists once create returns: a bad --fields must not turn that into an error exit
        rc, out, err = run("draft", "create", "--to", "a@x.com", "--body", "x", "--fields", "id,draft_id", "--no-header")
        self.assertEqual(rc, 0, err)
        self.assertIn("unknown field(s) id ignored", err)
        self.assertEqual(out.strip(), "r1")

    def test_reply_headers(self):
        rc, out, err = run("draft", "create", "--reply-to", "m1", "--reply-all", "--body", "ok")
        self.assertEqual(rc, 0, err)
        d = list(self.g.box["t"]["drafts"].values())[0]
        e = raw_of(d)
        self.assertEqual(d["threadId"], "t1")
        self.assertEqual(e["Subject"], "Re: Invoice March")
        self.assertEqual(e["In-Reply-To"], "<m1@mail>")
        self.assertEqual(e["To"], "Anna <anna@x.com>")
        self.assertIsNone(e["Cc"])  # the only other recipient is me

    def test_reply_to_own_message_goes_to_its_recipients(self):
        run("draft", "create", "--reply-to", "m2", "--body", "ping")
        e = raw_of(list(self.g.box["t"]["drafts"].values())[0])
        self.assertEqual(e["To"], "anna@x.com")
        self.assertEqual(e["Subject"], "Re: Invoice March")

    def test_edit_keeps_rest(self):
        run("draft", "create", "--to", "a@x.com", "--subject", "S", "--body", "one", "--attach", str(Path(__file__)))
        rc, out, err = run("draft", "edit", "r1", "--subject", "S2", "--drop-attach", "1", "--cc", "c@x.com")
        self.assertEqual(rc, 0, err)
        e = raw_of(self.g.box["t"]["drafts"]["r1"])
        self.assertEqual((e["Subject"], e["To"], e["Cc"]), ("S2", "a@x.com", "c@x.com"))
        self.assertEqual(e.get_body(preferencelist=("plain",)).get_content().strip(), "one")
        self.assertEqual(list(e.iter_attachments()), [])

    def test_send_now_and_delete(self):
        rc, out, err = run("send", "--to", "a@x.com", "--subject", "S", "--body", "b")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self.g.box["t"]["sent"]), 1)
        run("draft", "create", "--to", "a@x.com", "--body", "x")
        rc, out, err = run("draft", "delete", "r1")
        self.assertEqual(rc, 0, err)
        self.assertFalse(self.g.box["t"]["drafts"])
        rc, _, err = run("send", "--subject", "S", "--body", "b")
        self.assertEqual(rc, 2)
        self.assertIn("no recipient", err)

    def test_draft_needs_default_with_two_profiles(self):
        make_profile("w")
        rc, _, err = run("draft", "create", "--to", "a@x.com", "--body", "x")
        self.assertEqual(rc, 2)
        self.assertIn("which account", err)

    def test_large_message_uses_upload(self):
        big = Path(TMP) / "big.bin"
        big.write_bytes(os.urandom(compose.RAW_LIMIT))
        with mock.patch.object(compose.google, "mutate", return_value={"id": "r9", "message": {}}) as mut:
            run("draft", "create", "--to", "a@x.com", "--body", "x", "--attach", str(big))
        kw = mut.call_args.kwargs
        self.assertEqual(kw["base"], compose.google.UPLOAD)
        self.assertTrue(kw["content_type"].startswith("multipart/related"))


class TestContract(Base):
    def test_rail_grep(self):
        out = subprocess.run(["grep", "-rn", "allow_mutate", str(ROOT / "src" / "commands")],
                             capture_output=True, text=True).stdout
        self.assertEqual(out, "")

    def test_commands_never_speak_http(self):
        out = subprocess.run(["grep", "-rnE", r"google\.(get|mutate)|http\.request", str(ROOT / "src" / "commands")],
                             capture_output=True, text=True).stdout
        self.assertEqual(out, "")

    def test_help_and_unknown(self):
        self.assertEqual(run("--help")[0], 0)
        self.assertEqual(run()[0], 2)
        rc, _, err = run("serch")
        self.assertEqual(rc, 2)
        self.assertIn("search", err)
        self.assertEqual(run("label")[0], 2)

    def test_every_command_help(self):
        from src import registry
        for name in registry.COMMANDS:
            with self.assertRaises(SystemExit) as cm:
                run(*name.split(), "-h")
            self.assertEqual(cm.exception.code, 0, name)

    def test_unknown_profile(self):
        rc, _, err = run("--profile", "zz", "search", "x")
        self.assertEqual(rc, 2)
        self.assertIn("gmail onboard --profile zz", err)

    def test_api_disabled_message(self):
        self.g.disabled.add("t")
        rc, _, err = run("read", "m1", "--profile", "t")
        self.assertEqual(rc, 2)
        self.assertIn("Gmail API is off", err)

    def test_profiles_and_whoami(self):
        self.two()
        rc, out, _ = run("profiles")
        rows = self.tsv(out)
        self.assertEqual([(r["profile"], r["default"]) for r in rows], [("t", "yes"), ("w", "no")])
        rc, out, _ = run("whoami")
        self.assertEqual([r["email"] for r in self.tsv(out)], ["me@x.com", "me@corp.com"])
        rc, out, _ = run("profiles", "--default", "w")
        self.assertEqual(self.tsv(out)[1]["default"], "yes")


if __name__ == "__main__":
    unittest.main()


class TestTransport(unittest.TestCase):
    def test_one_tls_context_per_process(self):
        # urlopen without context= re-reads the CA bundle per call: 45 s CPU on a 9-profile search
        seen = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        def fake(req, timeout=None, context=None):
            seen.append(context)
            return Resp()
        with mock.patch("urllib.request.urlopen", fake):
            for _ in range(3):
                http.request("GET", "https://example.invalid/x")
        self.assertIsNotNone(seen[0])
        self.assertEqual(len({id(c) for c in seen}), 1)
