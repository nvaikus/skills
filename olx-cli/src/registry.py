"""Command name -> (module, one-line help). Never import a command module here."""

AREAS = {"start": "Start here", "find": "Search and inspect", "watch": "Saved searches (cron / clockmaster)"}
FAMILIES = {"watch"}

COMMANDS = {
    "doctor": ("src.commands.start.doctor", "live check of the OLX endpoint + breakage stats from past runs"),
    "search": ("src.commands.find.search", "listings for a query: price, title, city, date, url"),
    "show": ("src.commands.find.show", "one listing as a markdown card (numeric id or OLX URL)"),
    "photos": ("src.commands.find.photos", "download a listing's photos (id or URL), print the paths; --sheet = one grid image"),
    "categories": ("src.commands.find.categories", "category ids + names (for search --category)"),
    "places": ("src.commands.find.places", "city / region ids (for search --city / --region)"),
    "watch add": ("src.commands.watch.add", "save a search (same flags as search); records the current listings"),
    "watch list": ("src.commands.watch.list", "saved searches"),
    "watch rm": ("src.commands.watch.rm", "delete saved searches"),
    "watch run": ("src.commands.watch.run", "rerun saved searches: only NEW listings and price drops since last run"),
}


def area(name):
    return COMMANDS[name][0].split(".")[2]
