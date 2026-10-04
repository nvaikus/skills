"""Markdown (as Claude writes it) -> Telegram HTML, and a fence-aware splitter.
Pure functions, unit-tested. Telegram HTML: b i s u code pre a blockquote; escape & < >."""
import html
import re

LIMIT = 4096
TABLE_WIDTH = 34  # monospace chars that fit a phone bubble; wider tables become cards
CHUNK = 3500  # markdown budget per message; HTML tags add some, overflow falls back to plain

_FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+#.-]*)\s*$")


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def _inline(s: str) -> str:
    keep = []

    def stash(v):
        keep.append(v)
        return f"\x00{len(keep) - 1}\x00"

    s = re.sub(r"`([^`\n]+)`", lambda m: stash(f"<code>{esc(m.group(1))}</code>"), s)
    s = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)",
               lambda m: stash(f'<a href="{html.escape(m.group(2))}">{esc(m.group(1))}</a>'), s)
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\w)__(.+?)__(?!\w)", r"<b>\1</b>", s)
    s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"(?<!\w)_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)", r"<i>\1</i>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], s)


def _cells(row: str) -> list:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _table(rows: list, has_header: bool) -> str:
    """Narrow table -> aligned <pre>; wide one -> one card per row (no wrapped-grid mess on a phone)."""
    grid = [_cells(r) for r in rows]
    n = max(map(len, grid))
    grid = [g + [""] * (n - len(g)) for g in grid]
    plain = [[re.sub(r"\*\*|__|`", "", c) for c in g] for g in grid]
    widths = [max(len(g[k]) for g in plain) for k in range(n)]
    if sum(widths) + 2 * (n - 1) <= TABLE_WIDTH:
        lines = ["  ".join(c.ljust(w) for c, w in zip(g, widths)).rstrip() for g in plain]
        if has_header:
            lines.insert(1, "  ".join("─" * w for w in widths))
        return "<pre>" + esc("\n".join(lines)) + "</pre>"
    head, body = (grid[0], grid[1:]) if has_header else (None, grid)
    cards = []
    for g in body:
        card = [f"<b>{_inline(g[0])}</b>"] if g[0] else []
        for k in range(1, n):
            if g[k]:
                card.append(f"{_inline(head[k])}: {_inline(g[k])}" if head and head[k] else _inline(g[k]))
        cards.append("\n".join(card))
    return "\n\n".join(cards)


def md_to_html(md: str) -> str:
    out, quote, table = [], [], []
    header = False
    lines = md.split("\n")
    i = 0

    def flush():
        if quote:
            out.append("<blockquote>" + "\n".join(quote) + "</blockquote>")
            quote.clear()
        nonlocal header
        if table:
            out.append(_table(table, header))
            table.clear()
            header = False

    while i < len(lines):
        line = lines[i]
        m = _FENCE.match(line)
        if m:
            flush()
            j = i + 1
            while j < len(lines) and not _FENCE.match(lines[j]):
                j += 1
            code = esc("\n".join(lines[i + 1:j]))
            lang = m.group(2)
            out.append(f'<pre><code class="language-{esc(lang)}">{code}</code></pre>' if lang else f"<pre>{code}</pre>")
            i = j + 1
            continue
        s = line.strip()
        if s.startswith("|"):
            if quote:
                flush()
            if re.fullmatch(r"\|?[\s:|-]+\|?", s):  # |---|---| separator: rows above it are the header
                header = len(table) == 1
            else:
                table.append(s)
            i += 1
            continue
        if s.startswith(">"):
            if table:
                flush()
            quote.append(_inline(s[1:].lstrip()))
            i += 1
            continue
        flush()
        h = re.match(r"^#{1,6}\s+(.*)$", s)
        if h:
            out.append(f"<b>{_inline(h.group(1))}</b>")
        elif re.match(r"^\s*[-*+]\s+", line):
            indent = len(line) - len(line.lstrip())
            out.append(" " * indent + "• " + _inline(re.sub(r"^\s*[-*+]\s+", "", line)))
        elif re.fullmatch(r"\s*([-*_])(\s*\1){2,}\s*", line):
            out.append("──────")
        else:
            out.append(_inline(line))
        i += 1
    flush()
    return "\n".join(out)


def split_md(md: str, limit: int = CHUNK) -> list:
    """Split at line boundaries into chunks <= limit; a code fence cut by a split is closed
    at the end of one chunk and reopened (same language) at the start of the next."""
    chunks, cur, fence = [], [], None  # fence = opening line when inside a code block
    size = 0

    def emit():
        nonlocal cur, size
        body = "\n".join(cur)
        if fence is not None:
            body += "\n```"
        if body.strip():
            chunks.append(body)
        cur = [fence] if fence is not None else []
        size = len(fence) + 1 if fence is not None else 0

    for line in md.split("\n"):
        pieces = [line[k:k + limit - 20] for k in range(0, len(line), limit - 20)] or [""]
        for piece in pieces:
            if size + len(piece) + 1 > limit - 4 and cur:
                emit()
            cur.append(piece)
            size += len(piece) + 1
        m = _FENCE.match(line)
        if m:
            fence = None if fence is not None else line.strip()
    if cur:
        fence = None
        body = "\n".join(cur)
        if body.strip():
            chunks.append(body)
    return chunks
