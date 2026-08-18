/**
 * @file queryAsync.js
 * @description Shared promise-based MySQL query helper for the Campus Navigation System backend.
 *
 * This module provides a single, centralized implementation of the `queryAsync`
 * utility, eliminating the need for each controller and service to define its own
 * promise wrapper around `db.query`. This follows the DRY (Don't Repeat Yourself)
 * principle and ensures consistent error handling across all database operations.
 *
 * Previously duplicated in:
 *   - controllers/engineController.js (as `queryAsync`)
 *   - controllers/mapController.js    (as `promiseQuery`)
 *   - services/notificationBuilder.js (as `queryAsync`)
 *   - services/notificationService.js (as `queryAsync`)
 */

const db = require('../config/db');

/**
 * Executes a MySQL query and returns a Promise.
 *
 * Wraps the callback-based `db.query` into a modern async/await compatible
 * Promise. Rejects with the database error on failure, resolves with the
 * query results on success.
 *
 * @param {string} sql - The SQL query string. Use `?` placeholders for parameters.
 * @param {Array} [params=[]] - An array of parameter values corresponding to `?` placeholders.
 * @returns {Promise<Array>} Resolves with the array of result rows from the database.
 * @throws {Error} Rejects with the MySQL error object if the query fails.
 *
 * @example
 * // Basic select
 * const users = await queryAsync('SELECT * FROM users WHERE role_id = ?', [3]);
 *
 * @example
 * // Insert and retrieve inserted ID
 * const result = await queryAsync(
 *   'INSERT INTO nodes (floorplan_id, coord_x, coord_y) VALUES (?, ?, ?)',
 *   [1, 100, 200]
 * );
 * console.log(result.insertId);
 */
const queryAsync = (sql, params = []) => {
    return new Promise((resolve, reject) => {
        db.query(sql, params, (err, results) => {
            if (err) reject(err);
            else resolve(results);
        });
    });
};

module.exports = queryAsync;
