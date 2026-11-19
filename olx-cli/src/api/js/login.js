    // Signed-in check; when signed out, leaves the browser on OLX's sign-in page for the human.
    // P.keepalive: check in a fresh tab (the user's tab stays as it is), closed again when signed in
    // keep-alive leaves its tab open when signed out or on error: drop leftovers first, so at most one stays (live 2026-11-19: 25 stale ebay tabs, ~8 GB)
    if (P.keepalive) { step = 'new-tab'; for (const p of page.context().pages().slice(1)) await p.close().catch(() => {}); page = await page.context().newPage(); }
    step = 'open-inbox';
    await page.goto(INBOX, {timeout: T.nav, waitUntil: 'domcontentloaded'});
    await page.waitForLoadState('load', {timeout: T.nav}).catch(() => {});
    step = 'wait-inbox-or-signin';
    const r = await waitFor(async () => signedOut() ? 'login'
      : (!onLogin() && await page.locator(SEL.inboxPage).first().count()) ? 'inbox' : null, T.el + LOGIN_SETTLE,
      'conversation list or sign-in page');
    await dismissCookies();
    if (r === 'login') {
      await checkCaptcha();
      await page.bringToFront().catch(() => {});
      return {status: 'ok', logged_in: false, url: page.url()};
    }
    const url = page.url();
    if (P.keepalive) await page.close().catch(() => {});
    return {status: 'ok', logged_in: true, url};
