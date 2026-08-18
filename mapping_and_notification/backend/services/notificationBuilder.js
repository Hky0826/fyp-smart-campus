/**
 * @file notificationBuilder.js
 * @description Notification Payload Builder Service for the Campus Navigation System.
 *
 * Validates the notification trigger parameters, resolves host and visitor user
 * details from the database in a single optimized query, generates unique message IDs,
 * and constructs the complete notification payload objects for both the HOST and VISITOR
 * recipients.
 *
 * For appointment_routing events, the visitor payload will also contain
 * `routeVisualizations` — an array of CID-keyed image descriptors produced by
 * routeVisualizer. The host payload never contains route images.
 *
 * This service is stateless and does not perform any email sending or message queue
 * publishing. It is called by `engineController.calculateRoute` prior to publishing
 * events to RabbitMQ.
 */

const queryAsync        = require('../utils/queryAsync');
const routeVisualizer   = require('../utils/routeVisualizer');

/**
 * Validates notification trigger parameters, resolves recipient user details,
 * and constructs unified notification payloads for the HOST and VISITOR.
 *
 * Performs a single-query optimization to fetch both users in one database round-trip.
 *
 * @param {Object} params
 * @param {Object} params.reqBody    - The full Express request body from `calculateRoute`.
 * @param {Object} params.routeResult - The completed route result object from `runNavigation`.
 *
 * @returns {Promise<Object>} Resolved object containing:
 *   - `hostPayload`          {Object}  - Notification event payload for the host.
 *   - `visitorPayload`       {Object|null} - Notification event payload for the visitor (null if no email).
 *   - `resolvedHost`         {Object}  - Full host user record from DB.
 *   - `resolvedVisitor`      {Object}  - Full visitor user record from DB.
 *   - `visitorEmailAvailable` {boolean} - Whether the visitor has a valid email address.
 *   - `hostMsgId`            {string}  - Unique message ID for the host notification.
 *   - `visitorMsgId`         {string}  - Unique message ID for the visitor notification.
 *
 * @throws {Error} With `statusCode` 400 if required trigger fields are missing or invalid.
 * @throws {Error} With `statusCode` 404 if the host or visitor user cannot be found.
 */
async function buildNotifications({ reqBody, routeResult }) {
    const trigger      = reqBody.notification_trigger || {};
    const hostId       = Number(trigger.target_host_id ?? reqBody.target_host_id);
    const visitorUserIdStr = reqBody.user_id;
    const alertMsg     = trigger.alert_message ?? reqBody.alert_message;

    if (hostId && !alertMsg) {
        const error = new Error('Missing alert_message for the provided target_host_id in notification_trigger.');
        error.statusCode = 400;
        throw error;
    }
    
    const eventType = reqBody.event_type || 'appointment_routing';

    if (!hostId && eventType !== 'visitor_navigation') {
        const error = new Error('Target host ID is required for this event type.');
        error.statusCode = 400;
        throw error;
    }

    const visitorIdNum = Number(visitorUserIdStr);
    if (isNaN(visitorIdNum)) {
        const error = new Error('user_id must be a numeric user ID.');
        error.statusCode = 400;
        throw error;
    }

    let resolvedHost = null;
    let resolvedVisitor = null;
    let hostMsgId = null;
    let visitorMsgId = `MSG-VISITOR-${Date.now()}-${Math.floor(Math.random() * 10000).toString(16)}`;

    if (hostId) {
        // 1. Single-query optimization: fetch both host and visitor details simultaneously
        const userIds = [hostId, visitorIdNum];
        const userResults = await queryAsync(
            `SELECT u.user_id, u.full_name, u.email, u.role_id, r.role_name 
             FROM users u 
             LEFT JOIN roles r ON u.role_id = r.role_id 
             WHERE u.user_id IN (?)`,
            [userIds]
        );

        resolvedHost    = userResults.find(u => u.user_id === hostId);
        resolvedVisitor = userResults.find(u => u.user_id === visitorIdNum);

        // 2. Validate that both users exist in the database
        if (!resolvedHost) {
            const error = new Error(`Target host ID ${hostId} does not exist in the database.`);
            error.statusCode = 404;
            throw error;
        }

        hostMsgId = `MSG-HOST-${Date.now()}-${Math.floor(Math.random() * 10000).toString(16)}`;
    } else {
        const userResults = await queryAsync(
            `SELECT u.user_id, u.full_name, u.email, u.role_id, r.role_name 
             FROM users u 
             LEFT JOIN roles r ON u.role_id = r.role_id 
             WHERE u.user_id = ?`,
            [visitorIdNum]
        );
        resolvedVisitor = userResults.find(u => u.user_id === visitorIdNum);
    }

    if (!resolvedVisitor) {
        const error = new Error(`Visitor user ID ${visitorIdNum} does not exist in the database.`);
        error.statusCode = 404;
        throw error;
    }

    // 4. Generate route visualizations for appointment_routing & visitor_navigation (visitor-only, generated once)
    let routeVisualizations = [];
    if (eventType === 'appointment_routing' || eventType === 'visitor_navigation') {
        try {
            routeVisualizations = await routeVisualizer.generate(routeResult, visitorMsgId);
            console.log(`[NotificationBuilder] Generated ${routeVisualizations.length} route visualization(s).`);
        } catch (err) {
            console.error('[NotificationBuilder] Route visualization failed (non-fatal):', err.message);
            routeVisualizations = [];
        }
    }

    // 5. Construct the Host notification payload — NO route visualizations
    let hostPayload = null;
    if (resolvedHost) {
        hostPayload = {
            message_id:        hostMsgId,
            notification_type: 'HOST',
            event_type:        eventType,
            user_id:           resolvedVisitor.user_id,
            visitor_name:      resolvedVisitor.full_name,
            rbac_role:         resolvedVisitor.role_name || 'Visitor',
            current_location:  routeResult.route_summary.start_label,
            destination_node:  routeResult.route_summary.destination_label,
            route_summary: {
                start_label:                routeResult.route_summary.start_label,
                destination_label:          routeResult.route_summary.destination_label,
                total_distance_m:           routeResult.route_summary.total_distance_m,
                estimated_time_seconds:     routeResult.route_summary.estimated_time_seconds,
                estimated_time_label:       routeResult.route_summary.estimated_time_label,
                floor_transitions:          routeResult.route_summary.floor_transitions,
                building_transitions:       routeResult.route_summary.building_transitions,
                start_building_name:        routeResult.path[0]?.building_name || '',
                start_floor_level:          routeResult.path[0]?.floor_level   || 0,
                destination_building_name:  routeResult.path[routeResult.path.length - 1]?.building_name || '',
                destination_floor_level:    routeResult.path[routeResult.path.length - 1]?.floor_level   || 0
            },
            instructions: routeResult.instructions,
            notification_trigger: {
                target_host_id: hostId,
                alert_message:  alertMsg
            }
            // routeVisualizations intentionally omitted from host payload
        };
    }

    // 6. Construct the Visitor notification payload (only if the visitor has a valid email)
    const visitorEmailAvailable = !!(resolvedVisitor.email && resolvedVisitor.email.trim().length > 0);
    let visitorPayload = null;

    if (visitorEmailAvailable) {
        visitorPayload = {
            message_id:        visitorMsgId,
            notification_type: 'VISITOR',
            visitor_email:     resolvedVisitor.email.trim(),
            event_type:        eventType,
            user_id:           resolvedVisitor.user_id,
            visitor_name:      resolvedVisitor.full_name,
            rbac_role:         resolvedVisitor.role_name || 'Visitor',
            current_location:  routeResult.route_summary.start_label,
            destination_node:  routeResult.route_summary.destination_label,
            route_summary: {
                start_label:                routeResult.route_summary.start_label,
                destination_label:          routeResult.route_summary.destination_label,
                total_distance_m:           routeResult.route_summary.total_distance_m,
                estimated_time_seconds:     routeResult.route_summary.estimated_time_seconds,
                estimated_time_label:       routeResult.route_summary.estimated_time_label,
                floor_transitions:          routeResult.route_summary.floor_transitions,
                building_transitions:       routeResult.route_summary.building_transitions,
                start_building_name:        routeResult.path[0]?.building_name || '',
                start_floor_level:          routeResult.path[0]?.floor_level   || 0,
                destination_building_name:  routeResult.path[routeResult.path.length - 1]?.building_name || '',
                destination_floor_level:    routeResult.path[routeResult.path.length - 1]?.floor_level   || 0
            },
            instructions:        routeResult.instructions,
            routeVisualizations  // Only the visitor receives the image attachments
        };
    }

    return {
        hostPayload,
        visitorPayload,
        resolvedHost,
        resolvedVisitor,
        visitorEmailAvailable,
        hostMsgId,
        visitorMsgId
    };
}

module.exports = { buildNotifications };
