"""Index layer: extractors (Office fixtures built in-test), path mapping, manifest logic (md5 cache,
moves, deletes, change cursor), service units, and the index commands - against a FakeProvider."""
import io
import json
import os
import plistlib
import shutil
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from support import TMP, run  # noqa: E402  (sets the test environment first)

from src.api import extract, indexer, providers, service  # noqa: E402
from src.api.manifest import Manifest  # noqa: E402
from src.api.provider import Provider, Transient  # noqa: E402
from src.core import config, profile  # noqa: E402
from src.core.errors import CliError, UsageError  # noqa: E402

DOCX_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OFF_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def make_docx():
    p = lambda t, style=None, num=False: (  # noqa: E731
        "<w:p><w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "")
        + ("<w:numPr><w:ilvl w:val=\"0\"/></w:numPr>" if num else "") + f"</w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>")
    body = (p("Smeta", "Heading1") + p("Pool ") + "<w:p><w:r><w:t>tiles</w:t><w:tab/><w:t>blue</w:t></w:r></w:p>"
            + p("pump", num=True) + "<w:tbl><w:tr><w:tc>" + p("Item") + "</w:tc><w:tc>" + p("Qty")
            + "</w:tc></w:tr></w:tbl>")
    return _zip({"word/document.xml": f'<w:document {DOCX_NS}><w:body>{body}</w:body></w:document>'})


def make_xlsx():
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    wb = (f'<workbook {ns} xmlns:r="{OFF_REL}"><sheets><sheet name="Budget" sheetId="1" r:id="rId1"/>'
          f'<sheet name="Q 2" sheetId="2" r:id="rId2"/></sheets></workbook>')
    rels = (f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="x" Target="/xl/worksheets/sheet2.xml"/></Relationships>')
    sst = f'<sst {ns}><si><t>Tiles</t></si><si><r><t>Pu</t></r><r><t>mp</t></r></si></sst>'
    s1 = (f'<worksheet {ns}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1"><v>42</v></c></row>'
          f'<row r="2"><c r="B2" t="inlineStr"><is><t>inline, text</t></is></c><c r="C2" t="b"><v>1</v></c></row>'
          f'</sheetData></worksheet>')
    s2 = f'<worksheet {ns}><sheetData><row r="1"><c r="A1" t="s"><v>1</v></c></row></sheetData></worksheet>'
    return _zip({"xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": rels, "xl/sharedStrings.xml": sst,
                 "xl/worksheets/sheet1.xml": s1, "xl/worksheets/sheet2.xml": s2})


def make_pptx():
    a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    pns = f'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="{OFF_REL}"'
    pres = f'<p:presentation {pns}><p:sldIdLst><p:sldId id="1" r:id="rB"/><p:sldId id="2" r:id="rA"/></p:sldIdLst></p:presentation>'
    rels = (f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rA" Type="x/slide" Target="slides/slide1.xml"/>'
            f'<Relationship Id="rB" Type="x/slide" Target="slides/slide2.xml"/></Relationships>')
    slide = lambda t: f'<p:sld {pns} {a}><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:sld>'  # noqa: E731
    srels = (f'<Relationships xmlns="{PKG_REL}"><Relationship Id="n1" Type="x/notesSlide" '
             f'Target="../notesSlides/notesSlide1.xml"/></Relationships>')
    return _zip({"ppt/presentation.xml": pres, "ppt/_rels/presentation.xml.rels": rels,
                 "ppt/slides/slide1.xml": slide("Second slide"), "ppt/slides/slide2.xml": slide("First slide"),
                 "ppt/slides/_rels/slide2.xml.rels": srels,
                 "ppt/notesSlides/notesSlide1.xml": slide("Say hello")})


# ---- fake provider -------------------------------------------------------------------------

ROOT_ID = "ROOT"
DOCX = extract.DOCX


class FakeProvider(Provider):
    name = "fake"

    def __init__(self):
        self.items, self.blobs, self.exports = {}, {}, {}
        self.log, self.calls = [], {"fetch": 0, "export": 0, "ocr": 0, "list": 0}
        self.fail = {}  # id -> exception to raise on fetch
        self.scope = "fake:1"

    # test helpers
    def put(self, i, name, parent=ROOT_ID, folder=False, data=b"", mime="text/plain", native=False, ext=""):
        it = {"id": i, "parent": parent, "name": name, "mime": "folder" if folder else mime, "folder": int(folder),
              "native": int(native), "ext": ext, "size": len(data), "md5": None if native or folder else str(hash(data)),
              "modified": f"t{len(self.log)}"}
        it["key"] = it["md5"] or it["modified"]
        self.items[i] = it
        self.blobs[i] = data
        self.log.append(("up", dict(it)))
        return it

    def drop(self, i):
        self.items.pop(i)
        self.log.append(("gone", i))

    # Provider
    def scope_key(self):
        return self.scope

    def root_id(self):
        return ROOT_ID

    def address(self, rel):
        return "/" + rel

    def resolve(self, address):
        for i, it in self.items.items():
            if it["name"] == address.rsplit("/", 1)[-1]:
                return i
        raise UsageError("not found")

    def start_cursor(self):
        return str(len(self.log))

    def list_all(self):
        self.calls["list"] += 1
        yield [dict(v) for v in self.items.values()]

    def changes(self, cursor):
        start = int(cursor)
        ups, gone = [], []
        for kind, x in self.log[start:]:
            (ups if kind == "up" else gone).append(x)
        yield ups, gone, str(len(self.log))

    def get(self, i):
        return dict(self.items[i]) if i in self.items else None

    def list_children(self, fid):
        return [dict(v) for v in self.items.values() if v["parent"] == fid]

    def fetch(self, it, dest):
        self.calls["fetch"] += 1
        if it["id"] in self.fail:
            raise self.fail[it["id"]]
        Path(dest).write_bytes(self.blobs[it["id"]])

    def export_text(self, it, tmp):
        self.calls["export"] += 1
        return self.exports.get(it["id"], "exported text"), "fake-export"

    def ocr_text(self, it, tmp):
        self.calls["ocr"] += 1
        return "recognized text"


class Extract(unittest.TestCase):
    def tmpfile(self, data, name):
        p = Path(TMP) / name
        p.write_bytes(data)
        return p

    def test_docx(self):
        text = extract.docx(self.tmpfile(make_docx(), "a.docx"))
        self.assertEqual(text, "# Smeta\nPool \ntiles\tblue\n- pump\n| Item | Qty |\n")

    def test_xlsx(self):
        text = extract.xlsx(self.tmpfile(make_xlsx(), "a.xlsx"))
        self.assertEqual(text, '## Sheet: Budget\nTiles,,42\n,"inline, text",TRUE\n\n## Sheet: Q 2\nPump\n\n')

    def test_pptx_order_and_notes(self):
        text = extract.pptx(self.tmpfile(make_pptx(), "a.pptx"))
        self.assertEqual(text, "## Slide 1\nFirst slide\nNotes: Say hello\n\n## Slide 2\nSecond slide\n")

    def test_broken_office_is_value_error(self):
        with self.assertRaises(ValueError):
            extract.office("docx", self.tmpfile(b"not a zip", "bad.docx"))

    def test_kind_and_text(self):
        self.assertEqual(extract.kind(DOCX, "x"), "docx")
        self.assertEqual(extract.kind("application/octet-stream", "notes.MD"), "text")
        self.assertEqual(extract.kind("image/png", "a.png"), "image")
        self.assertIsNone(extract.kind("video/mp4", "a.mp4"))
        self.assertEqual(extract.text(self.tmpfile("привет".encode("cp1251"), "c.txt")), "привет")
        self.assertIsNone(extract.text(self.tmpfile(b"\x00\x01bin", "b.txt")))
        self.assertIn("1.5K", extract.meta_line("a.mp4", "video/mp4", 1536))

    def test_pdf_without_pdftotext(self):
        with mock.patch.object(extract.shutil, "which", lambda n: None):
            self.assertIsNone(extract.pdf(self.tmpfile(b"%PDF", "a.pdf")))
        self.assertFalse(extract.meaningful("\f\f  \n"))


class Paths(unittest.TestCase):
    def test_compute_paths(self):
        rows = [
            {"id": "F", "parent": ROOT_ID, "name": "Clients", "folder": 1, "ext": ""},
            {"id": "a", "parent": "F", "name": "smeta.xlsx", "folder": 0, "ext": ""},
            {"id": "d1", "parent": "F", "name": "Notes", "folder": 0, "ext": ".docx"},
            {"id": "d2", "parent": "F", "name": "notes.docx", "folder": 0, "ext": ""},  # same name ignoring case
            {"id": "s", "parent": "F", "name": "a/b", "folder": 0, "ext": ""},
            {"id": "form", "parent": "F", "name": "Survey", "folder": 0, "ext": None},  # not shown by the mount
            {"id": "out", "parent": "ELSEWHERE", "name": "x", "folder": 0, "ext": ""},
        ]
        got = indexer.compute_paths(rows, ROOT_ID)
        self.assertEqual(got["a"], "Clients/smeta.xlsx")
        self.assertEqual(got["d1"], "Clients/Notes.docx@d1")
        self.assertEqual(got["d2"], "Clients/notes.docx@d2")
        self.assertEqual(got["s"], "Clients/a／b")
        self.assertIsNone(got["form"])
        self.assertIsNone(got["out"])

    def test_header_roundtrip_and_rel(self):
        row = {"id": "x1", "md5": "m", "modified": "2026", "path": "A/b.txt"}
        head, body = indexer.parse(indexer.render(row, "/A/b.txt", "text", "hello\n---\nworld"))
        self.assertEqual((head["id"], head["path"], head["address"], head["extractor"]), ("x1", "A/b.txt", "/A/b.txt", "text"))
        self.assertEqual(body, "hello\n---\nworld")
        self.assertEqual(indexer.rel_of_md("/i", "/i/A/b.txt.md"), "A/b.txt")


class IndexCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(TMP) / f"idx-{self._testMethodName}"
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir()
        self.idx = self.dir / "index"
        self.man = Manifest(self.dir / "index.sqlite")
        self.addCleanup(self.man.close)
        self.p = FakeProvider()
        self.cfg = dict(config.DEFAULTS)

    def update(self):
        return indexer.update(self.p, self.man, self.idx, self.cfg)

    def md(self, rel):
        return (self.idx / (rel + ".md")).read_text(encoding="utf-8")


class Update(IndexCase):
    def seed(self):
        self.p.put("F", "Clients", folder=True)
        self.p.put("G", "Ivanov", parent="F", folder=True)
        self.p.put("x", "smeta.xlsx", parent="G", data=make_xlsx(), mime=extract.XLSX)
        self.p.put("t", "readme.txt", data=b"pool pump manual")
        self.p.put("gd", "Plan", native=True, mime="application/vnd.google-apps.document", ext=".docx")
        self.p.put("v", "clip.mp4", data=b"\x00" * 10, mime="video/mp4")

    def test_full_build_then_cache_hit(self):
        self.seed()
        got = self.update()
        self.assertTrue(got["finished"])
        self.assertEqual((got["sync"], got["extracted"], got["files"], got["pending"]), ("full", 4, 4, 0))
        self.assertIn("Tiles,,42", self.md("Clients/Ivanov/smeta.xlsx"))
        head, _ = indexer.parse(self.md("Clients/Ivanov/smeta.xlsx"))
        self.assertEqual((head["id"], head["path"], head["extractor"]), ("x", "Clients/Ivanov/smeta.xlsx", "xlsx"))
        self.assertIn("exported text", self.md("Plan.docx"))
        self.assertIn("clip.mp4 · video/mp4", self.md("clip.mp4"))
        self.assertEqual(self.p.calls["fetch"], 2)  # the video is never downloaded
        self.assertEqual(self.man.meta("cursor"), str(len(self.p.log)))
        got = self.update()  # nothing changed: md5 cache hit, no download, changes feed only
        self.assertEqual((got["sync"], got["extracted"]), ("changes", 0))
        self.assertEqual((self.p.calls["fetch"], self.p.calls["export"], self.p.calls["list"]), (2, 1, 1))
        self.assertFalse(list(self.dir.rglob("orig-*")))

    def test_changed_md5_reextracts(self):
        self.seed()
        self.update()
        self.p.put("t", "readme.txt", data=b"new heater text")
        got = self.update()
        self.assertEqual((got["extracted"], self.p.calls["fetch"]), (1, 3))
        self.assertIn("new heater text", self.md("readme.txt"))

    def test_rename_and_folder_move_only_move_texts(self):
        self.seed()
        self.update()
        self.p.put("t", "manual.txt", data=b"pool pump manual")   # rename, same content
        self.p.put("G", "Petrov", parent="F", folder=True)          # folder rename moves its subtree
        got = self.update()
        self.assertEqual((got["extracted"], got["moved"], self.p.calls["fetch"]), (0, 2, 2))
        self.assertFalse((self.idx / "readme.txt.md").exists())
        self.assertIn("pool pump manual", self.md("manual.txt"))
        head, _ = indexer.parse(self.md("Clients/Petrov/smeta.xlsx"))
        self.assertEqual(head["path"], "Clients/Petrov/smeta.xlsx")
        self.assertFalse((self.idx / "Clients" / "Ivanov").exists())  # empty dir pruned

    def test_delete_trash_and_out_of_scope(self):
        self.seed()
        self.update()
        self.p.drop("t")
        self.p.drop("F")  # a trashed folder: its subtree leaves the scope
        got = self.update()
        self.assertFalse((self.idx / "readme.txt.md").exists())
        self.assertFalse((self.idx / "Clients").exists())
        self.assertEqual(got["files"], 2)

    def test_duplicate_arrival_renames_both(self):
        self.seed()
        self.update()
        self.p.put("t2", "README.TXT", data=b"other")
        self.update()
        self.assertIn("pool pump manual", self.md("readme.txt@t"))
        self.assertIn("other", self.md("README.TXT@t2"))
        self.assertFalse((self.idx / "readme.txt.md").exists())

    def test_move_into_scope_needs_no_subtree_walk(self):
        self.p.put("OUT", "Archive", parent="ELSEWHERE", folder=True)
        self.p.put("o1", "old.txt", parent="OUT", data=b"archived")
        self.update()
        self.assertEqual(self.man.counts()["files"], 0)
        self.p.put("OUT", "Archive", parent=ROOT_ID, folder=True)  # only the folder changes
        self.update()
        self.assertIn("archived", self.md("Archive/old.txt"))

    def test_transient_retries_permanent_recorded(self):
        self.p.put("a", "a.txt", data=b"aaa")
        self.p.put("b", "b.txt", data=b"bbb")
        self.p.fail = {"a": Transient("503"), "b": CliError("HTTP 403: cannotDownloadFile", status=403)}
        got = self.update()
        self.assertEqual((got["retry"], got["failed"], got["pending"]), (1, 1, 1))
        self.assertIn("text not indexed: HTTP 403", self.md("b.txt"))
        self.p.fail = {}
        got = self.update()
        self.assertEqual((got["extracted"], got["pending"]), (1, 0))  # a retried; b not retried (same md5)
        self.assertEqual(self.p.calls["fetch"], 3)

    def test_pdf_falls_back_to_ocr(self):
        self.p.put("p", "scan.pdf", data=b"%PDF-1.4", mime=extract.PDF)
        with mock.patch.object(extract, "pdf", lambda path: None):
            self.update()
        self.assertIn("recognized text", self.md("scan.pdf"))
        self.assertEqual(indexer.parse(self.md("scan.pdf"))[0]["extractor"], "ocr")
        self.cfg["ocr"] = "off"
        self.p.put("p", "scan.pdf", data=b"%PDF-1.5", mime=extract.PDF)
        with mock.patch.object(extract, "pdf", lambda path: ""):
            self.update()
        self.assertIn("text not indexed: scanned PDF", self.md("scan.pdf"))

    def test_big_image_skips_ocr(self):
        self.p.put("i", "big.jpg", data=b"x", mime="image/jpeg")
        with mock.patch.object(indexer, "IMAGE_OCR_MAX", 0):
            got = self.update()
        self.assertEqual((got["failed"], self.p.calls["ocr"]), (0, 0))
        self.assertIn("text not indexed: image above Drive OCR limit", self.md("big.jpg"))

    def test_scope_change_rebuilds(self):
        self.seed()
        self.update()
        self.p.scope = "fake:2"
        got = self.update()
        self.assertEqual((got["sync"], self.p.calls["list"]), ("full", 2))

    def test_update_item_force(self):
        self.seed()
        self.update()
        rows = indexer.update_item(self.p, self.man, self.idx, self.cfg, "t", force=False)
        self.assertEqual(rows, [{"id": "t", "path": "readme.txt", "status": "current"}])
        rows = indexer.update_item(self.p, self.man, self.idx, self.cfg, "t", force=True)
        self.assertEqual(rows[0]["status"], "indexed")
        rows = indexer.update_item(self.p, self.man, self.idx, self.cfg, "F", force=False)
        self.assertEqual([r["path"] for r in rows], ["Clients/Ivanov/smeta.xlsx"])
        self.p.items.pop("t")
        rows = indexer.update_item(self.p, self.man, self.idx, self.cfg, "t", force=False)
        self.assertEqual(rows[0]["status"], "removed")
        self.assertFalse((self.idx / "readme.txt.md").exists())

    def test_update_item_needs_a_build(self):
        with self.assertRaises(UsageError):
            indexer.update_item(self.p, self.man, self.idx, self.cfg, "t", force=False)

    def test_deadline_keeps_progress(self):
        self.seed()
        got = indexer.update(self.p, self.man, self.idx, self.cfg, deadline=0.0)
        self.assertFalse(got["finished"])
        self.assertTrue(self.man.meta("cursor"))  # the listing is kept; the next run only extracts
        got = self.update()
        self.assertEqual((got["sync"], got["pending"]), ("changes", 0))


class Commands(unittest.TestCase):
    """index update/status through main, profile t with a mount choice and a FakeProvider."""

    def setUp(self):
        shutil.rmtree(profile.dir("t") / "index", ignore_errors=True)
        for f in ("index.sqlite", "index.sqlite-wal", "index.sqlite-shm", "index.lock"):
            (profile.dir("t") / f).unlink(missing_ok=True)
        self.p = FakeProvider()
        self.p.put("t1", "notes.txt", data=b"heat pump offer")
        cfgp = profile.dir("t") / "config.json"
        self.old_cfg = cfgp.read_text()
        cfgp.write_text(json.dumps({"mount": {"what": "/", "where": f"{TMP}/mnt-t", "persist": False}}))
        self.addCleanup(cfgp.write_text, self.old_cfg)
        patch = mock.patch.object(providers, "for_profile", lambda cfg: self.p)
        patch.start()
        self.addCleanup(patch.stop)

    def test_update_status_and_one_file(self):
        rc, out, err = run("index", "update", "--fields", "status,extracted,files")
        self.assertEqual((rc, out), (0, "done\t1\t1\n"), err)
        md = profile.dir("t") / "index" / "notes.txt.md"
        self.assertIn("heat pump offer", md.read_text())
        with mock.patch.object(service, "state", lambda p: "off"):
            rc, out, _ = run("index", "status", "--fields", "profile,files,indexed,pending,service", "--no-header")
        self.assertEqual(out, "t\t1\t1\t0\toff\n")
        self.p.put("t1", "notes.txt", data=b"cold pump offer")
        rc, out, _ = run("index", "update", str(md), "--no-header")  # an index hit path works
        self.assertEqual((rc, out), (0, "notes.txt\tindexed\tt1\n"))
        self.assertIn("cold pump offer", md.read_text())

    def test_busy_lock_reports_running(self):
        lock = profile.dir("t") / "index.lock"
        lock.write_text(str(os.getppid()))  # a live process that is not us
        try:
            rc, out, err = run("index", "update", "--fields", "status", "--no-header")
        finally:
            lock.unlink()
        self.assertEqual((rc, out), (0, "running\n"))
        self.assertIn("already running", err)

    def test_md_target(self):
        run("index", "update")
        md = profile.dir("t") / "index" / "notes.txt.md"
        self.assertEqual(indexer.md_target(str(md)), ("t", "t1"))
        self.assertIsNone(indexer.md_target(f"{TMP}/elsewhere.md"))

    def test_no_mount_choice(self):
        self.assertRaises(UsageError, providers.scope, {})


class Service(unittest.TestCase):
    def test_units(self):
        svc, timer = service.systemd_units("work")
        self.assertIn('"--profile" "work" "index" "update" "--unbounded"', svc)
        self.assertIn("Type=oneshot", svc)
        self.assertIn("Environment=\"PATH=", svc)
        self.assertIn("OnUnitInactiveSec=300s", timer)
        pl = plistlib.loads(service.launchd_plist("work"))
        self.assertEqual((pl["StartInterval"], pl["Label"]), (300, "gdrive.index.work"))
        self.assertEqual(pl["ProgramArguments"][-5:], ["--profile", "work", "index", "update", "--unbounded"])
        self.assertIn("PATH", pl["EnvironmentVariables"])


if __name__ == "__main__":
    unittest.main()


# ---- what=/ layout: My Drive / Shared with me / Shared drives, sections on demand ------------

DRV = "0AdrvAAAAAAAAAAAAAA"
GFILES = [
    {"id": "R", "name": "My Drive", "mimeType": "application/vnd.google-apps.folder"},
    {"id": "a", "name": "a.txt", "mimeType": "text/plain", "parents": ["R"], "md5Checksum": "m1"},
    {"id": "S", "name": "Brief", "mimeType": "application/vnd.google-apps.folder", "sharedWithMeTime": "2026"},
    {"id": "p", "name": "passport.txt", "mimeType": "text/plain", "parents": ["S"], "md5Checksum": "m2"},
    {"id": "d", "name": "d.txt", "mimeType": "text/plain", "parents": [DRV], "driveId": DRV, "md5Checksum": "m3"},
]


class FakeDriveApi:
    """google.get/download for GoogleDrive: My Drive, one Shared-with-me folder, one Shared drive."""

    def __init__(self):
        self.downloads = 0

    def get(self, remote, url, params=None):
        path = url.split("/drive/v3", 1)[-1]
        if path == "/changes/startPageToken":
            return {"startPageToken": "1"}
        if path == "/drives":
            return {"drives": [{"id": DRV, "name": "Team"}]}
        if path.startswith("/files/"):
            fid = path.rsplit("/", 1)[-1]
            return next(dict(f, id="R") for f in GFILES if f["id"] == ("R" if fid == "root" else fid))
        if path == "/files" and "appProperties" in params["q"]:
            return {"files": []}
        if path == "/files":
            alld = params.get("corpora") == "allDrives"
            return {"files": [f for f in GFILES if alld or not f.get("driveId")]}
        raise AssertionError(url)

    def download(self, remote, url, dest, params=None):
        self.downloads += 1
        Path(dest).write_bytes(b"text of " + url.rsplit("/", 1)[-1].encode())


class AllLayout(IndexCase):
    def setUp(self):
        super().setUp()
        from src.api import drive, google
        self.api = FakeDriveApi()
        for obj, name, fn in ((google, "get", self.api.get), (google, "download", self.api.download)):
            p = mock.patch.object(obj, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def prov(self, sections=("my-drive",), layout=True):
        from src.api.gprovider import GoogleDrive
        return GoogleDrive("gdrive", "/", sections, layout)

    def files(self):
        return sorted(str(p.relative_to(self.idx)) for p in self.idx.rglob("*.md"))

    def test_default_is_my_drive_only(self):
        self.p = self.prov()
        self.update()
        self.assertEqual(self.files(), ["My Drive/a.txt.md"])
        self.assertIn("address: /a.txt", self.md("My Drive/a.txt"))

    def test_old_layout_index_moves_without_download(self):
        self.p = self.prov(layout=False)
        self.update()
        self.assertEqual(self.files(), ["a.txt.md"])
        n = self.api.downloads
        self.p = self.prov()
        got = self.update()
        self.assertEqual((got["sync"], got["moved"], self.api.downloads), ("full", 1, n))
        self.assertEqual(self.files(), ["My Drive/a.txt.md"])

    def test_include_and_exclude_sections(self):
        self.p = self.prov()
        self.update()
        self.p = self.prov(("my-drive", "shared-with-me", "shared:Team"))
        self.update()
        self.assertEqual(self.files(), ["My Drive/a.txt.md", "Shared drives/Team/d.txt.md",
                                        "Shared with me/Brief/passport.txt.md"])
        self.assertIn("address: shared-with-me:/Brief/passport.txt", self.md("Shared with me/Brief/passport.txt"))
        self.assertEqual(self.man.counts("Shared with me")["files"], 1)
        n = self.api.downloads
        self.p = self.prov(("my-drive", "shared:Team"))
        got = self.update()
        self.assertEqual((got["deleted"], self.api.downloads), (1, n))
        self.assertEqual(self.files(), ["My Drive/a.txt.md", "Shared drives/Team/d.txt.md"])

    def test_missing_shared_drive_reported(self):
        self.assertEqual(self.prov(("my-drive", "shared:Gone")).missing, ["Gone"])


class SectionCommands(unittest.TestCase):
    """index include/exclude through main: config persisted, relist, file count, background run."""

    def setUp(self):
        from src.api import google
        shutil.rmtree(profile.dir("t") / "index", ignore_errors=True)
        for f in ("index.sqlite", "index.sqlite-wal", "index.sqlite-shm", "index.lock"):
            (profile.dir("t") / f).unlink(missing_ok=True)
        cfgp = profile.dir("t") / "config.json"
        self.addCleanup(cfgp.write_text, cfgp.read_text())
        cfgp.write_text(json.dumps({"mount": {"what": "/", "where": f"{TMP}/mnt-t", "persist": False}}))
        self.api = FakeDriveApi()
        self.spawned = []
        for obj, name, fn in ((google, "get", self.api.get), (google, "download", self.api.download),
                              (indexer, "spawn", lambda p: self.spawned.append(p) or 4242)):
            p = mock.patch.object(obj, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def test_include_exclude_status(self):
        rc, out, err = run("index", "update", "--fields", "status,files")
        self.assertEqual((rc, out), (0, "done\t1\n"), err)
        rc, out, err = run("index", "include", "shared-with-me", "--fields", "section,status,files,pending", "--no-header")
        self.assertEqual((rc, out), (0, "shared-with-me\tincluded\t1\t1\n"), err)
        self.assertEqual(self.spawned, ["t"])
        self.assertEqual(config.load("t")["index_sections"], ["my-drive", "shared-with-me"])
        rc, out, _ = run("index", "include", "Shared with me", "--fields", "status", "--no-header")
        self.assertEqual(out, "already indexed\n")
        with mock.patch.object(service, "state", lambda p: "off"):
            rc, out, _ = run("index", "status", "--fields", "sections", "--no-header")
        self.assertEqual(out, "my-drive,shared-with-me\n")
        rc, out, err = run("index", "exclude", "shared-with-me", "--fields", "status", "--no-header")
        self.assertEqual((rc, out), (0, "excluded\n"), err)
        self.assertEqual(config.load("t")["index_sections"], ["my-drive"])

    def test_refusals(self):
        rc, _, err = run("index", "include", "elsewhere")
        self.assertEqual(rc, 2)
        self.assertIn("unknown section", err)
        rc, _, err = run("index", "exclude", "my-drive")
        self.assertEqual(rc, 2)
        cfgp = profile.dir("t") / "config.json"
        cfgp.write_text(json.dumps({"mount": {"what": "/Projects", "where": f"{TMP}/mnt-t"}}))
        rc, _, err = run("index", "include", "shared-with-me")
        self.assertEqual(rc, 2)
        self.assertIn("mounts everything", err)
