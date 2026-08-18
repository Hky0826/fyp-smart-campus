/**
 * @file notificationController.js
 * @description Notification Hub Controller for the Campus Navigation System Admin Panel.
 *
 * Provides three read/write endpoints consumed by the admin dashboard:
 *  - `getNotifications`       — Retrieves audit trail logs from the `notifications` table.
 *  - `getUsers`               — Retrieves all users with role info for dropdown selectors.
 *  - `triggerTestNotification` — Delegates to `engineController.calculateRoute` to allow
 *                                testing the full navigation + notification workflow from
 *                                the admin UI without needing an external API key.
 */

const db = require('../config/db');

/**
 * Fetch all notification audit trail logs, ordered newest first.
 *
 * Returns each notification record joined with the recipient user's name and email,
 * enabling the admin dashboard to display human-readable recipient information.
 *
 * @param {import('express').Request}  req
 * @param {import('express').Response} res
 */
exports.getNotifications = (req, res) => {
    const sql = `
        SELECT n.*, u.full_name AS recipient_name, u.email AS recipient_email 
        FROM notifications n
        LEFT JOIN users u ON n.recipient_user_id = u.user_id
        ORDER BY n.created_at DESC
    `;
    db.query(sql, (err, results) => {
        if (err) {
            console.error('Error fetching notifications:', err.message);
            return res.status(500).json({ error: 'Failed to fetch notification logs.' });
        }
        res.json(results);
    });
};

/**
 * Fetch all users with their role information for admin panel dropdown selectors.
 *
 * Used by the Notification Hub panel to populate the "Target Host" and
 * "Selected Visitor" dropdowns with all registered users and their roles.
 *
 * @param {import('express').Request}  req
 * @param {import('express').Response} res
 */
exports.getUsers = (req, res) => {
    const sql = `
        SELECT u.user_id, u.full_name, u.email, u.role_id, r.role_name 
        FROM users u 
        LEFT JOIN roles r ON u.role_id = r.role_id 
        ORDER BY u.full_name ASC
    `;
    db.query(sql, (err, results) => {
        if (err) {
            console.error('Error fetching users:', err.message);
            return res.status(500).json({ error: 'Failed to fetch users.' });
        }
        res.json(results);
    });
};

const engineController = require('./engineController');

/**
 * Trigger a test notification event from the admin dashboard.
 *
 * Delegates directly to `engineController.calculateRoute` for full backward
 * compatibility. This ensures the admin test endpoint (`/api/notifications/test`)
 * executes the same complete pathfinding + notification workflow as the external
 * navigation endpoint (`/api/navigate`).
 *
 * @param {import('express').Request}  req
 * @param {import('express').Response} res
 */
exports.triggerTestNotification = async (req, res) => {
    return engineController.calculateRoute(req, res);
};
