const amqp = require('amqplib');

const RABBITMQ_URL = process.env.RABBITMQ_URL || 'amqp://localhost';
const EXCHANGE_NAME = 'campus.notifications.exchange';
const QUEUE_NAME = 'campus.notifications.queue';
const ROUTING_KEY = 'appointment_routing';

let connection = null;
let channel = null;
let isConnecting = false;

/**
 * Initialize connection and channel, assert exchange and queue.
 */
async function connectBroker() {
    if (connection && channel) return { connection, channel };
    if (isConnecting) {
        // Wait briefly if connection is already in progress
        await new Promise(resolve => setTimeout(resolve, 500));
        return connectBroker();
    }

    isConnecting = true;
    console.log(`[RabbitMQ] Connecting to broker at ${RABBITMQ_URL}...`);
    try {
        connection = await amqp.connect(RABBITMQ_URL);
        
        // Use a confirm channel so we can await broker receipt confirmation
        channel = await connection.createConfirmChannel();
        
        // Assert Topic exchange (durable)
        try {
            await channel.assertExchange(EXCHANGE_NAME, 'topic', { durable: true });
        } catch (_) {
            await channel.assertExchange(EXCHANGE_NAME, 'direct', { durable: true });
        }
        
        // Assert Queue (durable)
        await channel.assertQueue(QUEUE_NAME, { durable: true });
        
        // Bind Queue to Exchange with Routing Key
        await channel.bindQueue(QUEUE_NAME, EXCHANGE_NAME, ROUTING_KEY);
        
        console.log('[RabbitMQ] Successfully connected, exchange/queue asserted.');

        connection.on('error', (err) => {
            console.error('[RabbitMQ] Connection error:', err.message);
            connection = null;
            channel = null;
        });

        connection.on('close', () => {
            console.warn('[RabbitMQ] Connection closed. Will reconnect on next publish.');
            connection = null;
            channel = null;
        });

    } catch (err) {
        console.error('[RabbitMQ] Connection failed:', err.message);
        connection = null;
        channel = null;
    } finally {
        isConnecting = false;
    }

    return { connection, channel };
}

/**
 * Publishes a notification event to RabbitMQ using confirm channel.
 * Resolves once RabbitMQ acknowledges receipt of the message.
 * Falls back to graceful resolution if broker is offline (doesn't block HTTP flow).
 * 
 * @param {Object} payload The notification event payload.
 * @returns {Promise<Object>} { success: boolean, message_id: string }
 */
async function publishNotification(payload) {
    const timestamp = new Date().toISOString();
    
    // Auto-generate message_id if not present
    const messageId = payload.message_id || `MSG-${Date.now()}-${Math.floor(Math.random() * 10000).toString(16)}`;
    
    const enrichedPayload = {
        ...payload,
        message_id: messageId,
        timestamp: payload.timestamp || timestamp
    };

    try {
        const { channel: activeChannel } = await connectBroker();
        if (!activeChannel) {
            console.warn('[RabbitMQ] Message publish skipped: Broker offline.');
            return { success: false, message_id: messageId, status: 'failed_broker_offline' };
        }

        const msgBuffer = Buffer.from(JSON.stringify(enrichedPayload));
        
        console.log(`[RabbitMQ] Publishing message ${messageId} to routing key "${ROUTING_KEY}"...`);
        
        await new Promise((resolve, reject) => {
            activeChannel.publish(
                EXCHANGE_NAME, 
                ROUTING_KEY, 
                msgBuffer, 
                { persistent: true }, // Make message persistent (durable)
                (err, ok) => {
                    if (err) {
                        console.error('[RabbitMQ] Publish confirmation failed:', err);
                        reject(err);
                    } else {
                        resolve(ok);
                    }
                }
            );
        });

        return { success: true, message_id: messageId, status: 'queued' };
    } catch (err) {
        console.error('[RabbitMQ] Failed to publish message:', err.message);
        return { success: false, message_id: messageId, status: 'failed_publish_error' };
    }
}

module.exports = {
    connectBroker,
    publishNotification
};
