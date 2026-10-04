"""Drive paths -> file ids. Address grammar (shared by every doc/sheet/ls/link command):
  /A/B/C  or  A/B/C       My Drive, by names
  shared:<Drive>/A/B      a Shared drive by its name
  shared-with-me:/A/B     "Shared with me": items others shared with this account (flat root)
  name@<id> (component)   pick one of several same-named files; also a bare @<id>
  https://docs.google.com/.../d/<id>/...   any Drive/Docs/Sheets URL
A name ending in .docx/.xlsx/.pptx also matches the Google Doc/Sheet/Slides it is exported from
(that is how the mount shows them)."""
import difflib
import re

from ..core.errors import CliError, UsageError
from . import google

FOLDER = "application/vnd.google-apps.folder"
DOC = "application/vnd.google-apps.document"
SHEET = "application/vnd.google-apps.spreadsheet"
SLIDES = "application/vnd.google-apps.presentation"
EXPORT_EXT = {".docx": DOC, ".xlsx": SHEET, ".pptx": SLIDES}
KIND = {FOLDER: "folder", DOC: "doc", SHEET: "sheet", SLIDES: "slides",
        "application/vnd.google-apps.shortcut": "shortcut", "application/vnd.google-apps.form": "form"}
FIELDS = "id,name,mimeType,size,modifiedTime,parents,driveId,webViewLink,trashed"
ALL = {"supportsAllDrives": "true"}
URL_ID = re.compile(r"(?:/d/|/folders/|[?&]id=)([A-Za-z0-9_-]{10,})")
AT_ID = re.compile(r"^(.*)@([A-Za-z0-9_-]{15,})$")
SWM = "shared-with-me:"  # address prefix; the root is virtual (no folder id): sharedWithMe = true


def kind(f):
    mt = f.get("mimeType", "")
    return KIND.get(mt) or ("google-" + mt.rsplit(".", 1)[-1] if mt.startswith("application/vnd.google-apps.") else "file")


def label(f):
    return f"{f.get('name')}@{f.get('id')}"


def _q(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def get(remote, file_id):
    return google.get(remote, f"{google.DRIVE}/files/{file_id}", {"fields": FIELDS, **ALL})


def _list(remote, q, drive_id=None, limit=None, order="folder,name"):
    params = {"q": q, "fields": f"nextPageToken,files({FIELDS})", "pageSize": 1000, "orderBy": order,
              "includeItemsFromAllDrives": "true", **ALL}
    if drive_id:
        params.update(corpora="drive", driveId=drive_id)
    out, token = [], None
    while True:
        if token:
            params["pageToken"] = token
        page = google.get(remote, f"{google.DRIVE}/files", params) or {}
        out += page.get("files", [])
        token = page.get("nextPageToken")
        if not token or (limit and len(out) >= limit):
            return out[:limit] if limit else out


def swm_root():
    return {"id": None, "name": "Shared with me", "mimeType": FOLDER, "swm": True}


def _in(folder):
    """files.list condition for 'is a child of folder' (the Shared-with-me root has no id)."""
    return "sharedWithMe = true" if folder.get("swm") else f"'{_q(folder['id'])}' in parents"


def children(remote, folder, limit=None):
    return _list(remote, f"{_in(folder)} and trashed = false", folder.get("driveId"), limit)


def shared_drive(remote, name):
    found = google.get(remote, f"{google.DRIVE}/drives", {"q": f"name = '{_q(name)}'", "pageSize": 100}) or {}
    drives = found.get("drives", [])
    if not drives:
        every = (google.get(remote, f"{google.DRIVE}/drives", {"pageSize": 100}) or {}).get("drives", [])
        close = difflib.get_close_matches(name, [d["name"] for d in every], n=5, cutoff=0.4)
        raise UsageError(f"no Shared drive named {name!r}" + (f"; close: {', '.join(close)}" if close else ""),
                         payload=[{"shared_drive": d["name"], "id": d["id"]} for d in every[:20]])
    if len(drives) > 1:
        raise UsageError(f"{len(drives)} Shared drives are named {name!r}; address one as shared:@<id>",
                         payload=[{"candidate": label(d)} for d in drives])
    return drives[0]


# what=/ ("everything") layout of a mount and of the index: three top folders
MY_DIR, SWM_DIR, DRIVES_DIR = "My Drive", "Shared with me", "Shared drives"


def shared_drives(remote):
    out, params = [], {"pageSize": 100}
    while True:
        page = google.get(remote, f"{google.DRIVE}/drives", params) or {}
        out += page.get("drives", [])
        if not page.get("nextPageToken"):
            return out
        params["pageToken"] = page["nextPageToken"]


def drive_segments(drives):
    """Shared drives -> {id: folder name under 'Shared drives/'}: '/' shown as '／' (as rclone does),
    names equal ignoring case get '<name>@<id>' (the form `shared:@<id>` addresses)."""
    names = {}
    for d in drives:
        names.setdefault(d["name"].casefold(), []).append(d)
    return {d["id"]: d["name"].replace("/", "／") if len(g) == 1 else f"{d['name'].replace('/', '／')}@{d['id']}"
            for g in names.values() for d in g}


def layout_address(rel):
    """A path inside the what=/ layout ('My Drive/A', 'Shared with me/X', 'Shared drives/T/A')
    -> the gdrive address of that item ('/A', 'shared-with-me:/X', 'shared:T/A')."""
    top, _, rest = rel.strip("/").partition("/")
    if top == SWM_DIR:
        return f"{SWM}/{rest}"
    if top == DRIVES_DIR and rest:
        seg, _, sub = rest.partition("/")
        m = AT_ID.match(seg)
        name = f"@{m.group(2)}" if m else seg
        return f"shared:{name}" + (f"/{sub}" if sub else "")
    if top == MY_DIR:
        return f"/{rest}"
    return "/"  # the layout root itself, or a top folder that does not exist


def split(address):
    """-> (root, [components]). root: ('id', <id>) | ('my', None) | ('shared', <name>)."""
    a = address.strip()
    m = URL_ID.search(a) if "://" in a else None
    if m:
        return ("id", m.group(1)), []
    if a.startswith("@"):
        return ("id", a[1:]), []
    if a.startswith(SWM):
        return ("swm", None), [c for c in a[len(SWM):].split("/") if c]
    if a.startswith("shared:"):
        rest = a[len("shared:"):].strip("/")
        head, _, tail = rest.partition("/")
        if not head:
            raise UsageError("shared: needs a Shared drive name, e.g. shared:Team/Folder")
        return ("shared", head), [c for c in tail.split("/") if c]
    return ("my", None), [c for c in a.split("/") if c]


def root(remote, spec):
    kind_, val = spec
    if kind_ == "id":
        return get(remote, val)
    if kind_ == "shared":
        if val.startswith("@"):
            d = google.get(remote, f"{google.DRIVE}/drives/{val[1:]}")
        else:
            d = shared_drive(remote, val)
        return {"id": d["id"], "name": d["name"], "mimeType": FOLDER, "driveId": d["id"]}
    if kind_ == "swm":
        return swm_root()
    f = get(remote, "root")
    f["name"] = "My Drive"
    return f


def _by_id(remote, comp):
    m = AT_ID.match(comp)
    if not m:
        return None
    try:
        return get(remote, m.group(2))
    except UsageError:
        return None  # not an id after all: a literal name containing '@'


def find_child(remote, parent, name, last):
    hit = _by_id(remote, name)
    if hit:
        return hit
    q = f"{_in(parent)} and name = '{_q(name)}' and trashed = false"
    found = _list(remote, q, parent.get("driveId"))
    ext = name[name.rfind("."):].lower() if "." in name else ""
    if not found and last and ext in EXPORT_EXT:
        base = name[: -len(ext)]
        q = (f"{_in(parent)} and name = '{_q(base)}' and "
             f"mimeType = '{EXPORT_EXT[ext]}' and trashed = false")
        found = _list(remote, q, parent.get("driveId"))
    if not last:
        found = [f for f in found if f.get("mimeType") == FOLDER] or found
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise UsageError(f"{len(found)} items named {name!r} in {parent.get('name')!r}; "
                         "address one as name@id", payload=[
                             {"candidate": label(f), "kind": kind(f), "modified": f.get("modifiedTime")}
                             for f in found])
    return None


def resolve(remote, address):
    """Address -> file dict. Not found / ambiguous -> exit 2 with candidates."""
    spec, comps = split(address)
    cur = root(remote, spec)
    for i, comp in enumerate(comps):
        if cur.get("mimeType") != FOLDER:
            raise UsageError(f"{cur.get('name')!r} is not a folder (path {address!r})")
        nxt = find_child(remote, cur, comp, last=i == len(comps) - 1)
        if nxt is None:
            names = [f["name"] for f in children(remote, cur, limit=1000)]
            close = difflib.get_close_matches(comp, names, n=5, cutoff=0.5)
            raise UsageError(f"not found: {comp!r} in {cur.get('name')!r}"
                             + (f"; did you mean: {', '.join(close)}" if close else ""))
        cur = nxt
    return cur


def split_parent(address):
    """'/A/B/Name' -> ('/A/B', 'Name') for creating Name inside an existing folder."""
    a = address.strip().rstrip("/")
    if "://" in a or a.startswith("@"):
        raise UsageError("give the new item as a path (/Folder/Name), not a URL or id")
    if a.startswith("shared:") and "/" not in a:
        raise UsageError("give a name inside the Shared drive: shared:<Drive>/<Name>")
    if a.startswith(SWM) and "/" not in a[len(SWM):].strip("/"):
        return SWM, a[len(SWM):].strip("/")  # its root: create_unique refuses it with a clear reason
    head, _, name = a.rpartition("/")
    if not name:
        raise UsageError(f"no name in {address!r}")
    return (head or "/"), name


def create(remote, parent, name, mime):
    body = {"name": name, "mimeType": mime, "parents": [parent["id"]]}
    return google.mutate(remote, "POST", f"{google.DRIVE}/files", body=body, params={"fields": FIELDS, **ALL})


def create_unique(remote, parent_address, name, mime):
    """Create unless the name is already taken there (a duplicate makes every later path ambiguous)."""
    from ..core.errors import Refused
    parent = resolve(remote, parent_address)
    if parent.get("swm"):
        raise UsageError("nothing can be created at the top of \"Shared with me\" (it is a list, not a folder): "
                         "create it inside a shared folder (shared-with-me:/<Folder>/<Name>) or in My Drive")
    if parent.get("mimeType") != FOLDER:
        raise UsageError(f"{parent_address!r} is not a folder")
    q = f"'{_q(parent['id'])}' in parents and name = '{_q(name)}' and trashed = false"
    taken = _list(remote, q, parent.get("driveId"))
    if taken:
        raise Refused(f"{name!r} already exists in {parent.get('name')!r} ({label(taken[0])}) - nothing created; "
                      "pick another name or edit the existing one")
    f = create(remote, parent, name, mime)
    if not f or not f.get("id"):
        raise CliError("Drive answered without an id; check with gdrive ls")
    return f


def about(remote):
    return google.get(remote, f"{google.DRIVE}/about", {"fields": "user(displayName,emailAddress),storageQuota"})


def row(f):
    return {"name": f.get("name"), "kind": kind(f), "id": f.get("id"), "size": f.get("size"),
            "modified": f.get("modifiedTime"), "url": f.get("webViewLink"), "mime": f.get("mimeType")}


def share_public(remote, f):
    """Anyone-with-the-link viewer permission (what `rclone link` creates), by id so every
    address form works - including Docs, which rclone only knows by their export name."""
    google.mutate(remote, "POST", f"{google.DRIVE}/files/{f['id']}/permissions",
                  body={"type": "anyone", "role": "reader", "allowFileDiscovery": False}, params=ALL)
    return get(remote, f["id"]).get("webViewLink")


PERM_FIELDS = "permissions(id,type,role,emailAddress,domain,displayName,permissionDetails(inherited))"


def permissions(remote, f):
    """Permissions of an item, each with `inherited` (bool): from permissionDetails when Drive returns it,
    else true when the parent folder carries the same grant (same permission id and role)."""
    perms = (google.get(remote, f"{google.DRIVE}/files/{f['id']}/permissions",
                        {"fields": PERM_FIELDS, **ALL}) or {}).get("permissions", [])
    parent = None
    for p in perms:
        details = p.get("permissionDetails")
        if details:
            p["inherited"] = all(d.get("inherited") for d in details)
            continue
        if parent is None:
            pid = (f.get("parents") or [None])[0]
            parent = _grants(remote, pid) if pid else set()
        p["inherited"] = p.get("role") != "owner" and (p.get("id"), p.get("role")) in parent
    return perms


def _grants(remote, folder_id):
    try:
        perms = google.get(remote, f"{google.DRIVE}/files/{folder_id}/permissions", {"fields": PERM_FIELDS, **ALL})
    except CliError:  # parent not readable (an item shared to us alone): nothing is known as inherited
        return set()
    return {(q.get("id"), q.get("role")) for q in (perms or {}).get("permissions", [])}


def perm_who(p):
    return p.get("emailAddress") or p.get("domain") or p.get("type")


def share_user(remote, f, email, role, notify):
    """Grant one person access. Notification email only when asked (Drive sends one by default)."""
    return google.mutate(remote, "POST", f"{google.DRIVE}/files/{f['id']}/permissions",
                         body={"type": "user", "role": role, "emailAddress": email},
                         params={"sendNotificationEmail": "true" if notify else "false", **ALL})


def unshare(remote, f, perm_id):
    google.mutate(remote, "DELETE", f"{google.DRIVE}/files/{f['id']}/permissions/{perm_id}", params=ALL)
