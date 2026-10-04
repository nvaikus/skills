"""Google Sheets by path: cell grids in/out as TSV."""
import re
import urllib.parse

from ..core.errors import CliError, UsageError
from . import drive, google

A1 = re.compile(r"^\$?[A-Za-z]{0,3}\$?\d*(:\$?[A-Za-z]{0,3}\$?\d*)?$")
RENDER = {"formatted": "FORMATTED_VALUE", "raw": "UNFORMATTED_VALUE", "formula": "FORMULA"}


def open_sheet(remote, address):
    f = drive.resolve(remote, address)
    if f.get("mimeType") != drive.SHEET:
        raise UsageError(f"{drive.label(f)} is a {drive.kind(f)}, not a Google Sheet"
                         + (" - .xlsx files are edited in the mount" if f.get("name", "").endswith(".xlsx") else ""))
    return f


def tabs(remote, sid):
    meta = google.get(remote, f"{google.SHEETS}/spreadsheets/{sid}", {
        "fields": "sheets.properties(sheetId,title,index,hidden,gridProperties(rowCount,columnCount))"}) or {}
    out = []
    for s in meta.get("sheets", []):
        p = s.get("properties", {})
        g = p.get("gridProperties", {})
        out.append({"tab": p.get("title"), "id": p.get("sheetId"), "index": p.get("index"),
                    "rows": g.get("rowCount"), "cols": g.get("columnCount"), "hidden": bool(p.get("hidden"))})
    return out


def _quote_tab(t):
    t = t.strip()
    if t.startswith("'") and t.endswith("'"):
        return t
    return "'" + t.replace("'", "''") + "'"


def norm_range(rng):
    """'Tab!A1:C', 'A1:C9' (first tab), or a bare tab name (spaces ok) -> API range."""
    if not rng:
        return None
    if "!" in rng:
        tab, _, cells = rng.rpartition("!")
        return f"{_quote_tab(tab)}!{cells}"
    if A1.match(rng) and any(c.isalpha() for c in rng):
        return rng
    return _quote_tab(rng)


def _default_range(remote, sid, rng):
    r = norm_range(rng)
    if r:
        return r
    ts = tabs(remote, sid)
    if not ts:
        raise CliError("the spreadsheet has no tabs")
    return _quote_tab(ts[0]["tab"])


def _url(sid, rng, suffix=""):
    return f"{google.SHEETS}/spreadsheets/{sid}/values/{urllib.parse.quote(rng, safe='')}{suffix}"


def get(remote, sid, rng, render):
    r = _default_range(remote, sid, rng)
    res = google.get(remote, _url(sid, r), {"valueRenderOption": RENDER[render], "majorDimension": "ROWS"}) or {}
    return res.get("range"), res.get("values", [])


def put(remote, sid, rng, grid, raw):
    r = norm_range(rng)
    res = google.mutate(remote, "PUT", _url(sid, r), body={"range": r, "majorDimension": "ROWS", "values": grid},
                        params={"valueInputOption": "RAW" if raw else "USER_ENTERED"}) or {}
    return {"range": res.get("updatedRange"), "rows": res.get("updatedRows"), "cols": res.get("updatedColumns"),
            "cells": res.get("updatedCells")}


def append(remote, sid, tab, grid, raw):
    r = _default_range(remote, sid, tab)
    res = google.mutate(remote, "POST", _url(sid, r, ":append"), body={"majorDimension": "ROWS", "values": grid},
                        params={"valueInputOption": "RAW" if raw else "USER_ENTERED",
                                "insertDataOption": "INSERT_ROWS"}) or {}
    u = res.get("updates") or {}
    return {"range": u.get("updatedRange"), "rows": u.get("updatedRows"), "cols": u.get("updatedColumns"),
            "cells": u.get("updatedCells")}


def _unescape(cell):
    out, i = [], 0
    while i < len(cell):
        c = cell[i]
        if c == "\\" and i + 1 < len(cell):
            nxt = cell[i + 1]
            out.append({"t": "\t", "n": "\n", "\\": "\\"}.get(nxt, "\\" + nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_tsv(text):
    """TSV (same escaping as `sheet get`: \\t \\n \\\\) -> grid. Trailing empty lines dropped."""
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise UsageError("no rows on stdin: pipe TSV in (one row per line, tab-separated)")
    return [[_unescape(c) for c in ln.split("\t")] for ln in lines]


def new(remote, address):
    parent, name = drive.split_parent(address)
    return drive.create_unique(remote, parent, name, drive.SHEET)
