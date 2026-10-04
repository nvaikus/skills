"""Command name -> (module, one-line help). Never import a command module here.
Flat verbs for the filesystem layer, two-token `<family> <verb>` for Google-native files."""

AREAS = {"start": "Start here", "fs": "Filesystem (rclone)", "index": "Search index (grep ~/.claude/gdrive/<profile>/index)",
         "doc": "Google Docs", "sheet": "Google Sheets"}
FAMILIES = {"doc", "sheet", "index"}

COMMANDS = {
    "onboard": ("src.commands.start.onboard", "guided setup of a profile, one step per run (exit 5 = waiting on the user)"),
    "profiles": ("src.commands.start.profiles", "Google accounts set up here; --default NAME"),
    "setup": ("src.commands.fs.setup", "download/refresh the official rclone binary for this OS (no admin)"),
    "login": ("src.commands.fs.login", "one Google login for mount + Docs/Sheets (OAuth, headless-friendly)"),
    "whoami": ("src.commands.fs.whoami", "logged-in account, storage quota, rclone/config paths"),
    "mount": ("src.commands.fs.mount", "mount Drive (/, /Folder, shared:<Drive>) at a local dir, in background"),
    "umount": ("src.commands.fs.umount", "unmount / stop syncing; refuses while uploads are pending"),
    "status": ("src.commands.fs.status", "active mounts and sync folders: state, cache fill, pending uploads"),
    "sync": ("src.commands.fs.sync", "sync folder: run a two-way sync pass; mount: wait until uploads finish"),
    "ls": ("src.commands.fs.ls", "list a Drive folder by path (names, ids, kinds) without a mount"),
    "link": ("src.commands.fs.link", "web link of a file/folder; --public creates an anyone-with-link share"),
    "share": ("src.commands.fs.share", "who has access; --user EMAIL [--role] grants, --remove EMAIL revokes"),
    "index update": ("src.commands.index.update", "catch up with Drive changes, or re-index one file now (after your write)"),
    "index status": ("src.commands.index.status", "index completeness and freshness per profile"),
    "index include": ("src.commands.index.include", "also index Shared with me / Shared drives (My Drive only by default)"),
    "index exclude": ("src.commands.index.exclude", "stop indexing a section added with `index include`"),
    "index service": ("src.commands.index.service", "install/remove the 5-minute background updater"),
    "doc cat": ("src.commands.doc.cat", "a Google Doc as markdown"),
    "doc edit": ("src.commands.doc.edit", "targeted Doc edit: --replace OLD NEW | --append MD | --after HEADING MD"),
    "doc new": ("src.commands.doc.new", "create a Google Doc at a path, optionally with markdown content"),
    "sheet tabs": ("src.commands.sheet.tabs", "tabs of a Google Sheet with sizes"),
    "sheet get": ("src.commands.sheet.get", "cells of a range as TSV (default: whole first tab)"),
    "sheet set": ("src.commands.sheet.set", "overwrite a range with TSV from stdin"),
    "sheet append": ("src.commands.sheet.append", "append TSV rows from stdin after a tab's table"),
    "sheet new": ("src.commands.sheet.new", "create a Google Sheet at a path, optionally filled from stdin TSV"),
}


def area(name):
    return COMMANDS[name][0].split(".")[2]
