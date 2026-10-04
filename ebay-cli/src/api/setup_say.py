"""What `ebay setup` tells the user, word for word (Claude relays it unchanged).
Reader is not technical: one action per line, the exact label eBay shows in quotes, the pitfall where it happens."""
import sys

PORTAL = "https://developer.ebay.com"
KEYS_URL = f"{PORTAL}/my/keys"
STORE = 'security add-generic-password -U -a "$USER" -s {var} -w "$(pbpaste | tr -d \'[:space:]\')"'

ACCOUNT = f"""eBay setup, step 1 of 4: a free eBay developer account (no payment, no app review).

1. Open {PORTAL}/signin?tab=register
2. Fill in the form ("Individual" is fine) and accept the API License Agreement.
   You can use the same e-mail as your eBay buying account.
3. Confirm the e-mail eBay sends you.
4. New accounts go through a manual review: sign-in shows "Access to your new account is pending
   approval, which takes at least one business day". Nothing to do but wait for eBay's approval e-mail.
5. Tell me when you can sign in at {PORTAL}."""

KEYSET = f"""eBay setup, step 2 of 4: create the production keys.

1. Open {KEYS_URL} (sign in if asked).
2. In "Application Title" type any name, e.g. personal-search, and click "Create a keyset"
   in the "Production" column - NOT "Sandbox" (sandbox keys only see fake test listings).
3. If eBay asks for contact details, fill them in and continue.
4. You now see the Production keyset with "App ID (Client ID)", "Dev ID" and "Cert ID (Client Secret)".
   It may say the keyset is disabled - that is the next step.
5. Tell me when you see it."""

DELETION = f"""eBay setup, step 3 of 4: the account-deletion notice (eBay keeps new keys disabled until this is done).

eBay asks every app to either receive "marketplace account deletion" notices or declare that it stores
no eBay user data. This tool only searches public listings and stores nothing about eBay users, so you opt out:

1. On {KEYS_URL}, next to the Production keyset click the link about
   "marketplace deletion/account closure notification" (or "Notifications" / "Alerts & Notifications").
2. Switch "Not persisting eBay data" to On.
3. Confirm the dialog that pops up.
4. Pick the reason that says your app does not store eBay user data; "Additional information"
   may stay empty or say "personal search tool, no eBay user data stored".
5. Click "Submit". Back on {KEYS_URL} the Production keyset should no longer say disabled.
6. Tell me when it is done."""


def keys_mac():
    return f"""eBay setup, step 4 of 4: store the two keys in your Mac's Keychain (they never go into this chat).

On {KEYS_URL}, Production keyset:
1. Copy "App ID (Client ID)" (the copy icon next to it), then in the Terminal app run:
   {STORE.format(var="EBAY_CLIENT_ID")}
2. Copy "Cert ID (Client Secret)", then run:
   {STORE.format(var="EBAY_CLIENT_SECRET")}
   Nothing is printed - that is expected. Copy each value right before its command.
3. Do NOT paste the keys here. Just tell me "done"."""


def keys_other():
    return f"""eBay setup, step 4 of 4: store the two keys on this computer (they never go into this chat).

On {KEYS_URL}, Production keyset you need "App ID (Client ID)" and "Cert ID (Client Secret)".
1. Open a terminal on this computer and run:   ebay setup --keys-stdin
2. Paste the App ID when asked, Enter; then the Cert ID (hidden), Enter.
   (Alternative: set environment variables EBAY_CLIENT_ID and EBAY_CLIENT_SECRET.)
3. Do NOT paste the keys here. Just tell me "done"."""


def keys():
    return keys_mac() if sys.platform == "darwin" else keys_other()


DEFAULTS = """(agent, not for the user verbatim) Ask the user two things, then save them:
1. Which country should items ship to? (ISO code, e.g. PT) - optional postal code for exact shipping costs.
2. Which eBay site to search by default? EU buyers: EBAY_DE (largest EU site, no customs inside the EU);
   UK: EBAY_GB; US: EBAY_US. Any search can override it with --market."""


def rejected(err):
    return f"""eBay did not accept the keys: {err}

Most common causes:
1. The Sandbox keys were stored instead of the Production ones - on {KEYS_URL} use the "Production" column.
2. App ID and Cert ID swapped, or a value copied incompletely - redo step 4 (copy, then run the command).
3. The keyset is still disabled - redo step 3 (the "Not persisting eBay data" opt-out).
Tell me when you have checked these."""


DONE = "eBay is set up: searches go to {market}, shipping is priced for {ship}."
