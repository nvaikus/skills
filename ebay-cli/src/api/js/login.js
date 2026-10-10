    step = 'check-login';
    if (await loggedIn()) return {status: 'ok', logged_in: true};
    step = 'open-signin';
    // go() would treat the sign-in page as "not logged in": plain goto here
    await page.goto('https://signin.' + P.domain + '/', {timeout: T.nav, waitUntil: 'domcontentloaded'});
    await page.bringToFront().catch(() => {});
    return {status: 'ok', logged_in: false, url: page.url()};
