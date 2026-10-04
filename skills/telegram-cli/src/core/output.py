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
    """Dotted paths: --fields chat.id reads row['chat']['id']."""
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

    def note(self, msg):
        for line in str(msg).splitlines() or [""]:
            self.err.write(f"# {line}\n")
        self.err.flush()
