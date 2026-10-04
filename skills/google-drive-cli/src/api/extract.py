"""Local file -> plain text for the index. stdlib only, nothing installed: Office files are zip +
XML; PDFs use `pdftotext` when it is already on PATH (else the caller asks the provider to OCR).
Pure: no network, no printing."""
import csv
import io
import os
import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET

MAX_CHARS = 2_000_000  # one index file; the rest is cut with a note
TRUNC = "\n[... truncated by gdrive index: file text is longer than 2M characters]\n"

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PDF = "application/pdf"
BY_MIME = {DOCX: "docx", XLSX: "xlsx", PPTX: "pptx", PDF: "pdf"}
BY_EXT = {".docx": "docx", ".docm": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pptx": "pptx", ".pdf": "pdf",
          ".txt": "text", ".md": "text", ".csv": "text", ".tsv": "text", ".json": "text", ".xml": "text",
          ".html": "text", ".htm": "text", ".yaml": "text", ".yml": "text", ".log": "text", ".rtf": "text",
          ".ini": "text", ".sql": "text", ".py": "text", ".js": "text", ".ts": "text", ".sh": "text",
          ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image", ".bmp": "image",
          ".webp": "image", ".tif": "image", ".tiff": "image", ".heic": "image"}
TEXT_MIMES = {"application/json", "application/xml", "application/x-yaml", "application/yaml",
              "application/javascript", "application/x-sh", "application/sql", "application/rtf"}
OCR_IMAGES = {"image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp", "image/tiff"}  # Drive converts these

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def kind(mime, name):
    """-> docx | xlsx | pptx | pdf | text | image | None (metadata line only)."""
    k = BY_MIME.get(mime or "")
    if k:
        return k
    if mime in OCR_IMAGES:
        return "image"
    if (mime or "").startswith("text/") or mime in TEXT_MIMES:
        return "text"
    return BY_EXT.get(os.path.splitext(name or "")[1].lower())


def cap(text):
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + TRUNC


def human(n):
    if n in (None, ""):
        return "size unknown"
    n = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def meta_line(name, mime, size, why=None):
    """The whole index text of a file whose content is not extracted."""
    line = f"{name} · {mime or 'unknown type'} · {human(size)}"
    return line + (f"\n(text not indexed: {why})" if why else "") + "\n"


# ---- plain text ----------------------------------------------------------------------------

def text(path):
    with open(path, "rb") as f:
        raw = f.read(MAX_CHARS * 2)
    if b"\x00" in raw[:8192]:
        return None  # binary despite the name
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            return cap(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return None


# ---- Office (zip + XML) --------------------------------------------------------------------

def _rels(zf, part):
    """Relationship ids of a part -> target part names inside the zip."""
    base = part.rsplit("/", 1)[0]
    rels = f"{base}/_rels/{part.rsplit('/', 1)[1]}.rels"
    if rels not in zf.namelist():
        return {}
    out = {}
    for r in ET.fromstring(zf.read(rels)).iter(PR + "Relationship"):
        t = r.get("Target", "")
        if r.get("TargetMode") == "External":
            continue
        full = t.lstrip("/") if t.startswith("/") else os.path.normpath(f"{base}/{t}").replace(os.sep, "/")
        out[r.get("Id")] = (full, r.get("Type", ""))
    return out


def _para_docx(p):
    out = []
    for el in p.iter():
        if el.tag == W + "t" and el.text:
            out.append(el.text)
        elif el.tag == W + "tab":
            out.append("\t")
        elif el.tag in (W + "br", W + "cr"):
            out.append("\n")
    line = "".join(out)
    style = p.find(f"{W}pPr/{W}pStyle")
    sval = (style.get(W + "val") or "") if style is not None else ""
    m = re.match(r"(?i)heading(\d)", sval)
    if line.strip() and (m or sval.lower() == "title"):
        return "#" * (int(m.group(1)) if m else 1) + " " + line
    if line.strip() and p.find(f"{W}pPr/{W}numPr") is not None:
        return "- " + line
    return line


def docx(path):
    with zipfile.ZipFile(path) as zf:
        body = ET.fromstring(zf.read("word/document.xml")).find(W + "body")
    lines = []
    for el in list(body) if body is not None else []:
        if el.tag == W + "p":
            lines.append(_para_docx(el))
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                cells = [" ".join(_para_docx(p) for p in tc.iter(W + "p")).strip() for tc in tr.iter(W + "tc")]
                lines.append("| " + " | ".join(cells) + " |")
    return cap(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n")


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]*", ref or "").group(0):
        n = n * 26 + ord(ch) - 64
    return max(n - 1, 0)


def _si_text(si):
    return "".join(t.text or "" for t in si.iter(S + "t"))


def xlsx(path):
    """## Sheet: <name> then the rows as CSV (formula cells: their last computed value)."""
    out = io.StringIO()
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = [_si_text(si) for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).iter(S + "si")]
        rels = _rels(zf, "xl/workbook.xml")
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        for sh in wb.iter(S + "sheet"):
            target = rels.get(sh.get(R + "id"), (None,))[0]
            if not target or target not in names:
                continue
            out.write(f"## Sheet: {sh.get('name')}\n")
            w = csv.writer(out, lineterminator="\n")
            with zf.open(target) as f:
                for _, el in ET.iterparse(f):
                    if el.tag != S + "row":
                        continue
                    row = []
                    for c in el.iter(S + "c"):
                        t, v = c.get("t"), c.find(S + "v")
                        if t == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(shared):
                            val = shared[int(v.text)]
                        elif t == "inlineStr":
                            val = "".join(x.text or "" for x in c.iter(S + "t"))
                        elif t == "b" and v is not None:
                            val = "TRUE" if v.text == "1" else "FALSE"
                        else:
                            val = v.text if v is not None and v.text is not None else ""
                        i = _col(c.get("r"))
                        row += [""] * (i - len(row)) if i > len(row) else []
                        row.append(val)
                    el.clear()
                    if any(x.strip() for x in row):
                        w.writerow(row)
                    if out.tell() > MAX_CHARS:
                        return cap(out.getvalue())
            out.write("\n")
    return cap(out.getvalue())


def _slide_text(zf, part):
    lines = []
    for p in ET.fromstring(zf.read(part)).iter(A + "p"):
        line = "".join(t.text or "" for t in p.iter(A + "t"))
        if line.strip():
            lines.append(line)
    return lines


def pptx(path):
    """## Slide N, its text, then its speaker notes."""
    out = []
    with zipfile.ZipFile(path) as zf:
        rels = _rels(zf, "ppt/presentation.xml")
        pres = ET.fromstring(zf.read("ppt/presentation.xml"))
        for n, sid in enumerate(pres.iter(P + "sldId"), 1):
            part = rels.get(sid.get(R + "id"), (None,))[0]
            if not part or part not in zf.namelist():
                continue
            out.append(f"## Slide {n}")
            out += _slide_text(zf, part)
            notes = [t for t, typ in _rels(zf, part).values() if typ.endswith("/notesSlide")]
            if notes and notes[0] in zf.namelist():
                body = [ln for ln in _slide_text(zf, notes[0]) if not ln.strip().isdigit()]
                if body:
                    out.append("Notes: " + " ".join(body))
            out.append("")
    return cap("\n".join(out).strip() + "\n")


# ---- PDF -----------------------------------------------------------------------------------

def pdftotext():
    return shutil.which("pdftotext")


def pdf(path):
    """-> text, or None when pdftotext is not on PATH. '' = no text layer (scanned)."""
    exe = pdftotext()
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "-layout", "-enc", "UTF-8", "-q", str(path), "-"], capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return cap(p.stdout.decode("utf-8", "replace")) if p.returncode == 0 else ""


def meaningful(text_):
    """Enough real characters to count as a text layer (scanned PDFs yield page breaks only)."""
    return sum(ch.isalnum() for ch in (text_ or "")) >= 10  # live: a 1-line quote PDF has ~20


def office(k, path):
    """docx/xlsx/pptx -> text; a broken or encrypted file -> ValueError with the reason."""
    try:
        return {"docx": docx, "xlsx": xlsx, "pptx": pptx}[k](path)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise ValueError(f"unreadable {k} ({type(e).__name__}: password-protected or damaged?)") from None
