"""A listing's photos: full-size links, download to a dir, optional contact sheet via ffmpeg (if on PATH)."""
import math
import shutil
import subprocess
from pathlib import Path

from ..core import http
from ..core.errors import CliError, UsageError

SHEET_CELL = 400   # px per tile side
SHEET_COLS = 4


def links(o):
    """-> [(n, url)] at each photo's own size (the link is a {width}x{height} template)."""
    out = []
    for n, ph in enumerate(o.get("photos") or [], 1):
        if isinstance(ph, dict) and ph.get("link"):
            size = f"{ph.get('width') or 1000}x{ph.get('height') or 1000}"
            out.append((n, ph["link"].replace("{width}x{height}", size)))
    return out


def download(o, out_dir, limit=None):
    """-> rows {n, path, bytes, url}. Files: <dir>/<id>-NN.jpg (overwritten)."""
    todo = links(o)[:limit] if limit else links(o)
    d = Path(out_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, url in todo:
        data = http.get(url, want="bytes")
        p = d / f"{o['id']}-{n:02d}.jpg"
        p.write_bytes(data)
        rows.append({"n": n, "path": str(p), "bytes": len(data), "url": url})
    return rows


def sheet(o, rows, out_dir):
    """Photos already downloaded -> one grid JPEG <dir>/<id>-sheet.jpg; needs ffmpeg."""
    ff = shutil.which("ffmpeg")
    if not ff:
        raise UsageError("--sheet needs ffmpeg on PATH (photos are downloaded; install ffmpeg or drop --sheet)")
    cols = min(SHEET_COLS, len(rows))
    grid = f"{cols}x{math.ceil(len(rows) / cols)}"
    c = SHEET_CELL
    out = Path(out_dir).expanduser() / f"{o['id']}-sheet.jpg"
    cell = f"scale={c}:{c}:force_original_aspect_ratio=decrease,pad={c}:{c}:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1"
    graph = ";".join(f"[{i}:v]{cell}[c{i}]" for i in range(len(rows)))
    graph += ";" + "".join(f"[c{i}]" for i in range(len(rows))) + f"concat=n={len(rows)}:v=1,tile={grid}:padding=4:color=white"
    cmd = [ff, "-v", "error", "-y"]
    for r in rows:
        cmd += ["-i", r["path"]]
    cmd += ["-filter_complex", graph, "-frames:v", "1", "-q:v", "3", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise CliError("ffmpeg contact sheet timed out after 120 s") from None
    if r.returncode != 0 or not out.exists():
        raise CliError(f"ffmpeg contact sheet failed: {(r.stderr or '').strip()[:300]}")
    return {"n": "sheet", "path": str(out), "bytes": out.stat().st_size, "url": ""}
