  // ---- prelude: shared by every action. In scope: page, P (params: host, dumpDir, T timeouts ms, ...).
  // Scope is fixed: sign-in check, read conversations, send one chat message. Never posts an ad, buys or pays
  // (dev/tests rail test greps js/ for those controls).
  const T = P.T;
  const LOGIN = {login: true};
  const CAPTCHA = {captcha: true};
  const WWW = 'https://' + P.host;
  const norm = s => String(s || '').replace(/\s+/g, ' ').trim();
  // live 2026-11-15 olx.pt: signed out, /myaccount/* redirects (client side) to login.olx.<tld>/?client_id=...
  const onLogin = () => /^https?:\/\/login\.olx\./.test(page.url());
  // the account pages answer under /myaccount/answer[s]/ on every OLX EU site (one shared frontend, olxeuweb)
  const INBOX = WWW + '/myaccount/answers/';
  const SEL = {
    // live 2026-11-15 (ad page + chat bundles): data-testid attributes, the same in every site language
    adChat: '[data-testid=ad-contact-message-button], [data-testid=chat-button]',
    input: 'textarea[name="message.text"]',
    form: '[data-testid=chat-form-container] form',
    bubble: '[data-testid=sent-message], [data-testid=received-message]',
    inboxPage: '[data-testid=active-conversations-list-page], [data-testid=conversations-list-header], [data-testid=empty-list], [data-testid^=conversations-list-item-]',
  };

  async function dismissCookies() {
    // live 2026-11-15: OneTrust banner on the first load (www and login.*); "necessary only" closes it
    for (const b of [page.locator('#onetrust-reject-all-handler'), page.getByRole('button', {name: /Aceitar necessários|Reject all|Rejeitar/i})]) {
      if (await b.first().isVisible().catch(() => false)) { await b.first().click({timeout: 5000}).catch(() => {}); return; }
    }
  }

  async function checkCaptcha() {
    // not seen live yet: a CloudFront/captcha wall instead of the page -> a human step, never a loop
    const title = await page.title().catch(() => '');
    if (/captcha|are you a robot|verify you are human|security check/i.test(title)) throw CAPTCHA;
    if (await page.locator('iframe[src*="captcha"]').first().isVisible().catch(() => false)) throw CAPTCHA;
  }

  async function go(url) {
    await page.goto(url, {timeout: T.nav, waitUntil: 'domcontentloaded'});
    await page.waitForLoadState('load', {timeout: T.nav}).catch(() => {});
    if (onLogin()) throw LOGIN;
    await checkCaptcha();
    await dismissCookies();
  }

  async function waitFor(check, ms, what) {
    // poll a condition, bounded; check() returns a truthy value when done
    for (const until = Date.now() + ms; ;) {
      const v = await check();
      if (v) return v;
      if (Date.now() > until) throw new Error(`${what}: not there within ${ms / 1000} s`);
      await page.waitForTimeout(500);
    }
  }

  async function openInbox() {
    // the redirect to login.* happens after the page loads: wait for the list or the sign-in page
    await go(INBOX);
    const r = await waitFor(async () => onLogin() ? 'login'
      : (await page.locator(SEL.inboxPage).first().count()) ? 'inbox' : null, T.el, 'conversation list');
    if (r === 'login') throw LOGIN;
  }

  async function fail(stepName, error) {
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    const png = `${P.dumpDir}/${stepName}-${ts}.png`;
    const r = {status: 'fail', step: stepName, error: error.slice(0, 400), url: page.url(), png: null};
    try { await page.screenshot({path: png, timeout: 15000}); r.png = png; } catch (e) {}
    try { r.title = await page.title(); } catch (e) {}
    try { r.aria = await page.locator('body').ariaSnapshot({timeout: 15000}); }
    catch (e) { try { r.aria = await page.locator('body').innerText({timeout: 5000}); } catch (e2) { r.aria = 'no page text: ' + e2; } }
    return r;
  }

  // ---- conversation (chat bundle 2026-11-15: bubbles carry data-testid sent-message | received-message with an
  // aria-label naming the sender; text in [data-testid=message]; [data-testid=message-status-label] = the time,
  // or a sending / undelivered / read note on own messages). UNVERIFIED on a signed-in page: check DOM order.
  async function readThread() {
    return await page.evaluate(sel => [...document.querySelectorAll(sel)].map(b => {
      const t = b.querySelector('[data-testid=message]');
      const label = b.querySelector('[data-testid=message-status-label]');
      return {mine: b.getAttribute('data-testid') === 'sent-message', who: (b.getAttribute('aria-label') || '').trim(),
              time: label ? label.textContent.replace(/\s+/g, ' ').trim() : '',
              text: (t ? t.innerText : b.innerText).trim()};
    }), SEL.bubble);
  }

  function conversationId() {
    const m = page.url().match(/\/myaccount\/answer\/([^/?#]+)/);
    return m && m[1] !== 'new' ? m[1] : null;
  }

  async function openChat() {
    // P.conversation -> straight to it; else the ad page's own "Enviar mensagem" button, which routes to the
    // existing conversation (/myaccount/answer/<id>/) or a new one (/myaccount/answer/new/?ad_id=..&user_uuid=..)
    if (P.conversation) {
      step = 'open-conversation';
      await go(`${WWW}/myaccount/answer/${encodeURIComponent(P.conversation)}/`);
    } else {
      step = 'open-listing';
      await go(P.url);
      const btn = page.locator(SEL.adChat).first();
      try { await btn.waitFor({state: 'visible', timeout: T.el}); }
      catch (e) { return {status: 'usage', error: `listing ${P.id} shows no "send message" button (inactive listing, or the seller takes no chat)`}; }
      step = 'click-message';
      await btn.click({timeout: T.el});
    }
    step = 'wait-chat';
    // a desktop ad page may open the chat in a popup instead of routing: the composer is the proof either way
    const r = await waitFor(async () => onLogin() ? 'login'
      : (await page.locator(SEL.input).first().isVisible().catch(() => false)) ? 'chat' : null, T.nav, 'chat composer');
    if (r === 'login') throw LOGIN;
    await checkCaptcha();
    // existing conversations load their messages after the composer
    await page.locator(SEL.bubble).first().waitFor({state: 'attached', timeout: 5000}).catch(() => {});
    await page.waitForTimeout(800);
    return null;
  }
  // ---- end prelude
