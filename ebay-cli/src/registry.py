"""Command name -> (module, one-line help). Never import a command module here."""

AREAS = {"start": "Start here", "find": "Search and inspect", "watch": "Saved searches (for cron / task-scheduler)",
         "account": "Account, in the logged-in browser (cart, seller messages; never checkout/pay/bid/offer)"}
FAMILIES = {"watch", "cart", "msg"}

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
    "login": ("src.commands.account.login", "sign in once in the ebay browser window (exit 5 = the user signs in, rerun)"),
    "cart list": ("src.commands.account.cart_list", "lines in the user's cart"),
    "cart add": ("src.commands.account.cart_add", "add a listing to the cart, verified (never checks out)"),
    "cart rm": ("src.commands.account.cart_rm", "remove listings from the cart"),
    "msg send": ("src.commands.account.msg_send", "message a listing's seller, verified in the conversation"),
    "msg list": ("src.commands.account.msg_list", "inbox conversations, or --item ID: the thread with that seller"),
}


def area(name):
    return COMMANDS[name][0].split(".")[2]
