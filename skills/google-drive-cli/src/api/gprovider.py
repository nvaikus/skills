"""Google Drive behind the index's Provider interface: files.list, the Changes API, alt=media
downloads, exports, and OCR through a temporary Google Doc copy."""
import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core.errors import CliError, UsageError
from . import drive, google, sheets
from .provider import Provider, Transient

DRAWING = "application/vnd.google-apps.drawing"
# what `rclone mount` shows a Google-native file as (--drive-export-formats docx,xlsx,pptx,svg);
# other natives (Forms, Sites, Maps, shortcuts) are not shown by the mount -> not indexed
NATIVE_EXT = {drive.DOC: ".docx", drive.SHEET: ".xlsx", drive.SLIDES: ".pptx", DRAWING: ".svg"}
FIELDS = "id,name,mimeType,md5Checksum,modifiedTime,size,parents,trashed,driveId,appProperties,sharedWithMeTime"
TEMP_KEY = "gdriveIndexTemp"  # appProperties marker of OCR copies; swept when older than SWEEP_AGE
SWEEP_AGE = timedelta(minutes=15)
# what=/ layout: virtual folders (no Drive id) above My Drive's root, Shared with me and Shared drives
ALL_ID, SWM_ID, DRIVES_ID = "~all", "~shared-with-me", "~shared-drives"
SECTIONS = ("my-drive", "shared-with-me", "shared-drives")  # + shared:<Drive> (one Shared drive)


def vrow(i, parent, name):
    return {"id": i, "parent": parent, "name": name, "mime": drive.FOLDER, "folder": 1, "key": None, "md5": None,
            "modified": None, "size": None, "ext": "", "native": 0}


def is_temp(f):
    return (f.get("appProperties") or {}).get(TEMP_KEY) == "1"


def item(f):
    mime = f.get("mimeType", "")
    folder = mime == drive.FOLDER
    native = mime.startswith("application/vnd.google-apps.") and not folder
    ext = "" if folder or not native else NATIVE_EXT.get(mime)
    return {"id": f["id"], "parent": (f.get("parents") or [None])[0], "name": f.get("name", ""), "mime": mime,
            "folder": int(folder), "key": f.get("md5Checksum") or f.get("modifiedTime"),
            "md5": f.get("md5Checksum"), "modified": f.get("modifiedTime"),
            "size": int(f["size"]) if str(f.get("size") or "").isdigit() else None,
            "ext": ext, "native": int(native)}


def classify(e):
    """A per-file CliError -> Transient (retry next run) or the error itself (recorded)."""
    if isinstance(e, UsageError) and e.status in (None, 401):
        raise e  # not logged in / token refused: stop the whole run
    if e.status in (0, 429) or (e.status or 0) >= 500:
        return Transient(str(e))
    return e


class GoogleDrive(Provider):
    """what=/ with layout=True indexes the mount's three-folder layout (My Drive / Shared with me /
    Shared drives), each section only when listed in `sections`; My Drive always. Any other WHAT
    (or an old-layout mount) indexes that one folder tree as before."""
    name = "gdrive"

    def __init__(self, remote, what, sections=(), layout=True):
        self.remote, self.what = remote, what.rstrip("/") or "/"
        self.all = self.what == "/" and layout
        self.missing = []
        if self.all:
            return self._init_all(sections)
        top = drive.resolve(remote, what)
        if top.get("mimeType") != drive.FOLDER:
            raise UsageError(f"{what} is not a folder: the index scope is the profile's mount (/, /Folder, shared:<Drive>)")
        self.top = top["id"]
        self.drive_id = top.get("driveId")

    def _init_all(self, sections):
        self.top, self.drive_id = drive.get(self.remote, "root")["id"], None
        secs = set(sections or ())
        self.swm = "shared-with-me" in secs
        want = {s[len("shared:"):] for s in secs if s.startswith("shared:")}
        every = drive.shared_drives(self.remote) if want or "shared-drives" in secs else []
        self.segs = drive.drive_segments(every)  # over ALL drives: the same names the mount shows
        self.drives = [d for d in every if "shared-drives" in secs or d["name"] in want or f"@{d['id']}" in want]
        found = {d["name"] for d in self.drives} | {f"@{d['id']}" for d in self.drives}
        self.missing = sorted(want - found)

    def scope_key(self):
        if self.all:
            parts = (["swm"] if self.swm else []) + sorted(d["id"] for d in self.drives)
            return f"gdrive:all:{self.top}:{','.join(parts)}"
        return f"gdrive:{self.drive_id or 'my'}:{self.top}"

    def compatible(self, old):
        """Same Drive root, other sections or layout: relist and move texts, never re-download."""
        return self.all and old.split(":")[2:3] == [self.top]

    def root_id(self):
        return ALL_ID if self.all else self.top

    def address(self, rel):
        if self.all:
            return drive.layout_address(rel)
        base = "" if self.what == "/" else self.what
        return f"{base}/{rel}" if rel else (self.what or "/")

    def resolve(self, address):
        f = drive.resolve(self.remote, address)
        return SWM_ID if f.get("swm") else f["id"]

    def _corpus(self):
        if self.drive_id:
            return {"corpora": "drive", "driveId": self.drive_id, "includeItemsFromAllDrives": "true",
                    "supportsAllDrives": "true"}
        if self.all and self.drives:
            return {"corpora": "allDrives", "includeItemsFromAllDrives": "true", "supportsAllDrives": "true"}
        return {"supportsAllDrives": "true"}

    def _virtual(self):
        """The layout's folders that have no Drive item (or whose Drive item says nothing useful)."""
        rows = [vrow(self.top, ALL_ID, drive.MY_DIR)]
        if self.swm:
            rows.append(vrow(SWM_ID, ALL_ID, drive.SWM_DIR))
        if self.drives:
            rows.append(vrow(DRIVES_ID, ALL_ID, drive.DRIVES_DIR))
            rows += [vrow(d["id"], DRIVES_ID, self.segs[d["id"]]) for d in self.drives]
        return rows

    def _item(self, f):
        if not self.all:
            return item(f)
        virtual = {r["id"]: r for r in self._virtual()}
        if f.get("id") in virtual:
            return virtual[f["id"]]
        it = item(f)
        if not it["parent"] and self.swm and f.get("sharedWithMeTime"):
            it["parent"] = SWM_ID  # a top item of Shared with me (its real parent is not visible to us)
        return it

    def start_cursor(self):
        p = {"supportsAllDrives": "true", **({"driveId": self.drive_id} if self.drive_id else {})}
        return google.get(self.remote, f"{google.DRIVE}/changes/startPageToken", p)["startPageToken"]

    def list_all(self):
        if self.all:
            yield self._virtual()
        params = {"q": "trashed = false", "pageSize": 1000, "fields": f"nextPageToken,files({FIELDS})",
                  **self._corpus()}
        while True:
            page = google.get(self.remote, f"{google.DRIVE}/files", params) or {}
            yield [self._item(f) for f in page.get("files", []) if not is_temp(f)]
            if not page.get("nextPageToken"):
                return
            params["pageToken"] = page["nextPageToken"]

    def changes(self, cursor):
        params = {"pageToken": cursor, "pageSize": 1000, "includeRemoved": "true", "supportsAllDrives": "true",
                  "fields": f"nextPageToken,newStartPageToken,changes(changeType,removed,fileId,file({FIELDS}))"}
        if self.drive_id:
            params.update(driveId=self.drive_id, includeItemsFromAllDrives="true")
        elif self.all and self.drives:
            params.update(includeItemsFromAllDrives="true")
        while True:
            page = google.get(self.remote, f"{google.DRIVE}/changes", params) or {}
            ups, gone = [], []
            for c in page.get("changes", []):
                if c.get("changeType") == "drive":
                    continue
                f = c.get("file")
                if c.get("removed") or not f or f.get("trashed") or is_temp(f):
                    gone.append(c.get("fileId"))
                else:
                    ups.append(self._item(f))
            nxt = page.get("nextPageToken") or page.get("newStartPageToken")
            yield ups, gone, nxt
            if not page.get("nextPageToken"):
                return
            params["pageToken"] = page["nextPageToken"]

    def get(self, item_id):
        if self.all and item_id.startswith("~"):
            return next((r for r in self._virtual() if r["id"] == item_id), None)
        try:
            f = google.get(self.remote, f"{google.DRIVE}/files/{item_id}", {"fields": FIELDS, "supportsAllDrives": "true"})
        except UsageError as e:
            if e.status == 404:
                return None
            raise
        return None if not f or f.get("trashed") or is_temp(f) else self._item(f)

    def list_children(self, folder_id):
        if self.all and folder_id in (ALL_ID, DRIVES_ID):
            return [r for r in self._virtual() if r["parent"] == folder_id]
        cond = "sharedWithMe = true" if folder_id == SWM_ID else f"'{folder_id}' in parents"
        params = {"q": f"{cond} and trashed = false", "pageSize": 1000,
                  "fields": f"nextPageToken,files({FIELDS})", **self._corpus()}
        out = []
        while True:
            page = google.get(self.remote, f"{google.DRIVE}/files", params) or {}
            out += [self._item(f) for f in page.get("files", []) if not is_temp(f)]
            if not page.get("nextPageToken"):
                return out
            params["pageToken"] = page["nextPageToken"]

    def fetch(self, it, dest):
        try:
            google.download(self.remote, f"{google.DRIVE}/files/{it['id']}", dest,
                            {"alt": "media", "supportsAllDrives": "true"})
        except CliError as e:
            raise classify(e) from None

    def _export(self, file_id, mime, dest):
        google.download(self.remote, f"{google.DRIVE}/files/{file_id}/export", dest, {"mimeType": mime})
        return Path(dest).read_bytes().decode("utf-8", "replace")

    def export_text(self, it, tmp):
        dest = Path(tmp) / f"export-{it['id']}"
        try:
            if it["mime"] == drive.DOC:
                try:
                    return self._export(it["id"], "text/markdown", dest), "gdoc-md"
                except CliError as e:
                    if e.status not in (400, 403) or "exportSizeLimitExceeded" in google.reasons(e):
                        raise
                    return self._export(it["id"], "text/plain", dest), "gdoc-txt"  # markdown export not offered
            if it["mime"] == drive.SLIDES:
                return self._export(it["id"], "text/plain", dest), "gslides-txt"
            if it["mime"] == drive.SHEET:
                return self._sheet_csv(it["id"]), "gsheet-csv"
            return None
        except CliError as e:
            raise classify(e) from None
        finally:
            dest.unlink(missing_ok=True)

    def _sheet_csv(self, sid):
        out = io.StringIO()
        for tab in sheets.tabs(self.remote, sid):
            _, grid = sheets.get(self.remote, sid, tab["tab"], "formatted")
            out.write(f"## Sheet: {tab['tab']}\n")
            csv.writer(out, lineterminator="\n").writerows(grid)
            out.write("\n")
        return out.getvalue()

    def ocr_text(self, it, tmp):
        """files.copy into a Google Doc (Drive runs OCR on PDFs/images), export text, delete the
        copy at once. The copy carries appProperties gdriveIndexTemp=1 so sweep() removes it if
        this process dies in between."""
        copy = None
        try:
            copy = google.mutate(self.remote, "POST", f"{google.DRIVE}/files/{it['id']}/copy", body={
                "name": f".gdrive-index-ocr-{it['id']}", "mimeType": drive.DOC, "parents": ["root"],
                "appProperties": {TEMP_KEY: "1"}}, params={"supportsAllDrives": "true", "fields": "id"})
            return self._export(copy["id"], "text/plain", Path(tmp) / f"ocr-{it['id']}")
        except CliError as e:
            raise classify(e) from None
        finally:
            if copy and copy.get("id"):
                self._delete(copy["id"])
            (Path(tmp) / f"ocr-{it['id']}").unlink(missing_ok=True)

    def _delete(self, file_id):
        try:
            google.mutate(self.remote, "DELETE", f"{google.DRIVE}/files/{file_id}", params={"supportsAllDrives": "true"})
        except CliError:
            pass  # sweep() retries it on the next run

    def sweep(self):
        q = f"appProperties has {{ key='{TEMP_KEY}' and value='1' }} and trashed = false"
        page = google.get(self.remote, f"{google.DRIVE}/files",
                          {"q": q, "pageSize": 100, "fields": "files(id,createdTime)"}) or {}
        cutoff = datetime.now(timezone.utc) - SWEEP_AGE
        n = 0
        for f in page.get("files", []):
            try:
                made = datetime.fromisoformat(f.get("createdTime", "").replace("Z", "+00:00"))
            except ValueError:
                made = cutoff
            if made <= cutoff:  # younger ones may belong to a run still converting them
                self._delete(f["id"])
                n += 1
        return n
