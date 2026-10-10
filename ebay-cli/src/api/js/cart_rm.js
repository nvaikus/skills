    step = 'check-login';
    await needLogin();
    step = 'open-cart';
    await go(CART);
    await cartLines();
    const out = [];
    for (const id of P.ids) {
      step = 'remove-' + id;
      const lines = page.locator(`.cart-bucket-lineitem:has([data-test-info*='"itemId":"${id}"'])`);
      let n = await lines.count(), removed = 0;
      for (let i = 0; n > 0 && i < 10; i++) {
        await lines.first().locator('[data-test-id=cart-remove-item]').click({timeout: T.el});
        const deadline = Date.now() + T.verify;
        while (Date.now() < deadline && (await lines.count()) >= n) await page.waitForTimeout(500);
        const now = await lines.count();
        if (now >= n) throw new Error(`cart line of ${id} still there ${T.verify / 1000} s after Remove`);
        removed += n - now; n = now;
      }
      out.push({id, removed});
    }
    step = 'verify-cart';
    await go(CART);
    const left = await cartLines();
    for (const r of out) if (left.some(l => l.id === r.id)) throw new Error(`item ${r.id} still in the cart after reload`);
    return {status: 'ok', results: out, lines: left};
