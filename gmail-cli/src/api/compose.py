"""Outgoing mail: build RFC 822 messages (text, optional HTML from markdown, attachments, reply
headers), create/update/send drafts, send. Large messages go through the upload endpoint."""
import base64
import html
import json
import mimetypes
import re
import secrets
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, getaddresses, make_msgid
from pathlib import Path

from ..core.errors import UsageError
from . import google, mail

RAW_LIMIT = 4_500_000  # above this the JSON 'raw' body is refused; the upload endpoint takes up to 35 MB
_me = {}


def me(prof):
    if prof not in _me:
        _me[prof] = (google.get(prof, "/profile") or {}).get("emailAddress", "")
    return _me[prof]


# ---- markdown -> HTML (the subset people write in mail) ------------------------------------------

def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+|mailto:[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<i>\1</i>", s)
    return s


def md_to_html(md):
    out, para, lst = [], [], None

    def flush():
        nonlocal para, lst
        if para:
            out.append("<p>" + "<br>\n".join(_inline(x) for x in para) + "</p>")
            para = []
        if lst:
            tag, items = lst
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + f"</{tag}>")
            lst = None

    for ln in md.replace("\r\n", "\n").split("\n"):
        s = ln.rstrip()
        h = re.match(r"^(#{1,6})\s+(.*)", s)
        b = re.match(r"^\s*[-*+]\s+(.*)", s)
        n = re.match(r"^\s*\d+[.)]\s+(.*)", s)
        if not s.strip():
            flush()
        elif h:
            flush()
            out.append(f"<h{len(h.group(1))}>{_inline(h.group(2))}</h{len(h.group(1))}>")
        elif b or n:
            tag = "ul" if b else "ol"
            if para or (lst and lst[0] != tag):
                flush()
            lst = lst or (tag, [])
            lst[1].append((b or n).group(1))
        else:
            if lst:
                flush()
            para.append(s)
    flush()
    return "<div>" + "\n".join(out) + "</div>"


# ---- build --------------------------------------------------------------------------------------

def _addrs(value):
    """'a@x, B <b@y>' -> header string; '' -> None."""
    pairs = [(n, a) for n, a in getaddresses([value or ""]) if a]
    if not pairs:
        return None
    for _, a in pairs:
        if "@" not in a:
            raise UsageError(f"not an email address: {a!r}")
    return ", ".join(f"{n} <{a}>" if n else a for n, a in pairs)


def attach_file(msg, path):
    p = Path(path).expanduser()
    if not p.is_file():
        raise UsageError(f"--attach {path}: no such file")
    ctype, enc = mimetypes.guess_type(p.name)
    if not ctype or enc:
        ctype = "application/octet-stream"
    main, sub = ctype.split("/", 1)
    msg.add_attachment(p.read_bytes(), maintype=main, subtype=sub, filename=p.name)


def build(to=None, cc=None, bcc=None, subject="", body="", markdown=False, attach=(), sender=None,
          reply=None, keep=()):
    """-> EmailMessage. reply: reply_context(...) dict. keep: [(filename, bytes, ctype)] carried over."""
    msg = EmailMessage(policy=policy.SMTP)
    for name, val in (("From", sender), ("To", to), ("Cc", cc), ("Bcc", bcc)):
        v = _addrs(val) if val else None
        if v:
            msg[name] = v
    msg["Subject"] = subject or ""
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gmail-cli.local")
    if reply:
        if reply.get("in_reply_to"):
            msg["In-Reply-To"] = reply["in_reply_to"]
        if reply.get("references"):
            msg["References"] = reply["references"]
    body = body or ""
    msg.set_content(body if body.endswith("\n") or not body else body + "\n")
    if markdown:
        msg.add_alternative(md_to_html(body), subtype="html")
    for fname, data, ctype in keep:
        main, sub = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(data, maintype=main, subtype=sub, filename=fname)
    for path in attach or ():
        attach_file(msg, path)
    return msg


def reply_context(prof, mid, reply_all=False):
    """Headers of the message being answered -> {thread_id, to, cc, subject, in_reply_to, references}."""
    m = google.get(prof, f"/messages/{mid}", {"format": "metadata", "metadataHeaders":
                   ["Message-ID", "References", "Subject", "From", "Reply-To", "To", "Cc"]})
    h = mail.headers(m.get("payload"))
    mine = me(prof).lower()
    frm = h.get("reply-to") or h.get("from") or ""
    from_me = any(a.lower() == mine for _, a in getaddresses([h.get("from", "")]))
    to = h.get("to", "") if from_me else frm
    cc = ""
    if reply_all:
        seen = {a.lower() for _, a in getaddresses([to])} | {mine}
        rest = []
        for n, a in getaddresses([h.get("to", ""), h.get("cc", "")]):
            if a and a.lower() not in seen:
                seen.add(a.lower())
                rest.append(f"{n} <{a}>" if n else a)
        cc = ", ".join(rest)
    subj = h.get("subject", "")
    if not re.match(r"^\s*re\s*:", subj, re.I):
        subj = f"Re: {subj}".strip()
    mid_hdr = h.get("message-id", "")
    refs = " ".join(x for x in (h.get("references", ""), mid_hdr) if x).strip()
    return {"thread_id": m.get("threadId"), "to": to, "cc": cc, "subject": subj,
            "in_reply_to": mid_hdr or None, "references": refs or None}


def parse_raw(raw_b64):
    return BytesParser(policy=policy.SMTP).parsebytes(base64.urlsafe_b64decode(raw_b64 + "=" * (-len(raw_b64) % 4)))


def parts_of(msg):
    """Parsed message -> (plain body, html body or None, [(filename, bytes, ctype)])."""
    plain = msg.get_body(preferencelist=("plain",))
    htm = msg.get_body(preferencelist=("html",))
    atts = [(a.get_filename() or "attachment", a.get_content() if isinstance(a.get_content(), bytes)
             else a.get_content().encode(), a.get_content_type()) for a in msg.iter_attachments()]
    return (plain.get_content() if plain else ""), (htm.get_content() if htm else None), atts


# ---- Gmail calls --------------------------------------------------------------------------------

def _payload(msg):
    return msg.as_bytes()


def _upload(prof, method, path, meta, data):
    boundary = "gmailcli" + secrets.token_hex(8)
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: message/rfc822\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return google.mutate(prof, method, path, params={"uploadType": "multipart"}, data=body,
                         content_type=f"multipart/related; boundary={boundary}", base=google.UPLOAD)


def _message_obj(data, thread_id):
    m = {"raw": base64.urlsafe_b64encode(data).decode()}
    if thread_id:
        m["threadId"] = thread_id
    return m


def create_draft(prof, msg, thread_id=None):
    data = _payload(msg)
    if len(data) > RAW_LIMIT:
        return _upload(prof, "POST", "/drafts", {"message": {"threadId": thread_id} if thread_id else {}}, data)
    return google.mutate(prof, "POST", "/drafts", {"message": _message_obj(data, thread_id)})


def update_draft(prof, did, msg, thread_id=None):
    data = _payload(msg)
    if len(data) > RAW_LIMIT:
        meta = {"id": did, "message": {"threadId": thread_id} if thread_id else {}}
        return _upload(prof, "PUT", f"/drafts/{did}", meta, data)
    return google.mutate(prof, "PUT", f"/drafts/{did}", {"id": did, "message": _message_obj(data, thread_id)})


def send_draft(prof, did):
    return google.mutate(prof, "POST", "/drafts/send", {"id": did})


def delete_draft(prof, did):
    return google.mutate(prof, "DELETE", f"/drafts/{did}")


def send(prof, msg, thread_id=None):
    data = _payload(msg)
    if len(data) > RAW_LIMIT:
        return _upload(prof, "POST", "/messages/send", {"threadId": thread_id} if thread_id else {}, data)
    return google.mutate(prof, "POST", "/messages/send", _message_obj(data, thread_id))
