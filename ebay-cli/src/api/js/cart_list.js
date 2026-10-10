    step = 'check-login';
    await needLogin();
    step = 'open-cart';
    await go(CART);
    step = 'read-cart';
    return {status: 'ok', lines: await cartLines()};
