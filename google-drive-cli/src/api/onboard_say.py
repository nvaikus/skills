"""What `gdrive onboard` tells the user, word for word (Claude relays it unchanged).

The reader is NOT technical: one action per line, the exact label Google shows in quotes, what the
screen looks like after the action, the exact value to type, and each known pitfall at the moment
it happens (live 2026-10-01 on a gmail account: Publish greyed out until Branding is saved, Drive
box starts unticked, Google "500" right after publishing, "Google" in app names refused)."""
from pathlib import Path

TOTAL = 12
CONSOLE = "https://console.cloud.google.com"
APIS = {"drive": "drive.googleapis.com", "docs": "docs.googleapis.com", "sheets": "sheets.googleapis.com"}
CONSUMER = ("gmail.com", "googlemail.com")
APP_NAME = "Personal Drive"  # "gdrive"/"G-drive" are refused by Google (trademark)
PROJECT_NAME = "personal-drive"
# Shared pages (personal-drive/ on the nvaikus.github.io user site): Google accepts them for ANY
# user's app without domain ownership checks - live 2026-10-01, Publish became clickable.
HOME_URL = "https://nvaikus.github.io/personal-drive/"
PRIVACY_URL = "https://nvaikus.github.io/personal-drive/privacy.html"
DOMAIN = "nvaikus.github.io"
ERROR_500 = ("If Google shows \"500. That's an error\" (it happens in the first minutes after publishing):\n"
             "   wait 2 minutes and open the link again, or open it in a private/incognito window.")


def default_where(prof):
    return str(Path("~/gdrive").expanduser() / prof)


def acct_kind(cfg):
    """workspace (login saw a Workspace domain) · consumer · workspace? (non-gmail address, not
    logged in yet: could still be a personal account) · unknown."""
    a = cfg.get("account") or {}
    email = (a.get("email") or "").lower()
    if a.get("domain"):
        return "workspace"
    if email.endswith(CONSUMER) or "domain" in a:  # 'domain' key present = set by a login: no Workspace
        return "consumer"
    return "workspace?" if email else "unknown"


def who(cfg):
    email = (cfg.get("account") or {}).get("email")
    return f" ({email})" if email else ""


def _addr(cfg):
    return (cfg.get("account") or {}).get("email") or "your Google address"


def api_link(pid, names=None):
    ids = ",".join(APIS[n] for n in (names or APIS))
    return f"{CONSOLE}/flows/enableapi?apiid={ids}&project={pid}"


# ---- step 2: automatic or manual -------------------------------------------------------------

def mode():
    return (f"Step 2 of {TOTAL}: how do you want to set up the Google side?\n\n"
            f"A - Automatic (recommended, about 5 minutes):\n"
            f"    a Chrome window opens on this computer. You sign in to Google there.\n"
            f"    Everything else is filled in for you. At the very end you click \"Continue\" once.\n"
            f"B - Manual (about 15 minutes):\n"
            f"    I guide you through the Google screens step by step and you click them yourself.\n\n"
            f"Answer A or B. You can switch later.")


# ---- manual steps 3-9 ------------------------------------------------------------------------

def project(cfg, prof):
    return (f"Step 3 of {TOTAL}: create your own Google Cloud project (free, no payment).\n\n"
            f"1. Open {CONSOLE}/projectcreate\n"
            f"   Sign in with the Google account whose Drive you want to use{who(cfg)}.\n"
            f"2. If a window \"Welcome to Google Cloud\" appears: choose your country, tick the box\n"
            f"   that you agree to the Terms of Service, click \"AGREE AND CONTINUE\".\n"
            f"3. You see the page \"New Project\". In the box \"Project name\" delete the text and type:\n"
            f"   {PROJECT_NAME}\n"
            f"4. Just under it Google shows \"Project ID: {PROJECT_NAME}-123456\" (your numbers differ).\n"
            f"   Copy that Project ID.\n"
            f"5. Leave everything else as it is. Click \"CREATE\".\n"
            f"6. Send me the Project ID from point 4.")


def apis(cfg, disabled=None):
    pid = cfg["project_id"]
    still = ""
    if disabled:
        still = ("Google says these are still switched off: " + ", ".join(n.capitalize() for n in disabled)
                 + ".\n\n")
    return (f"Step 4 of {TOTAL}: switch on Google Drive, Docs and Sheets for your project.\n\n{still}"
            f"1. Open {api_link(pid, disabled)}\n"
            f"2. The page says \"Confirm project\" and shows {pid}.\n"
            f"   If it shows another project, stop and tell me. Otherwise click \"NEXT\".\n"
            f"3. The page lists Google Drive API, Google Docs API, Google Sheets API. Click \"ENABLE\".\n"
            f"4. Wait about 10 seconds until the page says the APIs are enabled.\n"
            f"5. Tell me \"done\".")


def consent(cfg):
    pid, kind = cfg["project_id"], acct_kind(cfg)
    if kind == "consumer":
        audience = "choose \"External\" (\"Internal\" cannot be selected for a personal account)."
    else:
        audience = ("if \"Internal\" can be selected, choose it (company Google Workspace account);\n"
                    "   otherwise choose \"External\".")
    return (f"Step 5 of {TOTAL}: name your app (Google calls it the consent screen).\n\n"
            f"1. Open {CONSOLE}/auth/overview?project={pid}\n"
            f"2. Click \"GET STARTED\". (No such button but a page \"OAuth Overview\"? Then this step is\n"
            f"   already done: tell me \"done\" and whether it says Internal or External.)\n"
            f"3. \"App name\": type {APP_NAME}\n"
            f"   (exactly this - Google refuses names like gdrive because of its trademark).\n"
            f"4. \"User support email\": click the box and choose your address. Click \"NEXT\".\n"
            f"5. Audience: {audience} Click \"NEXT\".\n"
            f"6. \"Email addresses\": type {_addr(cfg)} and press Enter. Click \"NEXT\".\n"
            f"7. Tick \"I agree to the Google API Services: User Data Policy\". Click \"CONTINUE\",\n"
            f"   then \"CREATE\". The page now shows \"OAuth Overview\".\n"
            f"8. Tell me \"done\" and whether you chose Internal or External.")


def branding(cfg, why=""):
    pid = cfg["project_id"]
    return (f"{why}Step 6 of {TOTAL}: give the app a home page and a privacy policy.\n"
            f"Google lets the app work permanently only with these two pages. Ready-made shared pages\n"
            f"for {APP_NAME} exist - you do not need your own website.\n\n"
            f"1. Open {CONSOLE}/auth/branding?project={pid}\n"
            f"2. Scroll down to \"App domain\".\n"
            f"3. \"Application home page\": paste {HOME_URL}\n"
            f"4. \"Application privacy policy link\": paste {PRIVACY_URL}\n"
            f"5. Leave \"Application Terms of Service link\" empty.\n"
            f"6. Below, under \"Authorised domains\", click \"ADD DOMAIN\".\n"
            f"   In the new box \"Authorised domain 1\" type: {DOMAIN}\n"
            f"7. Click \"SAVE\" at the bottom of the page. A short message confirms it was saved.\n"
            f"8. Tell me \"done\".")


def publish(cfg, why=""):
    pid = cfg["project_id"]
    return (f"{why}Step 7 of {TOTAL}: publish the app, so the login never expires.\n\n"
            f"1. Open {CONSOLE}/auth/audience?project={pid}\n"
            f"2. Under \"Test users\" click \"ADD USERS\", type {_addr(cfg)}, click \"SAVE\".\n"
            f"3. Under \"Publishing status\" (it says \"Testing\") click \"PUBLISH APP\".\n"
            f"   Greyed out? Then the Branding page was not saved: do step 6 again, click \"SAVE\",\n"
            f"   come back here and reload the page.\n"
            f"4. A window \"Push to production?\" appears. Click \"CONFIRM\".\n"
            f"5. The page now says \"In production\". Tell me \"done\".\n"
            f"Cannot publish at all? Say \"keep testing\": it works too, but Google then asks you to\n"
            f"allow access again every 7 days.")


def client(cfg):
    pid = cfg["project_id"]
    return (f"Step 8 of {TOTAL}: create the key file.\n\n"
            f"1. Open {CONSOLE}/auth/clients/create?project={pid}\n"
            f"2. \"Application type\": click the box and choose \"Desktop app\".\n"
            f"3. \"Name\": delete the text and type {APP_NAME}\n"
            f"4. Click \"CREATE\".\n"
            f"5. A window \"OAuth client created\" appears. Click \"DOWNLOAD JSON\".\n"
            f"   A file named client_secret_....json lands in your Downloads folder. Click \"OK\".\n"
            f"6. Tell me where the file is, e.g. ~/Downloads/client_secret_123.json")


def login(cfg, url, again=False, why=""):
    head = (f"Step 9 of {TOTAL}: allow access to your Drive." if not again else
            f"Step 9 of {TOTAL}: the saved login no longer works - allow access once more.")
    return (f"{why}{head}\n\n"
            f"1. Open this link (valid 24 h; send the address within ~5 minutes after step 5):\n   {url}\n"
            f"2. If Google asks, choose your account{who(cfg)}.\n"
            f"3. Google may say \"Google hasn't verified this app\". That is expected - it is your own app:\n"
            f"   - if there is a \"Continue\" button, click it;\n"
            f"   - otherwise click \"Advanced\" (small, bottom left), then \"Go to {APP_NAME} (unsafe)\".\n"
            f"4. On the page \"{APP_NAME} wants access to your Google Account\" TICK the box next to\n"
            f"   \"See, edit, create and delete all of your Google Drive files\" (or \"Select all\").\n"
            f"   It starts UNTICKED - without the tick nothing works.\n"
            f"5. Click \"Continue\".\n"
            f"6. The browser now shows an error page (\"This site can't be reached\"). That is expected.\n"
            f"   Copy the WHOLE address from the address bar (it starts with http://127.0.0.1:53682/)\n"
            f"   and send it to me.\n"
            f"{ERROR_500}")


TESTING = ("Your login works, but Google ends it every 7 days because the app is still in \"Testing\".\n"
           "Two short steps make it permanent.\n\n")
RELOGIN = ("The app is published. A login made before publishing still expires in 7 days,\n"
           "so allow access once more (if you see this message again after that, the app is not\n"
           "published yet: open step 7's page and check it says \"In production\").\n\n")


# ---- automatic mode --------------------------------------------------------------------------

AUTO_STEP = {"browser": 3, "signin": 3, "terms": 3, "project": 3, "apis": 4, "consent": 5, "branding": 6,
             "publish": 7, "client": 8, "login": 9}
AUTO_LABEL = {"browser": "opening the browser", "signin": "Google sign-in", "terms": "Google Cloud terms",
              "project": "creating the project", "apis": "switching on Drive, Docs and Sheets",
              "consent": "naming the app (consent screen)", "branding": "home page and privacy policy",
              "publish": "publishing the app", "client": "creating the key", "login": "allowing access"}


def auto_signin(cfg):
    return (f"Step 3 of {TOTAL}: a Chrome window has opened on this computer.\n\n"
            f"1. Sign in there with the Google account whose Drive you want to use{who(cfg)}\n"
            f"   (codes from your phone etc. as usual).\n"
            f"2. That is all for now - everything else happens by itself. Do not close that window.\n"
            f"   At the very end I will ask you for one more click there.")


def auto_terms():
    return ("In the Chrome window Google asks you to accept the Google Cloud terms:\n"
            "1. Choose your country, tick the box that you agree to the Terms of Service.\n"
            "2. Click \"AGREE AND CONTINUE\". The rest continues by itself.")


def auto_consent(cfg):
    return (f"Step 9 of {TOTAL}: the last click. In the Chrome window Google shows\n"
            f"\"{APP_NAME} wants access to your Google Account\".\n\n"
            f"1. Check that the box \"See, edit, create and delete all of your Google Drive files\" is ticked\n"
            f"   (it was ticked for you).\n"
            f"2. Click \"Continue\". The window then says {APP_NAME} is connected.\n"
            f"If Google asks for your password or a code first, enter it.")


def auto_working(st):
    step = st.get("step") or "browser"
    msg = st.get("msg") or AUTO_LABEL.get(step, step)
    return (f"Setting up the Google side automatically - now: {msg}.\n"
            f"Nothing to do for you; keep the Chrome window open.")


def auto_failed(st):
    step = st.get("step") or "browser"
    shot = (f" Screenshot: {st['screenshot']} (page dump: {st['screenshot'][:-4]}.txt)."
            if st.get("screenshot") else "")
    return (f"The automatic setup could not finish \"{AUTO_LABEL.get(step, step)}\" ({st.get('msg') or 'unknown error'})."
            f"{shot}\nLet's do this step by hand (if the automatic Chrome window is still open, you may use it).\n\n")


# ---- steps 10-12 -----------------------------------------------------------------------------

def mount(cfg, prof, drives):
    shared = ""
    if drives:
        shared = "  - a shared drive: " + ", ".join(drives[:15]) + ("..." if len(drives) > 15 else "") + "\n"
    return (f"Step 10 of {TOTAL}: choose what to connect to this computer{who(cfg)}.\n\n"
            f"  - everything: My Drive, Shared with me" + (" and the shared drives" if drives else "") + "\n"
            f"  - only one folder of My Drive (tell me its name, e.g. Clients)\n{shared}\n"
            f"It will appear as a normal folder at {default_where(prof)}\n"
            f"(tell me if you want it somewhere else).\n"
            f"With everything, files others shared with you are visible in the folder at once; I add them\n"
            f"to the search only when you need them.")


PERSIST = (f"Step 11 of {TOTAL}: should Google Drive connect by itself every time this computer starts\n"
           "or you log in? Recommended: yes.")


def done(cfg, m, idx, service):
    what = {"/": "everything (My Drive, Shared with me, shared drives)"}.get(m["what"], m["what"])
    lines = [f"All set. Google Drive{who(cfg)} - {what} - is on this computer at {m['where']}."]
    lines.append("It reconnects by itself after a restart." if m.get("persist") else
                 "After a restart it needs `gdrive mount` again.")
    files, ok = idx.get("files") or 0, idx.get("indexed") or 0
    if idx.get("built") and not idx.get("pending"):
        lines.append(f"Search index: ready ({ok} files).")
    elif files:
        lines.append(f"Search index: building in the background - {ok} of {files} files "
                     f"({100 * ok // max(files, 1)}%). Search already works for the finished part.")
    else:
        lines.append("Search index: building in the background (listing the files first).")
    if m["what"] == "/":
        lines.append("Search covers My Drive; shared files are added to it when you ask about them.")
    lines.append("It keeps itself up to date every 5 minutes." if service else
                 "Automatic index updates are not available here: run `gdrive index update` now and then.")
    return "\n".join(lines)
