    // Signed-in check; when signed out, leaves the browser on OLX's sign-in page for the human.
    step = 'open-inbox';
    await page.goto(INBOX, {timeout: T.nav, waitUntil: 'domcontentloaded'});
    await page.waitForLoadState('load', {timeout: T.nav}).catch(() => {});
    step = 'wait-inbox-or-signin';
    const r = await waitFor(async () => onLogin() ? 'login'
      : (await page.locator(SEL.inboxPage).first().count()) ? 'inbox' : null, T.el, 'conversation list or sign-in page');
    await dismissCookies();
    if (r === 'login') {
      await checkCaptcha();
      await page.bringToFront().catch(() => {});
      return {status: 'ok', logged_in: false, url: page.url()};
    }
    return {status: 'ok', logged_in: true, url: page.url()};
