"""Command name -> (module, one-line help). Never import a command module here."""

AREAS = {"start": "Start here", "find": "Search and inspect", "watch": "Saved searches (for cron / task-scheduler)"}
FAMILIES = {"watch"}

COMMANDS = {
    "setup": ("src.commands.start.setup", "guided setup: developer keys, defaults; one step per run (exit 5 = waiting on the user)"),
    "doctor": ("src.commands.start.doctor", "check keys, defaults, token and a live test search"),
    "search": ("src.commands.find.search", "listings for a query: price, shipping to you, condition, seller"),
    "item": ("src.commands.find.item", "one listing as a markdown card (id, v1|..| id or eBay URL)"),
    "categories": ("src.commands.find.categories", "category ids for a query (for search --category)"),
    "watch add": ("src.commands.watch.add", "save a search (same flags as search); records the current items"),
    "watch list": ("src.commands.watch.list", "saved searches"),
    "watch rm": ("src.commands.watch.rm", "delete saved searches"),
    "watch run": ("src.commands.watch.run", "rerun saved searches: only NEW items and price drops since last run"),
}


def area(name):
    return COMMANDS[name][0].split(".")[2]
