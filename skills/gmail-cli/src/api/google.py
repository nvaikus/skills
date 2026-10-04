"""Authorized Gmail REST calls. The only api/ helper that mutates Gmail (grep target for audits).

Quota: a per-user cap on 'Total Query Cost' over a sliding 60 s window. Its size depends on the
OAuth client's project (6000 or 15000 units/min seen) and real costs run up to ~3x the documented
ones (a metadata messages.get ~15, not 5). Every call takes units from a per-profile token bucket
(`Pacer`); the first 429 / 403 rate error recalibrates that bucket to what the window really held,
pauses the profile a few seconds, and retries (Retry-After honored, MAX_WAIT per call).
'# ' notes: the first pause per profile, then at most one a minute."""
import collections
import concurrent.futures as cf
import random
import re
import sys
import threading
import time

from ..core import http
from ..core.errors import CliError, UsageError
from . import auth

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
UPLOAD = "https://gmail.googleapis.com/upload/gmail/v1/users/me"
WORKERS = 8  # parallel GETs per profile; the Pacer, not this, keeps us under the quota
RATE = 200  # units/s per profile until Gmail first says 'too fast' (12000/min)
BURST = 1000  # units a profile may spend at once (small commands never wait)
MIN_RATE = 10  # units/s floor after recalibration (~2 messages/s)
WINDOW = 60.0  # s: Gmail's per-user quota window
NOTE_EVERY = 60  # s between '# ' rate-limit notes of one profile
MAX_WAIT = 300  # s one call may spend waiting out rate limits before it fails
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED", "quotaExceeded"}


def notice(msg):
    """'# ' note on stderr from deep inside a call (rate-limit waits). Tests patch it."""
    sys.stderr.write(f"# {msg}\n")
    sys.stderr.flush()


class Pacer:
    """Token bucket of quota units for one profile, shared by its threads, with a log of what it
    spent in the last WINDOW s. hit() = Gmail said 'too fast': the first time the rate drops to that
    log (the real cap in our units); a refusal later than WINDOW after that costs 5%. Every thread
    pauses a few seconds (the sliding window frees units continuously, long pauses waste them)."""

    def __init__(self, rate=RATE, burst=BURST, clock=time.monotonic, sleep=time.sleep):
        self.rate, self.burst, self.clock, self.sleep = rate, burst, clock, sleep
        self.level, self.t, self.until = float(burst), clock(), 0.0
        self.used = collections.deque()  # (time, units) of the last WINDOW s
        self.noted = None  # clock of the last note
        self.calibrated = None  # clock of the first refusal
        self.lock = threading.Lock()

    def take(self, units):
        units = min(units, self.burst)
        while True:
            with self.lock:
                now = self.clock()
                if now < self.until:
                    wait = self.until - now
                else:
                    self.level = min(self.burst, self.level + max(0.0, now - self.t) * self.rate)
                    self.t = now
                    if self.level >= units - 1e-6:  # float dust must not spin forever
                        self.level = max(0.0, self.level - units)
                        self.used.append((now, units))
                        return
                    wait = (units - self.level) / self.rate
            self.sleep(wait)

    def hit(self, seconds):
        """Gmail refused for rate: slow down, pause every caller >= seconds.
        -> (seconds this caller will wait, note due: True when a '# ' note should go out)."""
        with self.lock:
            now = self.clock()
            while self.used and self.used[0][0] <= now - WINDOW:
                self.used.popleft()
            if now < self.until - 0.5:  # another thread already paused the profile
                return self.until - now, False
            spent = sum(u for _, u in self.used)
            if self.calibrated is None:  # first refusal: the window held the real cap
                self.rate = min(self.rate, max(MIN_RATE, spent / WINDOW))
                self.calibrated = now
            elif now - self.calibrated > WINDOW:  # refused at the calibrated pace: 5% slower
                self.rate = max(MIN_RATE, self.rate * 0.95)
            # inside the first WINDOW the pre-calibration burst still fills Gmail's window: just wait
            self.burst = min(self.burst, max(self.rate * 5, 100))
            self.until = now + seconds  # short: the sliding window frees units every second
            self.level, self.t = 0.0, self.until
            due = self.noted is None or now - self.noted >= NOTE_EVERY
            if due:
                self.noted = now
            return seconds, due

    def per_min(self):
        """Units/min the bucket allows now (documented costs: a messages.get = 5)."""
        return self.rate * 60


_pacers = {}
_plock = threading.Lock()


def pacer(prof):
    with _plock:
        return _pacers.setdefault(prof, Pacer())


def cost(method, path):
    """Gmail quota units of a call (developers.google.com/gmail/api/reference/quota)."""
    p = path.split("?")[0]
    if p.endswith("/send"):
        return 100
    if p.endswith("/batchModify"):
        return 50
    if p.startswith("/threads"):
        return 10
    if p.startswith(("/labels", "/profile", "/settings")):
        return 1 if method == "GET" else 5
    return 5


def rate_limited(e):
    if e.status == 429:
        return True
    body = e.body if isinstance(e.body, dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    return e.status == 403 and bool(RATE_REASONS & reasons(e) or err.get("status") == "RESOURCE_EXHAUSTED")


def _call(prof, method, path, params=None, body=None, allow_mutate=False, data=None, content_type=None, base=BASE):
    url = path if path.startswith("http") else base + path
    units = cost(method, url[len(base):] if url.startswith(base) else path)
    pace, waited, attempt = pacer(prof), 0.0, 0
    while True:
        pace.take(units)
        hdrs = {"Authorization": f"Bearer {auth.access_token(prof)}"}
        try:
            got = http.request(method, url, params=params, body=body, headers=hdrs, allow_mutate=allow_mutate,
                               data=data, content_type=content_type, rate_retry=False)
            return got
        except CliError as e:
            if not rate_limited(e):
                raise translate(e, prof) from None
            if waited >= MAX_WAIT:
                t = translate(e, prof)
                raise CliError(f"{t} - still rate-limited after {waited:.0f} s of backoff: rerun in a few minutes "
                               "or narrow the query / --limit", status=t.status, body=t.body) from None
            # a rate-limited request did not run: retrying a mutation is safe too
            delay = getattr(e, "retry_after", None) or min(2 ** (attempt + 1), 30)
            pause, due = pace.hit(delay + random.uniform(0, 1))
            if due:
                cap = quota_limit(e)
                notice(f"profile {prof}: Gmail per-user quota reached{f' ({cap} units/min)' if cap else ''}; "
                       f"slowing to ~{pace.per_min() / 5:.0f} message reads/min, pausing {pause:.0f} s")
            waited += pause
            attempt += 1


def quota_limit(e):
    """quota_limit_value from Google's ErrorInfo (the per-user cap of this project) or None."""
    body = e.body if isinstance(e.body, dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    for d in err.get("details", []):
        if isinstance(d, dict) and (d.get("metadata") or {}).get("quota_limit_value"):
            return d["metadata"]["quota_limit_value"]
    return None


def translate(e, prof=None):
    """Google error -> the exit code a caller must act on. Never branch on message text elsewhere."""
    body = e.body if isinstance(e.body, dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    rs = reasons(e)
    msg = err.get("message") or str(e)
    kw = {"status": e.status, "body": e.body}
    who = f"profile {prof!r}: " if prof else ""
    again = f"`gmail onboard --profile {prof}`" if prof else "`gmail onboard`"
    if e.status == 401:
        return UsageError(f"{who}Google rejected the token ({msg}): log in again with {again}", **kw)
    if e.status == 403 and {"accessNotConfigured", "SERVICE_DISABLED"} & rs:
        return UsageError(f"{who}the Gmail API is off in the OAuth client's Google Cloud project: run {again} "
                          "(it shows the link to switch it on)", **kw)
    if e.status == 403 and {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"} & rs:
        return UsageError(f"{who}the token lacks Gmail access: log in again with {again} and tick the Gmail box", **kw)
    if e.status == 404:
        return UsageError(f"{who}not found: {msg}", **kw)
    if e.status == 400:
        return UsageError(f"{who}Gmail refused the request: {msg}", **kw)
    return CliError(f"{who}Gmail API error {e.status}: {msg}", **kw)


def reasons(e):
    """Google error reasons of a CliError (errors[].reason + details[].reason)."""
    body = e.body if isinstance(e.body, dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    return {d.get("reason") for d in err.get("errors", []) + err.get("details", []) if isinstance(d, dict)}


def get(prof, path, params=None):
    return _call(prof, "GET", path, params=params)


def mutate(prof, method, path, body=None, params=None, data=None, content_type=None, base=BASE):
    """Every write to Gmail goes through here."""
    return _call(prof, method, path, params=params, body=body, allow_mutate=True, data=data,
                 content_type=content_type, base=base)


def pmap(fn, items, workers=WORKERS):
    """Ordered parallel map (GETs of one profile). The first exception propagates."""
    items = list(items)
    if len(items) <= 1:
        return [fn(i) for i in items]
    with cf.ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        return list(ex.map(fn, items))


_SKIP = object()


def pmap_partial(fn, items, workers=WORKERS):
    """pmap that keeps what it got: -> (results in input order without the failed/skipped ones,
    first CliError or None). After a failure the remaining items are skipped, not fetched."""
    stop, errs = threading.Event(), []

    def guarded(i):
        if stop.is_set():
            return _SKIP
        try:
            return fn(i)
        except CliError as e:
            stop.set()
            errs.append(e)
            return _SKIP
    items = list(items)
    if len(items) <= 1:
        got = [guarded(i) for i in items]
    else:
        with cf.ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
            got = list(ex.map(guarded, items))
    return [g for g in got if g is not _SKIP], (errs[0] if errs else None)
