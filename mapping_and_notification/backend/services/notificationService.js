/**
 * @file notificationService.js
 * @description Notification Processing Service for the Campus Navigation System Consumer.
 *
 * This service is consumed exclusively by the RabbitMQ consumer worker (`consumer.js`).
 * It processes dequeued notification events by:
 *   1. Performing idempotency checks to skip already-processed messages.
 *   2. Resolving the associated audit trail record in the database.
 *   3. Dispatching the appropriate email (host alert or visitor journey email).
 *   4. Updating the MySQL audit trail with the final delivery status.
 *
 * This service does NOT interact with HTTP requests or Express.
 * It communicates exclusively through the database and the email service.
 */

const db = require('../config/db');
const emailService = require('./emailService');
const queryAsync = require('../utils/queryAsync');

/**
 * Processes a single notification event payload dequeued from RabbitMQ.
 *
 * This function is idempotent: if the message has already been processed
 * (i.e., its status is not PENDING), it will skip re-processing and return early.
 *
 * Processing flow:
 *   1. Wait up to 500ms for the database audit record to be created by the producer.
 *   2. Skip if duplicate (non-PENDING status detected).
 *   3. Insert a fallback audit record if none exists (handles manual MQ triggers).
 *   4. Dispatch email via `emailService` based on `notification_type` (HOST or VISITOR).
 *   5. Update the audit record with SENT/FAILED status, sent timestamp, and error details.
 *
 * @param {Object} payload - The full notification event object from the RabbitMQ queue.
 * @param {string} payload.message_id         - Unique message identifier for idempotency.
 * @param {string} payload.notification_type  - 'HOST' or 'VISITOR'.
 * @param {string} payload.event_type         - Event category (e.g. 'appointment_routing').
 * @param {number} payload.user_id            - Visitor's user ID.
 * @param {string} payload.visitor_name       - Visitor's full name.
 * @param {string} [payload.visitor_email]    - Visitor's email (required for VISITOR type).
 * @param {string} payload.rbac_role          - Visitor's role label.
 * @param {string} payload.current_location   - Start node label.
 * @param {string} payload.destination_node   - Destination node label.
 * @param {Object} payload.route_summary      - Summary metrics from the route calculation.
 * @param {Array}  [payload.instructions]     - Step-by-step navigation instructions (VISITOR only).
 * @param {Object} [payload.notification_trigger] - HOST trigger containing `target_host_id` and `alert_message`.
 *
 * @returns {Promise<{ success: boolean, status?: string, skipped?: boolean, error?: string }>}
 */
async function processNotification(payload) {
    const {
        message_id, notification_type, event_type, user_id, visitor_name,
        visitor_email, rbac_role, current_location, destination_node,
        route_summary, instructions, notification_trigger,
        routeVisualizations, email_delivery_mode
    } = payload;

    if (!message_id) {
        console.error('[NotificationService] Missing unique message_id in event payload.');
        return { success: false, error: 'Missing message_id' };
    }

    console.log(`[NotificationService] Processing messageId=${message_id} of type=${notification_type || 'HOST'}`);

    try {
        // 1. Wait up to 500ms (5 x 100ms retries) for database record to be created by the producer
        //    This handles potential race conditions where the consumer processes a message
        //    before the producer's INSERT transaction completes.
        let record = null;
        for (let i = 0; i < 5; i++) {
            const check = await queryAsync('SELECT * FROM notifications WHERE message_id = ?', [message_id]);
            if (check.length > 0) {
                record = check[0];
                break;
            }
            await new Promise(resolve => setTimeout(resolve, 100));
        }

        // 2. Idempotency check — skip re-processing if status is not PENDING
        if (record && record.status !== 'PENDING') {
            console.log(`[NotificationService] Duplicate message detected. messageId=${message_id} status is already ${record.status}. Skipping...`);
            return { success: true, status: record.status, skipped: true };
        }

        // 3. Resolve the database row ID for audit trail updates
        let notificationDbId = record ? record.notification_id : null;

        // If record is missing (extremely rare race condition or manual MQ trigger),
        // insert a fallback audit log entry to keep the trail complete.
        if (!notificationDbId) {
            console.warn(`[NotificationService] Audit record missing for messageId=${message_id}. Inserting fallback audit log.`);

            let recipientUserId = 1; // Default fallback to system admin
            if (notification_type === 'HOST' && notification_trigger && notification_trigger.target_host_id) {
                recipientUserId = Number(notification_trigger.target_host_id);
            } else if (user_id && !isNaN(Number(user_id))) {
                recipientUserId = Number(user_id);
            } else {
                const fallbackUsers = await queryAsync('SELECT user_id FROM users LIMIT 1');
                recipientUserId = fallbackUsers.length > 0 ? fallbackUsers[0].user_id : 1;
            }

            const title = notification_type === 'HOST'
                ? `Campus Visitor Alert: ${visitor_name || user_id || 'Visitor'}`
                : `Campus Visitor Journey: ${visitor_name || user_id || 'Visitor'}`;
            const body = notification_type === 'HOST'
                ? (notification_trigger?.alert_message || 'Visitor is en route')
                : `Journey instructions to ${route_summary?.destination_label || destination_node || 'Destination'}`;

            const insertRes = await queryAsync(
                'INSERT INTO notifications (recipient_user_id, event_type, title, body, status, message_id) VALUES (?, ?, ?, ?, ?, ?)',
                [recipientUserId, event_type || 'appointment_routing', title, body, 'PENDING', message_id]
            );
            notificationDbId = insertRes.insertId;
        }

        // 4. Dispatch the appropriate email based on notification_type
        let emailResult;

        if (notification_type === 'VISITOR') {
            if (!visitor_email) {
                throw new Error('Visitor email is unavailable.');
            }
            console.log(`[NotificationService] Sending email to Visitor: ${visitor_email}`);
            emailResult = await emailService.sendVisitorEmail({
                toEmail:               visitor_email,
                visitorName:           visitor_name,
                destinationNodeLabel:  route_summary?.destination_label || destination_node,
                destBuilding:          route_summary?.destination_building_name,
                destFloor:             route_summary?.destination_floor_level,
                startNodeLabel:        route_summary?.start_label || current_location,
                startBuilding:         route_summary?.start_building_name,
                startFloor:            route_summary?.start_floor_level,
                walkingTimeSeconds:    route_summary?.estimated_time_seconds,
                totalDistanceMetres:   route_summary?.total_distance_m,
                instructions:          instructions,
                eventType:             event_type,
                routeVisualizations:   routeVisualizations || [],
                emailDeliveryMode:     email_delivery_mode
            });
        } else {
            // Default to 'HOST' notification type
            const hostId  = notification_trigger ? Number(notification_trigger.target_host_id) : null;
            const alertMsg = notification_trigger ? notification_trigger.alert_message : null;

            if (!hostId || !alertMsg) {
                throw new Error('Missing target_host_id or alert_message in host trigger.');
            }

            const hostUsers = await queryAsync('SELECT user_id, full_name, email FROM users WHERE user_id = ?', [hostId]);
            if (hostUsers.length === 0) {
                const err = new Error(`Target host ID ${hostId} does not exist in users database.`);
                err.code = 'HOST_MISSING';
                throw err;
            }

            const host = hostUsers[0];
            console.log(`[NotificationService] Sending email to Host: ${host.email}`);

            emailResult = await emailService.sendHostEmail({
                toEmail:              host.email,
                hostName:             host.full_name,
                visitorName:          visitor_name,
                visitorId:            user_id,
                eventType:            event_type,
                visitorRole:          rbac_role,
                startNodeLabel:       route_summary?.start_label || current_location,
                destinationNodeLabel: route_summary?.destination_label || destination_node,
                startBuilding:        route_summary?.start_building_name,
                startFloor:           route_summary?.start_floor_level,
                destBuilding:         route_summary?.destination_building_name,
                destFloor:            route_summary?.destination_floor_level,
                walkingTimeSeconds:   route_summary?.estimated_time_seconds,
                totalDistanceMetres:  route_summary?.total_distance_m,
                alertMsg:             alertMsg,
                instructions:         payload.instructions || [],
                emailDeliveryMode:    email_delivery_mode
            });
        }

        // 5. Update audit trail with final delivery status
        const finalStatus = emailResult.success ? 'SENT' : 'FAILED';
        const sentAt      = emailResult.success ? new Date() : null;

        // Classify delivery error for the audit trail
        let deliveryError = null;
        if (!emailResult.success) {
            const err     = emailResult.error || {};
            const errMsg  = String(err.message || '').toLowerCase();
            const errCode = String(err.code    || '').toUpperCase();

            if (errCode === 'EAUTH' || errMsg.includes('auth')) {
                deliveryError = 'Authentication failure';
            } else if (errCode === 'ETIMEDOUT' || errMsg.includes('timeout')) {
                deliveryError = 'Timeout';
            } else if (errCode === 'EENVELOPE' || errMsg.includes('envelope') || errMsg.includes('invalid address')) {
                deliveryError = 'Invalid email';
            } else {
                deliveryError = 'SMTP unavailable';
            }
        }

        // Preserve existing body content and append the Ethereal preview URL if available
        const existingRecord = await queryAsync('SELECT body FROM notifications WHERE notification_id = ?', [notificationDbId]);
        let updatedBody = (existingRecord.length > 0 ? existingRecord[0].body : '') || '';
        if (emailResult.previewUrl) {
            updatedBody += `\n\nPreview Link: ${emailResult.previewUrl}`;
        }

        await queryAsync(
            'UPDATE notifications SET status = ?, sent_at = ?, body = ?, delivery_error = ? WHERE notification_id = ?',
            [finalStatus, sentAt, updatedBody, deliveryError, notificationDbId]
        );

        console.log(`[NotificationService] Message messageId=${message_id} processed. Status set to ${finalStatus}`);
        return { success: emailResult.success, error: deliveryError };

    } catch (err) {
        console.error(`[NotificationService] Failed to process messageId=${message_id}:`, err.message);

        // Log failure state to MySQL Audit Trail
        let deliveryError = 'SMTP unavailable';
        if (err.code === 'HOST_MISSING' || err.message.includes('email is unavailable')) {
            deliveryError = 'Target user missing';
        }

        await queryAsync(
            'UPDATE notifications SET status = "FAILED", delivery_error = ? WHERE message_id = ?',
            [deliveryError, message_id]
        );

        return { success: false, error: err.message };
    }
}

module.exports = { processNotification };
