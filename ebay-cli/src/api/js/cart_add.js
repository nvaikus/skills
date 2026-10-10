    // Adds to cart only. The add-to-cart dialog has more buttons: never touch anything in it.
    step = 'check-login';
    await needLogin();
    step = 'open-cart';
    await go(CART);
    const mine = ls => ls.filter(l => l.id === P.id);
    const before = mine(await cartLines());
    if (before.length && !P.var) return {status: 'ok', added: false, already: true, lines: before};
    step = 'open-item';
    await go(`${WWW}/itm/${P.id}` + (P.var ? `?var=${encodeURIComponent(P.var)}` : ''));
    const atc = page.locator('[data-testid=x-atc-action] a, [data-testid=x-atc-action] button').first();
    step = 'find-add-to-cart';
    try { await atc.waitFor({state: 'visible', timeout: T.el}); }
    catch (e) { throw new Error('no add-to-cart button on the listing (auction-only, ended or sold out?)'); }
    step = 'variation';
    const msku = page.locator('[data-testid=x-msku-evo]');
    if (await msku.count()) {
      if (!P.var) return {status: 'usage', error: `listing ${P.id} has variations: pass --variation (ids and aspects: ebay item ${P.id})`};
      // live 2026-10: ?var=<id> preselects every msku listbox; -1 = nothing chosen (unknown variation id)
      const unset = await msku.locator('select').evaluateAll(ss => ss.filter(s => s.value === '-1').length);
      if (unset) return {status: 'usage', error: `variation ${P.var} not found on listing ${P.id}: see ebay item ${P.id}`};
    }
    if (P.qty && P.qty > 1) {
      step = 'quantity';
      const q = page.locator('#qtyTextBox, input[name=quantity]').first();
      if (!(await q.count())) return {status: 'usage', error: `listing ${P.id} has no quantity field (one per order): drop --qty`};
      await q.fill(String(P.qty), {timeout: T.el});
      await q.press('Tab', {timeout: T.el});
    }
    step = 'add-to-cart';
    await atc.click({timeout: T.el});
    // the add finishes either by navigating to the cart or behind a dialog; give it time before leaving the page
    await Promise.race([
      page.waitForURL(/\/\/cart\./, {timeout: T.verify}),
      page.locator('[role=dialog]:visible').first().waitFor({timeout: T.verify}),
    ]).catch(() => {});
    await page.waitForTimeout(1500);
    step = 'verify-in-cart';
    const qty = ls => ls.reduce((a, l) => a + (l.qty || 1), 0);
    const deadline = Date.now() + T.verify;
    let after = [];
    while (Date.now() < deadline) {
      await go(CART);
      after = mine(await cartLines());
      if (after.length > before.length || qty(after) > qty(before)) return {status: 'ok', added: true, lines: after};
      await page.waitForTimeout(3000);
    }
    throw new Error(`item ${P.id} did not show up in the cart within ${T.verify / 1000} s`);
