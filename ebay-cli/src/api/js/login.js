    step = 'check-login';
    if (P.keepalive) {
      // scheduled touch: load the site in a fresh tab (refreshes the session cookies), the user's tab stays as it is
      step = 'keepalive-tab';
      page = await page.context().newPage();
      await page.goto(WWW + '/', {timeout: T.nav, waitUntil: 'domcontentloaded'});
      await page.waitForLoadState('load', {timeout: T.nav}).catch(() => {});
      if (await loggedIn()) { await page.close().catch(() => {}); return {status: 'ok', logged_in: true}; }
    }
    if (await loggedIn()) return {status: 'ok', logged_in: true};
    step = 'open-signin';
    // go() would treat the sign-in page as "not logged in": plain goto here
    await page.goto('https://signin.' + P.domain + '/', {timeout: T.nav, waitUntil: 'domcontentloaded'});
    await page.bringToFront().catch(() => {});
    return {status: 'ok', logged_in: false, url: page.url()};
