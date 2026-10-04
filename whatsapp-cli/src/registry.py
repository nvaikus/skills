"""Command name -> (module, one-line help). Never import a command module here."""

AREAS = {"auth": "Accounts", "chats": "Chats and people", "messages": "Messages",
         "groups": "Groups (invite links)", "channels": "Channels (newsletters)"}

COMMANDS = {
    "deps": ("src.commands.auth.deps", "install neonize into ~/.wa-cli/venv (once per machine)"),
    "login": ("src.commands.auth.login", "link this machine as a device: QR (default) or --phone pairing code; interactive"),
    "logout": ("src.commands.auth.logout", "unlink the device on WhatsApp and delete its session"),
    "accounts": ("src.commands.auth.accounts", "accounts linked on this machine (offline)"),
    "whoami": ("src.commands.auth.whoami", "the current account"),
    "sync": ("src.commands.messages.sync", "pull new messages into the local store and report counts"),
    "chats": ("src.commands.chats.chats", "chats in the store, filtered by name/type"),
    "contacts": ("src.commands.chats.contacts", "your address book (names synced from the phone)"),
    "user-find": ("src.commands.chats.user_find", "find people/chats by name or phone; checks a number is on WhatsApp"),
    "history": ("src.commands.messages.history", "recent messages of one chat (from the store)"),
    "search": ("src.commands.messages.search", "full-text search over the stored messages"),
    "send": ("src.commands.messages.send", "send a message or file(s) - immediately, no preview"),
    "group-info": ("src.commands.groups.group_info", "what a group invite link points to - without joining"),
    "join": ("src.commands.groups.join", "join a group by invite link (only on the user's explicit request)"),
    "channel-info": ("src.commands.channels.channel_info", "a channel by link, invite code or jid - without following"),
    "channel-fetch": ("src.commands.channels.channel_fetch", "recent posts of a channel into the store - without following"),
}


def area(name):
    return COMMANDS[name][0].split(".")[2]
