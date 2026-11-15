    if (P.id || P.conversation) {
      step = 'open-chat';
      const u = await openChat();
      if (u) return u;
      step = 'read-conversation';
      return {status: 'ok', conversation: conversationId(), messages: await readThread()};
    }
    step = 'open-inbox';
    await openInbox();
    await page.waitForTimeout(1500);  // rows render after the list frame
    step = 'read-inbox';
    // chat bundle 2026-11-15: row data-testid conversations-list-item-<conversation id>; a status icon before the
    // snippet only when the last message is the user's own; unread rows render bold
    const rows = await page.evaluate(limit => [...document.querySelectorAll('[data-testid^=conversations-list-item-]')]
      .filter(r => r.querySelector('[data-testid=list-item-message-text]')).slice(0, limit).map(r => {
        const t = sel => { const e = r.querySelector(sel); return e ? e.innerText.replace(/\s+/g, ' ').trim() : ''; };
        const msg = r.querySelector('[data-testid=list-item-message-text]');
        const line = msg.parentElement;
        const mine = !!(line && [...line.children].some(c => c !== msg && c.querySelector && (c.matches('svg') || c.querySelector('svg'))
          && (c.compareDocumentPosition(msg) & Node.DOCUMENT_POSITION_FOLLOWING)));
        const w = parseInt(getComputedStyle(msg).fontWeight, 10) || 400;
        return {conversation: r.getAttribute('data-testid').replace('conversations-list-item-', ''),
                from: t('[data-testid=list-item-user-name]'), ad: t('[data-testid=list-item-context-title]'),
                last: t('[data-testid=list-item-message-text]'), last_by: mine ? 'me' : 'them', unread: w >= 600,
                when: t('[data-testid=list-item-datetime]')};
      }), P.limit);
    return {status: 'ok', rows};
