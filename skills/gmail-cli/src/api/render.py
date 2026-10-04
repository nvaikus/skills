"""Message payload -> compact markdown: body text (HTML converted), quoted replies and signatures
stripped, attachments listed by number. Pure functions, no I/O."""
import base64
import html
import re
from html.parser import HTMLParser

from . import mail

# ---- payload --------------------------------------------------------------------------------------


def b64(data):
    return base64.urlsafe_b64decode((data or "") + "=" * (-len(data or "") % 4))


def _hdr(part, name):
    for h in part.get("headers", []):
        if h["name"].lower() == name:
            return h["value"]
    return ""


def walk(part):
    yield part
    for p in part.get("parts", []) or []:
        yield from walk(p)


def attachments(payload):
    """Every part with a filename, numbered 1.. in tree order (the numbers `attachment get` takes).
    inline = an embedded image (signature logos etc.)."""
    out = []
    for p in walk(payload or {}):
        name = p.get("filename")
        if not name:
            continue
        disp = _hdr(p, "content-disposition").lower()
        inline = (disp.startswith("inline") or (not disp and bool(_hdr(p, "content-id")))) \
            and (p.get("mimeType") or "").startswith("image/")
        out.append({"n": len(out) + 1, "name": name, "size": (p.get("body") or {}).get("size", 0),
                    "type": p.get("mimeType"), "inline": inline, "part": p})
    return out


# Single-byte charsets a mislabeled UTF-8 body hides behind (ActivoBank: header ISO-8859-15, body and
# <meta charset> UTF-8). Valid multi-byte UTF-8 is near-impossible by chance in these, so it wins.
_SINGLE_BYTE = re.compile(r"^(us-?ascii|ascii|latin[-_]?\d*|l\d|iso[-_]?8859[-_]?\d+|(windows|cp)[-_]?125\d|koi8[-_]?[ru]|"
                          r"mac[-_]?roman|ansi_x3\.4-1968)$", re.I)
# UTF-8 shown as Latin-1/cp1252 characters ("sÃ£o"): well-formed lead + continuation sequences only.
_CONT = ("[\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013\u2014"
         "\u2018-\u201e\u2020-\u2022\u2026\u2030\u2039\u203a\u20ac\u2122]")
_MOJIBAKE = re.compile(f"(?:[\u00c2-\u00df]{_CONT}|[\u00e0-\u00ef]{_CONT}{{2}}|[\u00f0-\u00f4]{_CONT}{{3}})+")


def _charset(part):
    m = re.search(r'charset\s*=\s*"?([\w.:-]+)', _hdr(part, "content-type"), re.I)
    return m.group(1) if m else ""


def _unmojibake(text):
    """Repair UTF-8 that was decoded as Latin-1/cp1252 upstream (by the sender): run by run, only
    where re-encoding gives valid UTF-8, so genuine Latin-1 text stays as it is."""
    def fix(m):
        run = m.group(0)
        for enc in ("cp1252", "latin-1"):
            try:
                return run.encode(enc).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        return run
    return _MOJIBAKE.sub(fix, text)


def decode_text(raw, charset=""):
    """Body bytes -> str. Honors the declared charset, except that bytes which are valid non-ASCII
    UTF-8 under a missing or single-byte label are UTF-8 (the label is wrong, not the bytes)."""
    cs = (charset or "").strip().lower()
    if not cs or _SINGLE_BYTE.match(cs):
        try:
            return _unmojibake(raw.decode("utf-8"))
        except UnicodeDecodeError:
            if not cs or "ascii" in cs or cs == "ansi_x3.4-1968":
                cs = "cp1252"  # 8-bit bytes with no real label: the common Western default
    try:
        text = raw.decode(cs, "replace")
    except LookupError:
        text = raw.decode("utf-8", "replace")
    return _unmojibake(text)


def _decode(part):
    return decode_text(b64((part.get("body") or {}).get("data")), _charset(part))


def bodies(payload):
    """-> (plain, html) of the first non-attachment text parts."""
    plain = htm = None
    for p in walk(payload or {}):
        if p.get("filename"):
            continue
        mt = p.get("mimeType")
        if mt == "text/plain" and plain is None and (p.get("body") or {}).get("data"):
            plain = _decode(p)
        elif mt == "text/html" and htm is None and (p.get("body") or {}).get("data"):
            htm = _decode(p)
    return plain, htm


# ---- HTML -> text ----------------------------------------------------------------------------------

BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "hr",
         "section", "article", "header", "footer", "pre", "dd", "dt"}
DROP = {"style", "script", "head", "title", "noscript", "template"}
VOID = {"br", "hr", "img", "meta", "link", "input", "col", "area", "base", "wbr", "source"}
SIG_CLASS = re.compile(r"\b(gmail_signature|moz-signature)\b")
CUT_ID = re.compile(r"^(divRplyFwdMsg|appendonsend|mail-editor-reference-message-container)$")


class _Text(HTMLParser):
    def __init__(self, keep_quotes):
        super().__init__(convert_charrefs=True)
        self.out, self.keep = [], keep_quotes
        self.drop = 0          # inside style/script/signature
        self.stack = []        # (tag, dropping?, quote?)
        self.quote = 0
        self.cut = False       # Outlook reply header reached: everything after is the quoted mail
        self.href = None
        self.link_text = []

    def _emit(self, s):
        if self.drop or self.cut:
            return
        if self.href is not None:
            self.link_text.append(s)
            return
        self.out.append(s)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if not self.keep and (CUT_ID.match(a.get("id") or "") or tag == "hr" and a.get("id") == "stopSpelling"):
            self.cut = True
        dropping = tag in DROP or (not self.keep and bool(SIG_CLASS.search(a.get("class") or "")))
        quote = tag == "blockquote"
        if tag not in VOID:
            self.stack.append((tag, dropping, quote))
        if dropping:
            self.drop += 1
        if quote:
            self.quote += 1
            self._emit("\n")
        if tag in BLOCK:
            self._emit("\n")
        if tag == "li":
            self._emit("- ")
        elif tag in ("td", "th"):
            self._emit(" | ")
        elif tag == "a" and a.get("href") and not self.drop:
            self.href, self.link_text = a["href"], []
        elif tag == "img" and a.get("alt") and len(a["alt"]) < 60:
            self._emit(f"[{a['alt']}]")

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            text = " ".join("".join(self.link_text).split())
            href, self.href = self.href, None
            if href.startswith("mailto:") or not text or text == href or len(href) > 120:
                self._emit(text or (href if len(href) <= 120 else ""))
            else:
                self._emit(f"[{text}]({href})")
        if tag in VOID:
            return
        while self.stack:
            t, dropping, quote = self.stack.pop()
            if dropping:
                self.drop -= 1
            if quote:
                self.quote -= 1
                self._emit("\n")
            if t == tag:
                break
        if tag in BLOCK:
            self._emit("\n")

    def handle_data(self, data):
        text = re.sub(r"[ \t\r\n ]+", " ", data)
        if self.quote and not self.drop and not self.cut and self.href is None:
            self.out.append(("Q", text))  # quoted: prefixed with "> " after joining
            return
        self._emit(text)


def html_to_text(src, keep_quotes=False):
    p = _Text(keep_quotes)
    p.feed(src)
    p.close()
    lines, cur, cur_q = [], [], False
    for piece in p.out:
        q = isinstance(piece, tuple)
        s = piece[1] if q else piece
        parts = s.split("\n")
        for i, seg in enumerate(parts):
            if i:
                lines.append(("> " if cur_q else "") + "".join(cur).strip())
                cur, cur_q = [], False
            if seg.strip():
                cur_q = cur_q or q
            cur.append(seg)
    lines.append(("> " if cur_q else "") + "".join(cur).strip())
    text = "\n".join(re.sub(r" {2,}", " ", ln).replace(" | ", " | ").strip() for ln in lines)
    text = re.sub(r"^\s*\|\s*", "", text, flags=re.M)
    return _unmojibake(re.sub(r"\n{3,}", "\n\n", text).strip())  # entity-encoded mojibake (&Atilde;&pound;)


# ---- quotes / signatures ---------------------------------------------------------------------------

WROTE = re.compile(r"(wrote|написал\(а\)|написала|написал|пишет|escreveu|escribió|schrieb|a écrit|ha scritto|schreef"
                   r"|napisał\(a\)|napisał)\s*:\s*$", re.I)
ON = re.compile(r"^(On|Em|El|Am|Le|Il|Op|W dniu|\d{1,2}[./]\d{1,2}[./]\d{2,4}|\w{2,3},? \d{1,2} \w+\.? \d{4})\b", re.I)
ORIGINAL = re.compile(r"^\s*-{2,}\s*(Original Message|Исходное сообщение|Mensagem original|Ursprüngliche Nachricht)", re.I)
HDR_FROM = re.compile(r"^\s*\*?(From|От|De|Von)\s*:\*?\s", re.I)
HDR_NEXT = re.compile(r"^\s*\*?(Sent|Date|Отправлено|Дата|Enviado|Enviada|Gesendet|To|Кому|Para|An|Subject|Тема)\s*:", re.I)
ADDR_COLON = re.compile(r"@[\w.-]+>?\s*:\s*$")  # "вт, 4 мар. 2026 г. в 09:12, Анна <a@x.com>:"
SIG = re.compile(r"^(-- ?|—)$")
MOBILE = re.compile(r"^(Sent from my \w+|Get Outlook for \w+|Отправлено с (iPhone|iPad|Android)|Enviado do meu \w+)", re.I)
FWD_SUBJECT = re.compile(r"^\s*(fwd?|fw|пересл\.?|tr|wg|rv|enc)\s*:", re.I)


def _quoted_next(lines, i):
    rest = [x.strip() for x in lines[i + 1:i + 4] if x.strip()]
    return bool(rest) and rest[0].startswith(">")


def strip(text, subject=""):
    """Drop quoted replies (Gmail/Apple/Outlook styles, several languages) and the signature.
    A forward keeps its forwarded part. -> (text, removed_anything)."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fwd = bool(FWD_SUBJECT.match(subject or ""))
    out, cut = [], False
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        s = ln.strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if WROTE.search(s) and not s.startswith(">") and (ON.match(s) or _quoted_next(lines, i)):
            cut = True
            break
        if ADDR_COLON.search(s) and not s.startswith(">") and _quoted_next(lines, i):
            cut = True
            break
        if ON.match(s) and WROTE.search(nxt) and not fwd:
            cut = True
            break
        if ORIGINAL.match(s):
            cut = True
            break
        if not fwd and HDR_FROM.match(s) and any(HDR_NEXT.match(x.strip()) for x in lines[i + 1:i + 4]) \
                and (not out or not out[-1].strip() or set(out[-1].strip()) <= set("_-")):
            cut = True
            break
        if SIG.match(s):
            cut = True
            break
        if MOBILE.match(s):
            cut = True
            i += 1
            continue
        if s.startswith(">"):
            cut = True
            if out and out[-1] == "> …":
                i += 1
                continue
            out.append("> …")
            i += 1
            continue
        out.append(ln)
        i += 1
    while out and (not out[-1].strip() or out[-1] == "> …" or set(out[-1].strip()) <= set("_-")):
        out.pop()
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return body, cut


def body_text(payload, full=False, subject=""):
    """-> (text, stripped?) of one message."""
    plain, htm = bodies(payload)
    if plain and plain.strip():
        text = plain
    elif htm:
        text = html_to_text(htm, keep_quotes=full)
    else:
        text = ""
    text = re.sub(r"[ \t]+\n", "\n", text.replace("\r\n", "\n")).strip()
    if full:
        return text, False
    return strip(text, subject)


# ---- markdown ---------------------------------------------------------------------------------------

def size(n):
    n = int(n or 0)
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024


def message_md(msg, names, idx=None, full=False, max_chars=6000, me=None):
    """One message as a markdown section."""
    h = mail.headers(msg.get("payload"))
    head = f"## {idx}. " if idx else "## "
    head += f"{mail.short_addr(h.get('from'))} · {mail.when(msg.get('internalDate'))}"
    lines = [head]
    rcpt = [f"to: {h['to']}"] if h.get("to") else []
    if h.get("cc"):
        rcpt.append(f"cc: {h['cc']}")
    if h.get("bcc"):
        rcpt.append(f"bcc: {h['bcc']}")
    labs = ",".join(mail.show_label(x, names) for x in msg.get("labelIds", []))
    lines.append(" · ".join(rcpt + [f"id: {msg['id']}"] + ([f"labels: {labs}"] if labs else [])))
    text, stripped = body_text(msg.get("payload"), full, h.get("subject", ""))
    if max_chars and len(text) > max_chars:
        cut = len(text) - max_chars
        text = text[:max_chars].rstrip() + f"\n[… {cut} more chars: gmail read {msg['id']} --message --max 0]"
    lines += ["", text or "(no text)"]
    if stripped:
        lines.append("[quoted text / signature hidden: --full shows it]")
    atts = attachments(msg.get("payload"))
    shown = [a for a in atts if not a["inline"]]
    inline = len(atts) - len(shown)
    if shown or inline:
        lines.append("")
        lines.append("attachments (gmail attachment get " + msg["id"] + " N):")
        lines += [f"- {a['n']}. {a['name']} · {size(a['size'])} · {a['type']}" for a in shown]
        if inline:
            lines.append(f"- (+{inline} inline image{'s' if inline > 1 else ''})")
    return "\n".join(lines)


def thread_md(thread, names, prof, full=False, max_chars=6000, only=None):
    msgs = thread.get("messages", [])
    if only:
        msgs = [m for m in msgs if m["id"] == only]
    first = mail.headers(msgs[0].get("payload")) if msgs else {}
    labs = sorted({x for m in thread.get("messages", []) for x in m.get("labelIds", [])})
    out = [f"# {first.get('subject') or '(no subject)'}",
           f"thread: {thread.get('id')} · profile: {prof} · {len(thread.get('messages', []))} message"
           f"{'s' if len(thread.get('messages', [])) != 1 else ''} · labels: "
           + ",".join(mail.show_label(x, names) for x in labs)]
    for i, m in enumerate(msgs, 1):
        out += ["", message_md(m, names, None if only else i, full, max_chars)]
    return "\n".join(out) + "\n"
