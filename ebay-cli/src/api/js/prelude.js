  // ---- prelude: shared by every action. In scope: page, P (params: domain, dumpDir, T timeouts ms, ...).
  const T = P.T;
  const LOGIN = {login: true};
  const CAPTCHA = {captcha: true};
  const WWW = 'https://www.' + P.domain;
  const norm = s => String(s || '').replace(/\s+/g, ' ').trim();

  async function loggedIn() {
    // live 2026-10: cookie `ebay` carries `sin=in` (url-encoded) while signed in, any market
    const ck = await page.context().cookies(WWW);
    return ck.some(c => c.name === 'ebay' && /sin%3Din/.test(c.value));
  }

  async function go(url) {
    await page.goto(url, {timeout: T.nav, waitUntil: 'domcontentloaded'});
    if (/^https?:\/\/signin\./.test(page.url())) throw LOGIN;  // run-code scope has no URL global
    // live 2026-10: after bursts of automated page loads eBay redirects to /splashui/captcha - a human step
    if (/\/splashui\/captcha|\/splashui\/challenge/.test(page.url())) throw CAPTCHA;
    // GDPR banner swallows clicks on EU sites
    const gdpr = page.locator('#gdpr-banner-accept');
    if (await gdpr.isVisible().catch(() => false)) await gdpr.click({timeout: 5000}).catch(() => {});
  }

  async function needLogin() {
    if (!(await loggedIn())) throw LOGIN;
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

  // ---- cart page (live 2026-10: data-test-id attributes, same on every market language)
  const CART = 'https://cart.' + P.domain + '/';
  async function cartLines() {
    // the cart app root must be there: anything else (challenge, error page) is not "empty cart"
    await page.locator('[data-test-id=app-cart]').first().waitFor({state: 'attached', timeout: T.el});
    return await page.evaluate(() => [...document.querySelectorAll('.cart-bucket-lineitem')].map(li => {
      const info = s => { try { return JSON.parse(s || '{}'); } catch (e) { return {}; } };
      const t = sel => { const e = li.querySelector(sel); return e ? e.innerText.replace(/\s+/g, ' ').trim() : ''; };
      const q = li.querySelector('input[type=number]');
      const bucket = li.closest('[data-test-id=cart-bucket]');
      return {
        id: info(li.querySelector('[data-test-id=list-summary]')?.getAttribute('data-test-info')).itemId || null,
        title: t('[data-test-id=cart-item-link]'),
        price: t('.item-price'),
        shipping: t('.logistics-costs'),
        qty: q ? Number(q.value) : 1,
        variation: t('[class*=aspect], [class*=variation]'),
        seller: info(bucket?.getAttribute('data-test-info')).sellerId || null,
      };
    }));
  }
  // ---- end prelude

  // ---- messages (live 2026-10: data-testid attributes; a conversation is per listing + other user)
  async function sellerOf(id) {
    // Fallback only: the CLI passes the seller from the Browse API. Store links (/str/<slug>) are not user ids.
    await go(`${WWW}/itm/${id}`);
    let s = await page.evaluate(() => {
      for (const a of document.querySelectorAll('a[href*="_ssn="]')) {
        const v = new URL(a.href).searchParams.get('_ssn'); if (v) return v;
      }
      const m = (document.querySelector('a[href*="/usr/"]')?.href || '').match(/\/usr\/([^/?#]+)/);
      return m ? decodeURIComponent(m[1]) : null;
    });
    if (s) return s;
    // live 2026-10: "contact seller" opens a dialog with iframe getConversation?...&other_user_id=<user id>
    const btn = page.getByRole('button', {name: /Nachricht an Verkäufer|Contact seller|Message seller|Contacter le vendeur|Contatta il venditore|Contactar al vendedor/i}).first();
    await btn.click({timeout: T.el});
    const fr = page.locator('iframe[src*="getConversation"]').first();
    await fr.waitFor({state: 'attached', timeout: T.el});
    const m = ((await fr.getAttribute('src')) || '').match(/other_user_id=([^&]+)/);
    await page.keyboard.press('Escape').catch(() => {});
    if (!m) throw new Error(`no seller id on listing ${id}`);
    return decodeURIComponent(m[1]);
  }

  const convUrl = (id, seller) => `${WWW}/cnt/ViewMessage/getConversation?reference_id=${id}`
    + `&other_user_id=${encodeURIComponent(seller)}&reference_type=LISTING&group_type=CORE`;

  async function openConversation(id, seller) {
    await go(convUrl(id, seller));
    await page.locator('textarea[data-testid=message-input-textarea]').waitFor({timeout: T.el});
    await page.locator('[data-testid=messages-thread]').waitFor({timeout: 5000}).catch(() => {});
  }

  async function readThread() {
    // live 2026-10-10: the thread container is inverse - DOM order is newest first, and the day separator
    // (h3) sits on the oldest message of that day. Reverse to chronological order, carry the day forward.
    // The other side's group label has no colon ("ttz0422 18:59 text"); own: "Sie: Heute 18:41 text".
    return await page.evaluate(() => {
      let day = '';
      return [...document.querySelectorAll('[data-testid=app-conversation]')].reverse().map(g => {
        const h = g.querySelector('h3');
        if (h) day = h.innerText.trim();
        const label = g.getAttribute('aria-label') || '';
        const av = g.querySelector('[data-testid=message-bubble__avatar] [role=img]');
        // live 2026-10: one .clipped span per text line
        const parts = [...g.querySelectorAll('[data-testid=message-bubble_content] .clipped')].map(e => e.textContent.trim());
        const c = g.querySelector('[data-testid=message-bubble_content]');
        // posted-time = time span + (auto-translated) a "Übersetzt" label span
        const tm = g.querySelector('[data-testid=message-bubble_posted-time] > .ux-textspans');
        return {who: av ? (av.getAttribute('aria-label') || '').trim() : (label.includes(':') ? label.split(':')[0].trim() : ''),
                day, time: tm ? tm.textContent.trim() : '',
                translated: !!g.querySelector('.app-conversation__message-bubble__translation-label'),
                text: parts.length ? parts.join('\n') : (c ? c.innerText.trim() : '')};
      });
    });
  }

  async function addOriginals(msgs) {
    // live 2026-10-10: eBay auto-translates the other side's messages; [data-testid=translation-cta] toggles the
    // whole thread to the originals and back (a view switch, no reload). A tourtip host covers it -> dispatchEvent.
    if (!msgs.some(m => m.translated)) return msgs;
    const cta = page.locator('[data-testid=translation-cta]').first();
    if (!(await cta.count())) return msgs;
    const labels = () => page.evaluate(() => document.querySelectorAll('.app-conversation__message-bubble__translation-label').length);
    try {
      await cta.dispatchEvent('click', {}, {timeout: 5000});
      await page.waitForFunction(() => !document.querySelector('.app-conversation__message-bubble__translation-label'), null, {timeout: 10000});
      const orig = await readThread();
      if (orig.length === msgs.length) msgs.forEach((m, i) => { if (m.translated && orig[i].text !== m.text) m.original = orig[i].text; });
    } catch (e) {
      // originals are a bonus: the translated thread is already read
    } finally {
      if (!(await labels().catch(() => 1))) {
        await cta.dispatchEvent('click', {}, {timeout: 5000}).catch(() => {});  // back to the translated view
        await page.waitForFunction(() => !!document.querySelector('.app-conversation__message-bubble__translation-label'), null, {timeout: 10000}).catch(() => {});
      }
    }
    return msgs;
  }
