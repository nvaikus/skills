"""What `gmail onboard` tells the user, word for word (Claude relays it unchanged).

The reader is NOT technical: one action per line, the exact label Google shows in quotes, what the
screen looks like after the action, the exact value to type, each known pitfall where it happens.
Console pitfalls are the google-drive-cli skill's (live 2026-10-01): Publish greyed out until Branding is
saved, Google "500" right after publishing, trademark words refused in app names."""

CONSOLE = "https://console.cloud.google.com"
GMAIL_API = "gmail.googleapis.com"
CONSUMER = ("gmail.com", "googlemail.com")
APP_NAME = "Personal Mail"  # "Gmail" in an app name is refused by Google (trademark)
PROJECT_NAME = "personal-mail"
# Shared pages (nvaikus/skills docs/personal-drive on GitHub Pages): Google accepts them for any user's app.
HOME_URL = "https://nvaikus.github.io/skills/personal-drive/"
PRIVACY_URL = "https://nvaikus.github.io/skills/personal-drive/privacy.html"
DOMAIN = "nvaikus.github.io"
ERROR_500 = ("If Google shows \"500. That's an error\" (it happens in the first minutes after publishing):\n"
             "   wait 2 minutes and open the link again, or open it in a private/incognito window.")


def acct_kind(cfg):
    a = cfg.get("account") or {}
    email = (a.get("email") or "").lower()
    if a.get("domain"):
        return "workspace"
    if email.endswith(CONSUMER) or "domain" in a:
        return "consumer"
    return "workspace?" if email else "unknown"


def who(cfg):
    email = (cfg.get("account") or {}).get("email")
    return f" ({email})" if email else ""


def _addr(cfg):
    return (cfg.get("account") or {}).get("email") or "your Google address"


def _app(cfg):
    return cfg.get("app_name") or "your app"


def api_link(pid):
    if pid:
        return f"{CONSOLE}/flows/enableapi?apiid={GMAIL_API}&project={pid}"
    return f"{CONSOLE}/apis/library/{GMAIL_API}"


def reused(src, email=None):
    return f"Reusing the Google key of {src}" + (f" ({email})" if email else "") + " - no new Google Cloud setup needed."


# ---- a new key (no gdrive/gmail profile to reuse) -----------------------------------------------

def project(cfg):
    return ("Gmail setup: create your own Google Cloud project (free, no payment).\n\n"
            f"1. Open {CONSOLE}/projectcreate\n"
            f"   Sign in with your Google account{who(cfg)}.\n"
            "2. If a window \"Welcome to Google Cloud\" appears: choose your country, tick the box\n"
            "   that you agree to the Terms of Service, click \"AGREE AND CONTINUE\".\n"
            f"3. In the box \"Project name\" delete the text and type: {PROJECT_NAME}\n"
            f"4. Just under it Google shows \"Project ID: {PROJECT_NAME}-123456\" (your numbers differ).\n"
            "   Copy that Project ID.\n"
            "5. Click \"CREATE\".\n"
            "6. Send me the Project ID from point 4.")


def consent(cfg):
    pid, kind = cfg["project_id"], acct_kind(cfg)
    audience = ("choose \"External\" (\"Internal\" cannot be selected for a personal account)." if kind == "consumer"
                else "if \"Internal\" can be selected, choose it (company Google Workspace account);\n"
                     "   otherwise choose \"External\".")
    return ("Gmail setup: name your app (Google calls it the consent screen).\n\n"
            f"1. Open {CONSOLE}/auth/overview?project={pid}\n"
            "2. Click \"GET STARTED\". (No such button but a page \"OAuth Overview\"? Then this is already\n"
            "   done: tell me \"done\" and whether it says Internal or External.)\n"
            f"3. \"App name\": type {APP_NAME}\n"
            "   (exactly this - Google refuses names containing Gmail because of its trademark).\n"
            "4. \"User support email\": click the box and choose your address. Click \"NEXT\".\n"
            f"5. Audience: {audience} Click \"NEXT\".\n"
            f"6. \"Email addresses\": type {_addr(cfg)} and press Enter. Click \"NEXT\".\n"
            "7. Tick \"I agree to the Google API Services: User Data Policy\". Click \"CONTINUE\", then \"CREATE\".\n"
            "8. Tell me \"done\" and whether you chose Internal or External.")


def branding(cfg, why=""):
    pid = cfg.get("project_id")
    return (f"{why}Gmail setup: give the app a home page and a privacy policy.\n"
            "Google lets the app work permanently only with these two pages. Ready-made shared pages exist -\n"
            "you do not need your own website.\n\n"
            f"1. Open {CONSOLE}/auth/branding?project={pid}\n"
            "2. Scroll down to \"App domain\".\n"
            f"3. \"Application home page\": paste {HOME_URL}\n"
            f"4. \"Application privacy policy link\": paste {PRIVACY_URL}\n"
            "5. Below, under \"Authorised domains\", click \"ADD DOMAIN\" and type: " + DOMAIN + "\n"
            "6. Click \"SAVE\" at the bottom of the page.\n"
            "7. Tell me \"done\".")


def publish(cfg, why=""):
    pid = cfg.get("project_id")
    return (f"{why}Gmail setup: publish the app, so the login never expires.\n\n"
            f"1. Open {CONSOLE}/auth/audience?project={pid}\n"
            f"2. Under \"Test users\" click \"ADD USERS\", type {_addr(cfg)}, click \"SAVE\".\n"
            "3. Under \"Publishing status\" (it says \"Testing\") click \"PUBLISH APP\".\n"
            "   Greyed out? Then the Branding page was not saved: do that step again, click \"SAVE\",\n"
            "   come back here and reload the page.\n"
            "4. A window \"Push to production?\" appears. Click \"CONFIRM\".\n"
            "5. The page now says \"In production\". Tell me \"done\".\n"
            "Cannot publish at all? Say \"keep testing\": it works too, but Google then asks you to\n"
            "allow access again every 7 days.")


def client(cfg):
    pid = cfg["project_id"]
    return ("Gmail setup: create the key file.\n\n"
            f"1. Open {CONSOLE}/auth/clients/create?project={pid}\n"
            "2. \"Application type\": click the box and choose \"Desktop app\".\n"
            f"3. \"Name\": delete the text and type {APP_NAME}\n"
            "4. Click \"CREATE\".\n"
            "5. A window \"OAuth client created\" appears. Click \"DOWNLOAD JSON\", then \"OK\".\n"
            "6. Tell me where the file is, e.g. ~/Downloads/client_secret_123.json")


# ---- every profile ------------------------------------------------------------------------------

def apis(cfg, still=False):
    pid = cfg.get("project_id")
    head = ("Google says the Gmail API is still switched off for your app's project.\n\n" if still else "")
    proj = (f"2. The page says \"Confirm project\" and shows {pid}.\n"
            "   If it shows another project, stop and tell me. Otherwise click \"NEXT\".\n" if pid else
            "2. At the top, make sure the project of your Google key is selected.\n")
    return (f"{head}Gmail setup: switch on Gmail for your Google app (one click, free).\n\n"
            f"1. Open {api_link(pid)}\n"
            "   Sign in with the Google account that owns the app's project, if asked.\n"
            f"{proj}"
            "3. Click \"ENABLE\" (if it says \"MANAGE\" or \"API enabled\", it is already on).\n"
            "4. Tell me \"done\".")


def login(cfg, url, again=False, why=""):
    head = ("Gmail setup: allow access to your mailbox." if not again else
            "Gmail setup: the saved login does not work - allow access once more.")
    app = _app(cfg)
    unsafe = f"\"Go to {cfg['app_name']} (unsafe)\"" if cfg.get("app_name") else "\"Go to ... (unsafe)\""
    return (f"{why}{head}\n\n"
            f"1. Open this link (valid 24 h; send the address within ~5 minutes after step 5):\n   {url}\n"
            f"2. Choose the Gmail account to connect{who(cfg)}.\n"
            "3. Google may say \"Google hasn't verified this app\". That is expected - it is your own app:\n"
            "   - if there is a \"Continue\" button, click it;\n"
            f"   - otherwise click \"Advanced\" (small, bottom left), then {unsafe}.\n"
            f"4. On the page \"{app} wants access to your Google Account\" TICK every box (or \"Select all\"):\n"
            "   \"Read, compose and send emails from your Gmail account\" and \"See, edit, create or change\n"
            "   your email settings and filters\". They may start UNTICKED - without the first nothing works.\n"
            "5. Click \"Continue\".\n"
            "6. The browser now shows an error page (\"This site can't be reached\"). That is expected.\n"
            "   Copy the WHOLE address from the address bar (it starts with http://127.0.0.1:53682/)\n"
            "   and send it to me.\n"
            f"{ERROR_500}")


UNTICKED = ("The Gmail box on Google's page was not ticked, so the app got no access to the mailbox.\n"
            "Let's do it once more - this time tick the box.\n\n")
TESTING = ("Your login works, but Google ends it every 7 days because the app is still in \"Testing\".\n"
           "Two short steps make it permanent.\n\n")
RELOGIN = ("The app is published. A login made before publishing still expires in 7 days,\n"
           "so allow access once more.\n\n")
SETTINGS = ("Gmail filters need one more permission (\"settings and filters\") that this login does not have.\n"
            "Mail keeps working meanwhile; allow access once more to add it.\n\n")
PROPAGATING = ("Google is still switching Gmail on for your app (this takes up to a few minutes after\n"
               "clicking \"ENABLE\"). I will check again shortly - nothing to do for you.")


def done(cfg, prof, stats, filters=True):
    email = (cfg.get("account") or {}).get("email") or "the account"
    total = stats.get("messagesTotal")
    return (f"All set. Gmail {email} is connected (profile {prof})"
            + (f" - {total} messages in the mailbox." if total is not None else ".")
            + "\nI can now search, read and organise mail and write drafts there. Another account: tell me,\n"
              "and I connect it the same way (it reuses this key)."
            + ("" if filters else "\nFilters are not allowed on this login yet; to set them up I will ask you to log in once\n"
               f"more (`gmail --profile {prof} onboard --relogin`)."))
