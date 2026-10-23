"""Command name -> (module, one-line help). Never import a command module here."""

AREAS = {"start": "Start here", "find": "Search and inspect", "watch": "Saved searches (cron / clockmaster)"}
FAMILIES = {"watch"}

COMMANDS = {
    "doctor": ("src.commands.start.doctor", "live check of the Vinted sources + breakage stats from past runs"),
    "search": ("src.commands.find.search", "items for a query: price, total with fee, brand, size, condition, url"),
    "show": ("src.commands.find.show", "one item as a markdown card (numeric id or Vinted URL)"),
    "categories": ("src.commands.find.categories", "category ids + names (for search --category)"),
    "brands": ("src.commands.find.brands", "brand ids for a keyword (for search --brand)"),
    "sizes": ("src.commands.find.sizes", "size ids of a category (for search --size)"),
    "conditions": ("src.commands.find.conditions", "condition names + ids (for search --condition)"),
    "colors": ("src.commands.find.colors", "color names + ids (for search --color)"),
    "watch add": ("src.commands.watch.add", "save a search (same flags as search); records the current items"),
    "watch list": ("src.commands.watch.list", "saved searches"),
    "watch rm": ("src.commands.watch.rm", "delete saved searches"),
    "watch run": ("src.commands.watch.run", "rerun saved searches: only NEW items and price drops since last run"),
}


def area(name):
    return COMMANDS[name][0].split(".")[2]
