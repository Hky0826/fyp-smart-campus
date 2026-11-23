const test = require('node:test');
const assert = require('node:assert/strict');

test('unconfigured kiosk API key rejects the public fallback; configured key works', () => {
    const originalKey = process.env.NAVIGATION_API_KEY;
    const modulePath = require.resolve('./kioskAuthMiddleware');
    function check(key) {
        delete require.cache[modulePath];
        const { authenticateKioskAccess } = require(modulePath);
        let status = 200;
        let accepted = false;
        authenticateKioskAccess(
            { headers: { 'x-api-key': key } },
            { status(code) { status = code; return this; }, json() {} },
            () => { accepted = true; },
        );
        return { status, accepted };
    }
    try {
        delete process.env.NAVIGATION_API_KEY;
        assert.deepEqual(check('campus-nav-key'), { status: 401, accepted: false });
        process.env.NAVIGATION_API_KEY = 'isolated-kiosk-regression-key';
        assert.deepEqual(check('wrong-key'), { status: 401, accepted: false });
        assert.deepEqual(check('isolated-kiosk-regression-key'), { status: 200, accepted: true });
    } finally {
        if (originalKey === undefined) delete process.env.NAVIGATION_API_KEY;
        else process.env.NAVIGATION_API_KEY = originalKey;
        delete require.cache[modulePath];
    }
});
