require('dotenv').config();
const amqp = require('amqplib');
const db = require('./config/db');
const notificationService = require('./services/notificationService');

const RABBITMQ_URL = process.env.RABBITMQ_URL || 'amqp://localhost';
const QUEUE_NAME = 'campus.notifications.queue';

let connection = null;
let channel = null;

/**
 * Handle incoming message from RabbitMQ.
 */
async function handleMessage(msg) {
    if (!msg) return;

    let payload;
    try {
        payload = JSON.parse(msg.content.toString());
    } catch (err) {
        console.error('[Consumer] Failed to parse message content as JSON. Rejecting.');
        channel.ack(msg);
        return;
    }

    try {
        // Delegate core notification logic to Notification Service
        await notificationService.processNotification(payload);
    } catch (err) {
        console.error('[Consumer] Error processing message inside service:', err.message);
    } finally {
        // Always acknowledge to avoid infinite message loop re-deliveries
        channel.ack(msg);
    }
}

/**
 * Start the consumer worker.
 */
async function start() {
    console.log('[Consumer] Starting notification consumer...');
    
    // Connect to database check
    db.getConnection((err, conn) => {
        if (err) {
            console.error('[Consumer] Database connection failed:', err.message);
            process.exit(1);
        }
        console.log('[Consumer] Database connection pool verified.');
        conn.release();
    });

    try {
        connection = await amqp.connect(RABBITMQ_URL);
        
        connection.on('error', (err) => {
            console.error('[Consumer] Connection error:', err.message);
        });
        
        connection.on('close', () => {
            console.warn('[Consumer] RabbitMQ connection closed. Reconnecting in 5 seconds...');
            connection = null;
            channel = null;
            setTimeout(start, 5000);
        });

        channel = await connection.createChannel();
        
        channel.on('error', (err) => {
            console.error('[Consumer] Channel error:', err.message);
        });
        
        channel.on('close', () => {
            console.warn('[Consumer] RabbitMQ channel closed.');
        });
        
        await channel.assertQueue(QUEUE_NAME, { durable: true });
        // Prefetch set to 1 for load balancing
        await channel.prefetch(1);

        console.log(`[Consumer] Listening for messages on "${QUEUE_NAME}"...`);

        channel.consume(QUEUE_NAME, (msg) => {
            handleMessage(msg);
        }, { noAck: false });

        // Handle graceful shutdowns
        const shutdown = async () => {
            console.log('[Consumer] Shutting down consumer worker gracefully...');
            try {
                if (channel) await channel.close();
                if (connection) await connection.close();
                console.log('[Consumer] RabbitMQ connection closed.');
                process.exit(0);
            } catch (err) {
                console.error('[Consumer] Error during shutdown:', err.message);
                process.exit(1);
            }
        };

        process.on('SIGINT', shutdown);
        process.on('SIGTERM', shutdown);

    } catch (err) {
        console.error('[Consumer] Consumer startup failed:', err.message);
        setTimeout(start, 5000); // Retry connecting in 5 seconds
    }
}

start();
