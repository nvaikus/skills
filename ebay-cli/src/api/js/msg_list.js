    step = 'check-login';
    await needLogin();
    if (P.id) {
      let seller = P.seller;
      if (!seller) { step = 'find-seller'; seller = await sellerOf(P.id); }
      step = 'open-conversation';
      await openConversation(P.id, seller);
      step = 'read-conversation';
      step = 'read-originals';
      return {status: 'ok', seller, messages: await addOriginals(await readThread())};
    }
    step = 'open-inbox';
    await go(`${WWW}/cnt/ViewMessage?group_type=CORE`);
    await page.locator('[data-testid=messages-inbox]').waitFor({timeout: T.el});
    step = 'read-inbox';
    const rows = await page.evaluate(limit => [...document.querySelectorAll('[data-testid=messages-inbox] tr[role=row]')]
      .slice(0, limit).map(tr => {
        const b = tr.querySelector('button[data-conversation-id]');
        const t = sel => { const e = tr.querySelector(sel); return e ? e.innerText.replace(/\s+/g, ' ').trim() : ''; };
        const last = tr.querySelector('.card__latest-message .ux-textspans');
        return {
          conversation: b ? b.getAttribute('data-conversation-id') : null,
          kind: /from-ebay/.test(b ? b.getAttribute('data-testid') : '') ? 'ebay' : 'member',
          from: t('.card__username'),
          subject: t('.card__conversation-title .ux-textspans') || t('.card__conversation-title'),
          last: last ? last.innerText.replace(/\s+/g, ' ').trim() : '',
          // live 2026-10: a reply icon before the snippet = the latest message is the user's own
          last_by: tr.querySelector('.card__latest-message use[href="#icon-reply-16"]') ? 'me' : 'them',
          unread: !!(b && b.classList.contains('unread')),
          when: t('.card__time'),
        };
      }), P.limit);
    return {status: 'ok', rows};
