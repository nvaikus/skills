"""Gmail filters (users.settings.filters): list, create, delete, and applying one to existing mail.
list needs gmail.modify (every token has it); create/delete need gmail.settings.basic."""
from ..core.errors import UsageError
from . import auth, google, mail

CRITERIA = ("from", "to", "subject", "query")
SHOW = {("remove", "INBOX"): "archive", ("remove", "UNREAD"): "mark-read", ("remove", "SPAM"): "never-spam",
        ("add", "TRASH"): "trash", ("add", "STARRED"): "star", ("add", "IMPORTANT"): "important"}


def relogin_hint(profs):
    return (f"{'profiles' if len(profs) > 1 else 'profile'} {', '.join(profs)} logged in before filters were "
            "supported: the token lacks the Gmail settings permission. Log in again, per profile: "
            "`gmail --profile NAME onboard --relogin` (relay the step; the user ticks every box). "
            "Everything else keeps working meanwhile.")


def need_settings(prof):
    if auth.lacks_settings(prof):
        raise UsageError(relogin_hint([prof]))


def _settings_call(prof, fn):
    try:
        return fn()
    except UsageError as e:
        if {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"} & google.reasons(e):
            raise UsageError(relogin_hint([prof]), status=e.status, body=e.body) from None
        raise


def criteria_text(c):
    parts = []
    for k in ("from", "to", "subject"):
        if c.get(k):
            parts.append(f"{k}:({c[k]})")
    if c.get("query"):
        parts.append(c["query"])
    if c.get("negatedQuery"):
        parts.append(f"-{{{c['negatedQuery']}}}")
    if c.get("hasAttachment"):
        parts.append("has:attachment")
    if c.get("size"):
        parts.append(f"size {c.get('sizeComparison', '')} {c['size']}".replace("  ", " "))
    return " ".join(parts)


def actions_text(a, names):
    out = []
    for side, key in (("add", "addLabelIds"), ("remove", "removeLabelIds")):
        for lid in a.get(key, []):
            out.append(SHOW.get((side, lid)) or ("+" if side == "add" else "-") + mail.show_label(lid, names))
    if a.get("forward"):
        out.append(f"forward:{a['forward']}")
    return ",".join(out)


def row(prof, f, names):
    c, a = f.get("criteria", {}), f.get("action", {})
    return {"profile": prof, "id": f.get("id"), "criteria": criteria_text(c), "actions": actions_text(a, names),
            "criteria_raw": c, "action_raw": a}


def list_rows(prof):
    names = mail.label_names(prof)
    got = google.get(prof, "/settings/filters") or {}
    return [row(prof, f, names) for f in got.get("filter", [])], None


def label_ids(prof, add_names, remove_names, note=None):
    """Label names -> ids; an --add-label that does not exist yet is created (with a note)."""
    add, remove = [], []
    for n in add_names:
        lb = mail.find_label(prof, n, must=False)
        if not lb:
            lb = mail.create_label(prof, n)[-1]
            if note:
                note(f"profile {prof}: created label {lb['name']}")
        add.append(lb["id"])
    remove = [mail.find_label(prof, n)["id"] for n in remove_names]
    return add, remove


def query_of(c):
    """Filter criteria -> the Gmail search query matching the same mail (for --apply)."""
    return criteria_text(c)


def create(prof, criteria, add, remove):
    need_settings(prof)
    body = {"criteria": {k: v for k, v in criteria.items() if v},
            "action": {k: v for k, v in (("addLabelIds", add), ("removeLabelIds", remove)) if v}}
    return _settings_call(prof, lambda: google.mutate(prof, "POST", "/settings/filters", body))


def get(prof, fid):
    return google.get(prof, f"/settings/filters/{fid}")


def delete(prof, fid):
    need_settings(prof)
    f = get(prof, fid)
    _settings_call(prof, lambda: google.mutate(prof, "DELETE", f"/settings/filters/{fid}"))
    return f


def apply(prof, criteria, add, remove, limit=None):
    """Run a filter's label changes on mail it matches already. -> matched count. TRASH = trash."""
    ids = mail.list_ids(prof, query_of(criteria), limit)
    if not ids:
        return 0
    if "TRASH" in add:
        mail.trash(prof, ids)
        add = [x for x in add if x != "TRASH"]
    if add or remove:
        mail.batch_modify(prof, ids, add, remove)
    return len(ids)
