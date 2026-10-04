"""Writer: the only place that prints data. TSV by default, JSON on -j."""
import json
import sys

from .errors import UsageError


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v).replace("\t", " ").replace("\r", "").replace("\n", " ↵ ")


def _get(row, path):
    """Dotted paths: --fields owner.email reads row['owner']['email']."""
    for part in path.split("."):
        if not isinstance(row, dict):
            return None
        row = row.get(part)
    return row


def _has(row, path):
    for part in path.split("."):
        if not isinstance(row, dict) or part not in row:
            return False
        row = row[part]
    return True


def grid_cell(v):
    """Grid TSV escaping (round-trips through sheet set): backslash, tab, newline."""
    s = "" if v is None else str(v)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\r\n", "\n").replace("\n", "\\n")


class Writer:
    def __init__(self, json_mode=False, fields=None, header=True, out=None, err=None):
        self.json = json_mode
        self.fields = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
        self.header = header
        self.out = out or sys.stdout
        self.err = err or sys.stderr

    def write(self, rows, fields, receipt=False):
        """rows: list of dicts. fields: default TSV columns. receipt: one header-less row / one JSON object."""
        cols = self.fields or fields
        if self.fields and rows:
            missing = [c for c in cols if not any(_has(r, c) for r in rows)]
            if missing:
                avail = sorted({k for r in rows for k in r})
                raise UsageError(f"unknown field(s) {', '.join(missing)}; this command has: {', '.join(avail)}")
        if self.json:
            data = rows if not self.fields else [{c: _get(r, c) for c in cols} for r in rows]
            if receipt:
                data = data[0] if data else None
            self.out.write(json.dumps(data, ensure_ascii=False, indent=1, default=str) + "\n")
            return
        if self.header and not receipt:
            self.out.write("\t".join(cols) + "\n")
        for r in rows:
            self.out.write("\t".join(_cell(_get(r, c)) for c in cols) + "\n")

    def grid(self, rows):
        """A cell grid (list of lists): escaped TSV, or a JSON array of arrays on -j. No header."""
        if self.fields:
            raise UsageError("--fields does not apply to a cell grid; narrow with an A1 range instead")
        if self.json:
            self.out.write(json.dumps(rows, ensure_ascii=False) + "\n")
            return
        for r in rows:
            self.out.write("\t".join(grid_cell(c) for c in r) + "\n")

    def text(self, s, meta=None):
        """Raw document text (doc cat). -j: one object {**meta, "text": ...}."""
        if self.fields:
            raise UsageError("--fields does not apply to document text; use -j and pick keys")
        if self.json:
            self.out.write(json.dumps({**(meta or {}), "text": s}, ensure_ascii=False, indent=1) + "\n")
            return
        self.out.write(s if s.endswith("\n") else s + "\n")

    def note(self, msg):
        for line in str(msg).splitlines() or [""]:
            self.err.write(f"# {line}\n")
        self.err.flush()
