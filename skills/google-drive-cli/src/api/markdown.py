"""Markdown <-> Google Docs structure. Pure functions, no I/O.

Docs indices are UTF-16 code units (an emoji is 2) - every offset goes through u16()."""
import re

MONO = {"Courier New", "Roboto Mono", "Source Code Pro", "Consolas", "Courier", "Inconsolata"}
ORDERED = {"DECIMAL", "ZERO_DECIMAL", "UPPER_ALPHA", "ALPHA", "UPPER_ROMAN", "ROMAN"}
HEADING = {"TITLE": 1, **{f"HEADING_{n}": n for n in range(1, 7)}}
INLINE = re.compile(r"`([^`]+)`|\*\*(.+?)\*\*|__(.+?)__|\*(?![\s*])(.+?)\*|(?<![\w\\])_(?![\s_])(.+?)_(?!\w)"
                    r"|\[([^\]]+)\]\(([^)\s]+)\)")
TEXT_RESET = "bold,italic,underline,strikethrough,link,weightedFontFamily,baselineOffset,smallCaps"


def u16(s):
    return len(s.encode("utf-16-le")) // 2


# ---- Docs -> markdown ----------------------------------------------------------------------

def _wrap(text, mark):
    core = text.strip()
    if not core:
        return text
    lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()):]
    return f"{lead}{mark}{core}{mark}{trail}"


def inline(elements):
    out = []
    for el in elements:
        tr = el.get("textRun")
        if tr:
            t = tr.get("content", "").replace("\n", "").replace("\x0b", "\n")
            st = tr.get("textStyle", {})
            if (st.get("weightedFontFamily") or {}).get("fontFamily") in MONO and t.strip():
                t = _wrap(t, "`")
            else:
                if st.get("bold"):
                    t = _wrap(t, "**")
                if st.get("italic"):
                    t = _wrap(t, "*")
            url = (st.get("link") or {}).get("url")
            if url and t.strip():
                t = f"[{t}]({url})"
            out.append(t)
        elif "richLink" in el:
            p = el["richLink"].get("richLinkProperties", {})
            out.append(f"[{p.get('title', 'link')}]({p.get('uri', '')})")
        elif "person" in el:
            out.append(el["person"].get("personProperties", {}).get("email", "@person"))
        elif "inlineObjectElement" in el:
            out.append("[image]")
        elif "horizontalRule" in el:
            out.append("---")
    return "".join(out)


def _para_line(p, lists):
    text = inline(p.get("elements", []))
    style = p.get("paragraphStyle", {}).get("namedStyleType", "")
    if style in HEADING and text.strip():
        return "heading", "#" * HEADING[style] + " " + text.strip()
    b = p.get("bullet")
    if b is not None:
        lvl = b.get("nestingLevel", 0)
        levels = lists.get(b.get("listId"), {}).get("listProperties", {}).get("nestingLevels", [])
        glyph = levels[lvl].get("glyphType") if lvl < len(levels) else None
        return "list", "   " * lvl + ("1. " if glyph in ORDERED else "- ") + text
    return "para", text


def _cell_text(cell, lists):
    return " ".join(_para_line(e["paragraph"], lists)[1] for e in cell.get("content", []) if "paragraph" in e).strip()


def to_markdown(body, lists):
    blocks = []  # (kind, text)
    for el in body.get("content", []):
        if "paragraph" in el:
            kind, line = _para_line(el["paragraph"], lists)
            if kind == "para" and not line.strip():
                continue
            blocks.append((kind, line))
        elif "table" in el:
            rows = [[_cell_text(c, lists).replace("|", "\\|") for c in r.get("tableCells", [])]
                    for r in el["table"].get("tableRows", [])]
            if rows:
                lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                blocks.append(("table", "\n".join(lines)))
        elif "tableOfContents" in el:
            blocks.append(("para", "[table of contents]"))
    out = []
    for i, (kind, text) in enumerate(blocks):
        if i:
            out.append("\n" if kind == "list" and blocks[i - 1][0] == "list" else "\n\n")
        out.append(text)
    return "".join(out) + "\n" if out else ""


def headings(body):
    """-> [{level, text, start, end}] in document order."""
    out = []
    for el in body.get("content", []):
        p = el.get("paragraph")
        if not p:
            continue
        style = p.get("paragraphStyle", {}).get("namedStyleType", "")
        text = "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", [])).strip()
        if style in HEADING and text:
            out.append({"level": 0 if style == "TITLE" else HEADING[style], "text": text,
                        "start": el["startIndex"], "end": el["endIndex"]})
    return out


# ---- markdown -> blocks --------------------------------------------------------------------

def parse(md):
    """-> (blocks, warnings). block: {kind: heading|bullet|para|code, level, ordered, runs:[(text, style)]}"""
    blocks, warnings, para, fence = [], [], [], False

    def flush():
        if para:
            blocks.append({"kind": "para", "runs": runs(" ".join(para))})
            para.clear()

    for raw in md.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            flush()
            fence = not fence
            continue
        if fence:
            blocks.append({"kind": "code", "runs": [(raw, {"code": True})] if raw else [("", {})]})
            continue
        if not line.strip():
            flush()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            blocks.append({"kind": "heading", "level": len(m.group(1)), "runs": runs(m.group(2).strip())})
            continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            flush()
            indent = m.group(1).replace("\t", "    ")
            blocks.append({"kind": "bullet", "level": min(len(indent) // 2, 8),
                           "ordered": m.group(2)[0].isdigit(), "runs": runs(m.group(3))})
            continue
        if re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):
            flush()
            warnings.append("horizontal rule dropped (the Docs API cannot insert one)")
            continue
        if line.lstrip().startswith("|"):
            flush()
            if not re.match(r"^\s*\|[\s:|-]+\|\s*$", line):
                blocks.append({"kind": "para", "runs": runs(line.strip())})
            if "tables inserted as plain text lines" not in warnings:
                warnings.append("tables inserted as plain text lines")
            continue
        para.append(line.strip())
    flush()
    return blocks, warnings


def runs(text):
    out, pos = [], 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], {}))
        code, b1, b2, i1, i2, ltext, url = m.groups()
        if code is not None:
            out.append((code, {"code": True}))
        elif b1 or b2:
            out.append((b1 or b2, {"bold": True}))
        elif i1 or i2:
            out.append((i1 or i2, {"italic": True}))
        else:
            out.append((ltext, {"link": url}))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], {}))
    return out


# ---- blocks -> batchUpdate requests --------------------------------------------------------

def _loc(d, tab):
    if tab:
        d["tabId"] = tab
    return d


def requests(blocks, at, lead_newline, trail_newline, tab=None):
    """Insert blocks at index `at` as new paragraphs. lead_newline: at is inside an existing
    non-empty paragraph end (append). trail_newline: at is the start of an existing paragraph."""
    texts = []
    for b in blocks:
        t = "".join(r[0] for r in b["runs"])
        texts.append("\t" * b.get("level", 0) + t if b["kind"] == "bullet" else t)
    full = ("\n" if lead_newline else "") + "\n".join(texts) + ("\n" if trail_newline else "")
    reqs = [{"insertText": {"location": _loc({"index": at}, tab), "text": full}}]
    start = at + (1 if lead_newline else 0)
    end_all = at + u16(full)
    rng = lambda s, e: _loc({"startIndex": s, "endIndex": e}, tab)  # noqa: E731
    if end_all > start:
        reqs.append({"updateTextStyle": {"range": rng(start, end_all), "textStyle": {}, "fields": TEXT_RESET}})
        reqs.append({"deleteParagraphBullets": {"range": rng(start, end_all)}})
    bullets, s = [], start
    for b, t in zip(blocks, texts):
        e = s + u16(t)
        style = f"HEADING_{b['level']}" if b["kind"] == "heading" else "NORMAL_TEXT"
        reqs.append({"updateParagraphStyle": {"range": rng(s, max(e, s + 1)),
                                              "paragraphStyle": {"namedStyleType": style}, "fields": "namedStyleType"}})
        pos = s + (b.get("level", 0) if b["kind"] == "bullet" else 0)
        for text, st in b["runs"]:
            n = u16(text)
            if st and n:
                ts, fields = {}, []
                if st.get("bold"):
                    ts["bold"], fields = True, fields + ["bold"]
                if st.get("italic"):
                    ts["italic"], fields = True, fields + ["italic"]
                if st.get("link"):
                    ts["link"], fields = {"url": st["link"]}, fields + ["link"]
                if st.get("code"):
                    ts["weightedFontFamily"], fields = {"fontFamily": "Roboto Mono"}, fields + ["weightedFontFamily"]
                reqs.append({"updateTextStyle": {"range": rng(pos, pos + n), "textStyle": ts, "fields": ",".join(fields)}})
            pos += n
        if b["kind"] == "bullet":
            if bullets and bullets[-1]["ordered"] == b["ordered"] and bullets[-1]["end"] == s:
                bullets[-1]["end"] = e + 1
            else:
                bullets.append({"ordered": b["ordered"], "start": s, "end": e + 1})
        s = e + 1
    # createParagraphBullets strips the leading tabs (nesting) and shifts later indices: last group first
    for g in reversed(bullets):
        preset = "NUMBERED_DECIMAL_ALPHA_ROMAN" if g["ordered"] else "BULLET_DISC_CIRCLE_SQUARE"
        reqs.append({"createParagraphBullets": {"range": rng(g["start"], g["end"] - 1 if g["end"] - 1 > g["start"] else g["end"]),
                                                "bulletPreset": preset}})
    return reqs
