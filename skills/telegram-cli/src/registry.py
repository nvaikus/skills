"""Command name -> (module, one-line help). Never import a command module here."""

AREAS = {"auth": "Accounts", "chats": "Chats and people", "messages": "Messages"}

COMMANDS = {
    "deps": ("src.commands.auth.deps", "install Telethon into ~/.tg-cli/venv (once per machine)"),
    "keys": ("src.commands.auth.keys", "store the Telegram API keys (interactive, once per machine user)"),
    "login": ("src.commands.auth.login", "log an account in: QR (default) or --phone; interactive"),
    "logout": ("src.commands.auth.logout", "end the session on Telegram and delete it locally"),
    "accounts": ("src.commands.auth.accounts", "accounts logged in on this machine (offline)"),
    "whoami": ("src.commands.auth.whoami", "the current account"),
    "chats": ("src.commands.chats.chats", "your dialogs, filtered by name/type"),
    "user-find": ("src.commands.chats.user_find", "find users, bots, groups, channels: contacts, @username, global"),
    "history": ("src.commands.messages.history", "recent messages of one chat"),
    "search": ("src.commands.messages.search", "search messages: all your chats, one --chat, or --public posts"),
    "send": ("src.commands.messages.send", "send a message or file(s) - immediately, no preview"),
}


def area(name):
    return COMMANDS[name][0].split(".")[2]
