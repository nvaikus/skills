    step = 'check-login';
    await needLogin();
    let seller = P.seller;
    if (!seller) { step = 'find-seller'; seller = await sellerOf(P.id); }
    step = 'open-conversation';
    await openConversation(P.id, seller);
    const before = (await readThread()).length;
    step = 'type';
    const ta = page.locator('textarea[data-testid=message-input-textarea]');
    await ta.fill(P.text, {timeout: T.el});
    step = 'send';
    const btn = page.locator('button[data-testid=message-send-button]');
    const ready = Date.now() + T.el;
    while (Date.now() < ready && !(await btn.isEnabled())) await page.waitForTimeout(300);
    await btn.click({timeout: T.el});
    step = 'verify-sent';
    const want = norm(P.text).slice(0, 80);
    const deadline = Date.now() + T.verify;
    while (Date.now() < deadline) {
      const msgs = await readThread();
      const hit = msgs.slice(before).reverse().find(m => norm(m.text).includes(want) && m.time);
      if (hit) return {status: 'ok', seller, message: hit, count: msgs.length};
      await page.waitForTimeout(1000);
    }
    throw new Error(`sent message did not appear in the conversation with a timestamp within ${T.verify / 1000} s`);
