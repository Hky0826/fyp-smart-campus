'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const amqp = require('amqplib');

const { publishNotification } = require('./mqBroker');

test('publishNotification handles offline broker without throwing', async (t) => {
    t.mock.method(amqp, 'connect', async () => {
        throw new Error('ECONNREFUSED');
    });

    const result = await publishNotification({
        notification_type: 'HOST',
        event_type: 'appointment_routing',
    });

    assert.equal(result.success, false);
    assert.equal(result.status, 'failed_broker_offline');
    assert.ok(result.message_id);
});
