    step = 'open-chat';
    const u = await openChat();
    if (u) return u;
    const before = (await readThread()).length;
    step = 'type';
    const ta = page.locator(SEL.input).first();
    await ta.fill(P.text, {timeout: T.el});
    step = 'send';
    // chat bundle 2026-11-15: the composer's submit button (type=submit, shown once there is text) in the same form
    const btn = ta.locator('xpath=ancestor::form[1]').locator('button[type=submit]').first();
    await waitFor(async () => (await btn.isVisible().catch(() => false)) && (await btn.isEnabled().catch(() => false)),
                  T.el, 'enabled send button');
    await btn.click({timeout: T.el});
    step = 'verify-sent';
    // sent = a new own bubble with this text whose status label shows a time (sending / undelivered show none)
    const want = norm(P.text).slice(0, 80);
    const deadline = Date.now() + T.verify;
    let last = null;
    while (Date.now() < deadline) {
      const msgs = await readThread();
      const hit = msgs.slice(before).reverse().find(m => m.mine && norm(m.text).includes(want));
      last = hit || last;
      if (hit && /\d/.test(hit.time)) return {status: 'ok', message: hit, count: msgs.length, conversation: conversationId()};
      await page.waitForTimeout(1000);
    }
    throw new Error(last ? `message shows in the conversation but not as delivered (status '${last.time}') within ${T.verify / 1000} s`
                         : `sent message did not appear in the conversation within ${T.verify / 1000} s`);
