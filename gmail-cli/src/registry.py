"""Command name -> (module, one-line help). Never import a command module here.
Flat verbs for mail and organizing, two-token `<family> <verb>` for labels, drafts, attachments."""

AREAS = {"start": "Start here", "mail": "Find and read", "org": "Organize (message ids or -q QUERY; no confirmation)",
         "label": "Labels", "clean": "Declutter (bulk senders, unsubscribe, filters)", "draft": "Write (draft first, then `draft send`)"}
FAMILIES = {"label", "draft", "attachment", "filter"}

COMMANDS = {
    "onboard": ("src.commands.start.onboard", "guided setup of a Gmail account, one step per run (exit 5 = waiting on the user)"),
    "profiles": ("src.commands.start.profiles", "Gmail accounts set up here; --default NAME; --remove NAME"),
    "login": ("src.commands.start.login", "OAuth login of a profile (onboard drives it; --start / --finish)"),
    "whoami": ("src.commands.start.whoami", "account address and mailbox size per profile"),
    "search": ("src.commands.mail.search", "Gmail query -> TSV rows; every profile at once unless --profile"),
    "read": ("src.commands.mail.read", "a thread (or one message) as compact markdown: no quotes, no signatures"),
    "attachment list": ("src.commands.mail.attachment_list", "attachments of a message, numbered"),
    "attachment get": ("src.commands.mail.attachment_get", "download attachments by number or name"),
    "modify": ("src.commands.org.modify", "add/remove labels on ids or on everything a query matches"),
    "archive": ("src.commands.org.verbs", "remove from Inbox"),
    "unarchive": ("src.commands.org.verbs", "move back to Inbox"),
    "mark-read": ("src.commands.org.verbs", "mark as read"),
    "mark-unread": ("src.commands.org.verbs", "mark as unread"),
    "star": ("src.commands.org.verbs", "add a star"),
    "unstar": ("src.commands.org.verbs", "remove the star"),
    "trash": ("src.commands.org.verbs", "move to Trash (Gmail empties it after 30 days; no permanent delete here)"),
    "untrash": ("src.commands.org.verbs", "restore from Trash"),
    "label list": ("src.commands.label.list", "labels with ids; --counts adds message/unread totals"),
    "label create": ("src.commands.label.create", "create a label (Parent/Child creates missing parents)"),
    "label rename": ("src.commands.label.rename", "rename a label and its nested children"),
    "label delete": ("src.commands.label.delete", "delete a label (messages stay, they just lose it)"),
    "senders": ("src.commands.clean.senders", "who sends the most: messages grouped by sender, count, unread, unsubscribe method"),
    "unsubscribe": ("src.commands.clean.unsubscribe", "leave a mailing list: one-click POST, else mailto, else the URL to open"),
    "filter list": ("src.commands.clean.filter_list", "Gmail filters: criteria and actions, every profile"),
    "filter create": ("src.commands.clean.filter_create", "new filter: --from/--to/--subject/--query + label/archive/read/trash; --apply"),
    "filter delete": ("src.commands.clean.filter_delete", "remove filters by id"),
    "draft create": ("src.commands.draft.create", "new draft: --to/--cc/--subject/--body, --attach, --reply-to ID"),
    "draft list": ("src.commands.draft.list", "drafts: id, to, subject, snippet"),
    "draft show": ("src.commands.draft.show", "a draft in full: headers, body, attachments"),
    "draft edit": ("src.commands.draft.edit", "change fields, body or attachments of a draft"),
    "draft send": ("src.commands.draft.send", "send a draft as it is"),
    "draft delete": ("src.commands.draft.delete", "discard a draft (unsent drafts only)"),
    "send": ("src.commands.draft.send_now", "send right away, same flags as draft create (prefer draft create + draft send)"),
}


def area(name):
    return COMMANDS[name][0].split(".")[2]
