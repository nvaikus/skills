#!/usr/bin/env python3
"""Jira rich text (ADF json) <-> a compact markdown dialect.

  adf.py to-adf [FILE]    markdown -> ADF doc json
  adf.py to-md  [FILE]    ADF -> markdown; the input may be any JSON that
                          holds a {"type": "doc"} node (raw acli --json works)
  adf.py check  FILE...   round-trip proof for ADF docs: to-md must give the
                          same markdown on passes 1, 2 and 3

FILE omitted -> stdin. to-md is strict: a node or mark outside the dialect
-> exit 1, the offending types on stderr, nothing on stdout.

Dialect (blocks are separated by blank lines):
  # .. ###### text {#rrggbb}  heading, level 1-6, optional text color
  ```lang ... ```             code block, verbatim
  - item  /  1. item          lists. Lines indented under an item are its own
                              blocks: more paragraphs, nested lists, code,
                              tables. One single-line numbered item stays a
                              plain paragraph ("3. Step title" keeps its
                              number); two or more make a list
  | a | b |                   table; the 2nd line is the | --- | separator.
  | --- | --- |               An all-blank header line = headerless table.
                              <br> splits a cell into blocks, \\| is a pipe
  ![alt](media-id =WxH)       image, on its own line or as a whole table
                              cell. media-id = the attachment's media UUID
                              (not its file name, not its attachment id)
  **b** *i* `code` [t](url)   inline marks, one per span (ADF forbids code
                              combined with any other mark)
  @[Name](accountId)          mention
  <br>                        hard line break
  \\- \\# \\| \\` \\! 3\\.          leading backslash: the line is plain text

Normalized on the way to markdown (stable after one pass): smart links ->
[url](url); underline and non-heading text colors dropped; mediaGroup ->
one image per line; table cells flattened to <br>-joined paragraphs; a
one-item numbered list -> numbered paragraph.
"""
import argparse
import difflib
import json
import re
import sys

LITERAL = "-#|`!"

SPAN = re.compile(
    r"@\[(?P<who>[^\]]+)\]\((?P<acc>[^)\s]+)\)"
    r"|\[(?P<label>[^\]]+)\]\((?P<href>[^)\s]+)\)"
    r"|\*\*(?P<strong>.+?)\*\*"
    r"|\*(?P<em>[^*]+?)\*"
    r"|`(?P<code>[^`]+)`"
    r"|(?P<br><[bB][rR]\s*/?>)")
BREAK = re.compile(r"<br\s*/?>", re.I)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+\{(#[0-9A-Fa-f]{6})\})?\s*$")
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
BULLET = re.compile(r"^-(?:\s+|$)")
NUMBERED = re.compile(r"^(\d+)\.(?:\s+|$)")
ESCAPED_NUMBER = re.compile(r"^(\d+)\\\.")
IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)(?:\s+=(\d+)x(\d+))?\)\s*$")
RULER = re.compile(r"^:?-+:?$")
LISTS = ("bulletList", "orderedList")


class Outside(Exception):
    """ADF content the dialect cannot express."""


# ---------------------------------------------------------------- md -> ADF

def text_node(value, mark=None):
    node = {"type": "text", "text": value}
    if mark:
        node["marks"] = [mark]
    return node


def spans(text):
    nodes, at = [], 0
    for m in SPAN.finditer(text):
        if m.start() > at:
            nodes.append(text_node(text[at:m.start()]))
        g = m.groupdict()
        if g["who"] is not None:
            nodes.append({"type": "mention",
                          "attrs": {"id": g["acc"], "text": "@" + g["who"]}})
        elif g["label"] is not None:
            nodes.append(text_node(g["label"], {"type": "link",
                                                "attrs": {"href": g["href"]}}))
        elif g["br"] is not None:
            nodes.append({"type": "hardBreak"})
        else:
            kind = next(k for k in ("strong", "em", "code") if g[k] is not None)
            nodes.append(text_node(g[kind], {"type": kind}))
        at = m.end()
    if at < len(text):
        nodes.append(text_node(text[at:]))
    return nodes


def paragraph(text):
    if text[:1] == "\\" and text[1:2] in LITERAL:
        text = text[1:]
    else:
        text = ESCAPED_NUMBER.sub(r"\1.", text, count=1)
    return {"type": "paragraph", "content": spans(text)}


def heading(m):
    level, text, color = len(m.group(1)), m.group(2), m.group(3)
    content = spans(text)
    if color:
        for node in content:
            marks = node.get("marks", [])
            if node["type"] == "text" and all(k["type"] != "code" for k in marks):
                node["marks"] = marks + [{"type": "textColor",
                                          "attrs": {"color": color}}]
    return {"type": "heading", "attrs": {"level": level}, "content": content}


def picture(m):
    alt, ident, width, height = m.groups()
    media = {"type": "file", "id": ident, "collection": ""}
    single = {"layout": "center"}
    if alt:
        media["alt"] = alt
    if width:
        media.update(width=int(width), height=int(height))
        single.update(width=int(width), widthType="pixel")
    return {"type": "mediaSingle", "attrs": single,
            "content": [{"type": "media", "attrs": media}]}


def code_block(lang, lines):
    node = {"type": "codeBlock"}
    if lang:
        node["attrs"] = {"language": lang}
    body = "\n".join(lines)
    if body:
        node["content"] = [text_node(body)]
    return node


def row_cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def starts_table(lines, i):
    return (lines[i].lstrip().startswith("|") and i + 1 < len(lines)
            and lines[i + 1].lstrip().startswith("|")
            and all(RULER.match(c) for c in row_cells(lines[i + 1])))


def cell_content(text):
    out = []
    for part in BREAK.split(text):
        part = part.strip()
        if part:
            m = IMAGE.match(part)
            out.append(picture(m) if m else paragraph(part))
    return out or [paragraph("")]


def table(head, rows):
    width = max(len(r) for r in [head] + rows)

    def row(values, kind):
        values = values + [""] * (width - len(values))
        return {"type": "tableRow",
                "content": [{"type": kind, "content": cell_content(v)}
                            for v in values]}

    content = [row(head, "tableHeader")] if any(head) else []
    content += [row(r, "tableCell") for r in rows]
    if not content:
        return paragraph("")
    return {"type": "table",
            "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
            "content": content}


def opens_block(lines, i):
    line = lines[i]
    return bool(line.startswith("```") or HEADING.match(line)
                or IMAGE.match(line) or BULLET.match(line)
                or NUMBERED.match(line) or starts_table(lines, i))


def take_list(lines, i):
    ordered = bool(NUMBERED.match(lines[i]))
    marker = NUMBERED if ordered else BULLET
    start = int(NUMBERED.match(lines[i]).group(1)) if ordered else 1
    first_line, items, flat = lines[i], [], True
    while i < len(lines):
        m = marker.match(lines[i])
        if not m:
            break
        body, blanks = [lines[i][m.end():]], 0
        i += 1
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                blanks += 1
            elif line[0] in " \t":
                body += [""] * blanks + [line]
                blanks = 0
            else:
                break
            i += 1
        nested = body[1:]
        if nested:
            flat = False
            cut = min(len(x) - len(x.lstrip()) for x in nested if x.strip())
            body = body[:1] + [x[cut:] if x.strip() else "" for x in nested]
        items.append({"type": "listItem",
                      "content": parse(body) or [paragraph("")]})
    if ordered and len(items) == 1 and flat:
        return paragraph(first_line), i
    if ordered:
        return {"type": "orderedList", "attrs": {"order": start},
                "content": items}, i
    return {"type": "bulletList", "content": items}, i


def parse(lines):
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            lang, body = line[3:].strip(), []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            out.append(code_block(lang, body))
            i += 1
            continue
        m = HEADING.match(line) or IMAGE.match(line)
        if m:
            out.append(heading(m) if m.re is HEADING else picture(m))
            i += 1
            continue
        if starts_table(lines, i):
            head, rows = row_cells(line), []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(row_cells(lines[i]))
                i += 1
            out.append(table(head, rows))
            continue
        if BULLET.match(line) or NUMBERED.match(line):
            node, i = take_list(lines, i)
            out.append(node)
            continue
        buf = []
        while (i < len(lines) and lines[i].strip()
               and not (buf and opens_block(lines, i))):
            buf.append(lines[i].strip())
            i += 1
        out.append(paragraph(" ".join(buf)))
    return out


def to_adf(markdown):
    return {"type": "doc", "version": 1,
            "content": parse(markdown.splitlines())}


# ---------------------------------------------------------------- ADF -> md

def find_doc(obj):
    if isinstance(obj, dict):
        if obj.get("type") == "doc" and "content" in obj:
            return obj
        obj = list(obj.values())
    if isinstance(obj, list):
        for value in obj:
            doc = find_doc(value)
            if doc is not None:
                return doc
    return None


def escape_lead(s):
    """Backslash a paragraph that markdown would read as a block opener."""
    if NUMBERED.match(s) or ESCAPED_NUMBER.match(s):
        digits = re.match(r"\d+", s).end()
        return s[:digits] + "\\" + s[digits:].lstrip("\\")
    if (s[:1] == "\\" and s[1:2] in LITERAL) or opens_block([s], 0):
        return "\\" + s
    return s


class Markdown:
    WRAP = {"strong": "**%s**", "em": "*%s*", "code": "`%s`"}

    def __init__(self):
        self.outside = set()

    def miss(self, what):
        self.outside.add(what)
        return ""

    def text(self, node):
        value = node.get("text", "").replace("\n", "<br>")
        marks = [m for m in node.get("marks") or []
                 if m.get("type") not in ("underline", "textColor")]
        if not marks:
            return value
        if len(marks) > 1:
            return self.miss("stacked marks "
                             + "+".join(sorted(m.get("type", "?") for m in marks)))
        mark = marks[0]
        kind = mark.get("type")
        if kind in self.WRAP:
            return self.WRAP[kind] % value
        if kind == "link":
            return "[%s](%s)" % (value, (mark.get("attrs") or {}).get("href", ""))
        return self.miss("mark %s" % kind)

    def inline(self, nodes):
        out = []
        for node in nodes or []:
            kind, attrs = node.get("type"), node.get("attrs") or {}
            if kind == "text":
                out.append(self.text(node))
            elif kind == "hardBreak":
                out.append("<br>")
            elif kind == "mention":
                name = (attrs.get("text") or "@?").lstrip("@")
                out.append("@[%s](%s)" % (name, attrs.get("id", "")))
            elif kind == "inlineCard":
                url = attrs.get("url") or (attrs.get("data") or {}).get("url")
                out.append("[%s](%s)" % (url, url) if url
                           else self.miss("inlineCard without url"))
            else:
                out.append(self.miss("inline node %s" % kind))
        return "".join(out).strip()

    def heading(self, node):
        content = node.get("content") or []
        level = int((node.get("attrs") or {}).get("level", 1))
        line = "#" * max(1, min(level, 6)) + " " + self.inline(content)
        colors = [(m.get("attrs") or {}).get("color", "")
                  for t in content if t.get("type") == "text"
                  for m in t.get("marks") or [] if m.get("type") == "textColor"]
        if colors and COLOR.match(colors[0]):
            line += " {%s}" % colors[0]
        return line

    def item(self, node, marker):
        blocks = [(c.get("type"), self.block(c)) for c in node.get("content") or []]
        blocks = [(kind, md) for kind, md in blocks if md.strip()]
        lead = ""
        if blocks and blocks[0][0] == "paragraph":
            lead = blocks.pop(0)[1]
        lines, pad = [(marker + lead).rstrip()], " " * len(marker)
        for kind, md in blocks:
            if kind not in LISTS:
                lines.append("")
            lines.append("\n".join(pad + ln if ln.strip() else ""
                                   for ln in md.split("\n")))
        return "\n".join(lines)

    def ordered(self, node):
        start = int((node.get("attrs") or {}).get("order", 1))
        items = node.get("content") or []
        md = "\n".join(self.item(li, "%d. " % (start + k))
                       for k, li in enumerate(items))
        if len(items) == 1 and "\n" not in md:
            return escape_lead(md)  # parses back as a paragraph anyway
        return md

    def cell(self, node):
        parts = (self.block(b, top=False).replace("\n", "<br>").strip()
                 for b in node.get("content") or [])
        return "<br>".join(p for p in parts if p).replace("|", "\\|")

    def table(self, node):
        rows = []
        for row in node.get("content") or []:
            if row.get("type") != "tableRow":
                self.miss("table child %s" % row.get("type"))
                continue
            kinds, values = [], []
            for cell in row.get("content") or []:
                kind, attrs = cell.get("type"), cell.get("attrs") or {}
                if kind not in ("tableCell", "tableHeader"):
                    self.miss("table row child %s" % kind)
                    continue
                if (attrs.get("colspan") or 1) > 1 or (attrs.get("rowspan") or 1) > 1:
                    self.miss("merged table cell")
                kinds.append(kind)
                values.append(self.cell(cell))
            if values:
                rows.append((kinds, values))
        if not rows:
            return ""
        width = max(len(v) for _, v in rows)
        for _, values in rows:
            values += [""] * (width - len(values))
        if all(k == "tableHeader" for k in rows[0][0]):
            head, body = rows[0][1], [v for _, v in rows[1:]]
        else:
            head, body = [""] * width, [v for _, v in rows]

        def line(values):
            return "| " + " | ".join(values) + " |"

        return "\n".join([line(head), line(["---"] * width)]
                         + [line(v) for v in body])

    def media(self, node):
        out = []
        for child in node.get("content") or []:
            attrs = child.get("attrs") or {}
            if child.get("type") != "media":
                self.miss("media container child %s" % child.get("type"))
            elif not attrs.get("id"):
                self.miss("media without id")
            else:
                size = ""
                if attrs.get("width") and attrs.get("height"):
                    size = " =%dx%d" % (attrs["width"], attrs["height"])
                out.append("![%s](%s%s)" % (attrs.get("alt", ""), attrs["id"], size))
        return "\n\n".join(out)

    def block(self, node, top=True):
        kind = node.get("type")
        if kind == "paragraph":
            md = self.inline(node.get("content"))
            return escape_lead(md) if top else md
        if kind == "heading":
            return self.heading(node)
        if kind == "codeBlock":
            body = "".join(c.get("text", "") for c in node.get("content") or [])
            lang = (node.get("attrs") or {}).get("language") or ""
            return "```%s\n%s\n```" % (lang, body)
        if kind == "bulletList":
            return "\n".join(self.item(li, "- ") for li in node.get("content") or [])
        if kind == "orderedList":
            return self.ordered(node)
        if kind == "table":
            return self.table(node)
        if kind in ("mediaSingle", "mediaGroup"):
            return self.media(node)
        return self.miss("block node %s" % kind)


def to_md(data):
    doc = find_doc(data)
    if doc is None:
        raise Outside("no ADF doc node in the input")
    render = Markdown()
    blocks = [b for b in (render.block(n) for n in doc.get("content") or [])
              if b.strip()]
    if render.outside:
        raise Outside("outside the dialect: " + "; ".join(sorted(render.outside))
                      + "\nextend both directions in adf.py, then retry")
    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------- CLI

def read(path):
    if path in (None, "-"):
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def check(paths):
    ok = True
    for path in paths:
        adf, passes = json.loads(read(path)), []
        for _ in range(3):
            passes.append(to_md(adf))
            adf = to_adf(passes[-1])
        if passes[0] == passes[1] == passes[2]:
            print("OK    %s" % path)
            continue
        ok = False
        print("DIFF  %s" % path)
        for a, b, tag in ((passes[0], passes[1], "pass 1->2"),
                          (passes[1], passes[2], "pass 2->3")):
            if a != b:
                print("".join(difflib.unified_diff(
                    a.splitlines(True), b.splitlines(True), tag, tag)))
    return 0 if ok else 1


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        prog="adf.py", description=__doc__.split("\n\n")[0],
        epilog=__doc__.split("\n\n", 1)[1],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("to-adf", help="markdown -> ADF json").add_argument("file", nargs="?")
    sub.add_parser("to-md", help="ADF -> markdown").add_argument("file", nargs="?")
    sub.add_parser("check", help="round-trip proof").add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "to-adf":
            json.dump(to_adf(read(args.file)), sys.stdout, ensure_ascii=False)
        elif args.cmd == "to-md":
            sys.stdout.write(to_md(json.loads(read(args.file))))
        else:
            return check(args.files)
    except Outside as err:
        print("adf.py: %s" % err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
