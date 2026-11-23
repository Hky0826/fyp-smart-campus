const test = require('node:test');
const assert = require('node:assert/strict');
const jwt = require('jsonwebtoken');
const express = require('express');
const http = require('node:http');

process.env.JWT_SECRET = 'middleware-regression-test-secret';
const { authenticateToken } = require('./authMiddleware');

let server;
let baseUrl;

test('real HTTP admin boundary rejects bypasses and preserves valid administrator JWTs', async t => {
    const app = express();
    app.get('/admin', authenticateToken, (req, res) => res.json({ role: req.user.role }));
    server = http.createServer(app);
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    baseUrl = `http://127.0.0.1:${server.address().port}`;
    t.after(() => new Promise(resolve => server.close(resolve)));

    for (const token of ['broken', 'dashboard-admin-session', 'active-admin-anything']) {
        const response = await fetch(`${baseUrl}/admin`, { headers: { Authorization: `Bearer ${token}` } });
        assert.equal(response.status, 401);
    }
    const student = jwt.sign({ role: 'STUDENT' }, process.env.JWT_SECRET, { expiresIn: '1h' });
    assert.equal((await fetch(`${baseUrl}/admin`, { headers: { Authorization: `Bearer ${student}` } })).status, 403);
    const admin = jwt.sign({ type: 'SYSTEM_ADMIN' }, process.env.JWT_SECRET, { expiresIn: '1h' });
    const accepted = await fetch(`${baseUrl}/admin`, { headers: { Authorization: `Bearer ${admin}` } });
    assert.equal(accepted.status, 200);
    assert.deepEqual(await accepted.json(), { role: 'SYSTEM_ADMIN' });
    const noExpiry = jwt.sign({ type: 'SUPER_ADMIN' }, process.env.JWT_SECRET, { noTimestamp: true });
    assert.equal((await fetch(`${baseUrl}/admin`, { headers: { Authorization: `Bearer ${noExpiry}` } })).status, 401);
});

function run(token) {
    return new Promise(resolve => {
        const req = { headers: token === undefined ? {} : { authorization: `Bearer ${token}` } };
        const res = {
            statusCode: 200,
            status(code) { this.statusCode = code; return this; },
            json(body) { resolve({ statusCode: this.statusCode, body, user: req.user }); return this; },
        };
        authenticateToken(req, res, () => resolve({ statusCode: 200, user: req.user }));
    });
}

test('missing, malformed, invalid, expired, and former admin tokens fail closed', async () => {
    const expired = jwt.sign({ type: 'SUPER_ADMIN' }, process.env.JWT_SECRET, { expiresIn: -1 });
    for (const token of [undefined, 'broken', 'dashboard-admin-session', 'authenticated-admin-session', 'active-admin-anything', expired]) {
        const result = await run(token);
        assert.equal(result.statusCode, 401, String(token));
    }
    assert.equal((await run(jwt.sign({ sub: 'forged' }, 'other-secret'))).statusCode, 401);
});

test('signed administrator tokens retain their role claim', async () => {
    const token = jwt.sign({ email: 'admin@example.test', type: 'SUPER_ADMIN' }, process.env.JWT_SECRET, { expiresIn: '1h' });
    const result = await run(token);
    assert.equal(result.statusCode, 200);
    assert.equal(result.user.role, 'SUPER_ADMIN');
    assert.equal(result.user.type, 'SUPER_ADMIN');
});

test('signed non-admin tokens cannot reach admin routes', async () => {
    const token = jwt.sign({ sub: 'student-1', role: 'STUDENT' }, process.env.JWT_SECRET, { expiresIn: '1h' });
    assert.equal((await run(token)).statusCode, 403);
});
