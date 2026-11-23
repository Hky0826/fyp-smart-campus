/**
 * @file kioskSessionService.js
 * @description Service for managing short-lived, unguessable mobile navigation sessions
 * and generating secure QR codes for the Campus Navigation Kiosk.
 */

'use strict';

const crypto = require('crypto');
const QRCode = require('qrcode');
const queryAsync = require('../utils/queryAsync');

let tableInitialized = false;

/**
 * Ensures the kiosk_sessions table exists in the database.
 */
async function initKioskSessionTable() {
    if (tableInitialized) return;
    try {
        await queryAsync(`
            CREATE TABLE IF NOT EXISTS kiosk_sessions (
                session_id INT AUTO_INCREMENT PRIMARY KEY,
                session_token VARCHAR(64) NOT NULL UNIQUE,
                current_location INT NOT NULL,
                destination_node INT NOT NULL,
                rbac_role VARCHAR(32) NOT NULL,
                walking_speed DECIMAL(4,2) DEFAULT 1.20,
                navigation_data LONGTEXT NOT NULL,
                map_context LONGTEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                INDEX idx_session_token (session_token),
                INDEX idx_expires_at (expires_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        `);
        tableInitialized = true;
    } catch (err) {
        console.error('[KioskSessionService] Failed to initialize kiosk_sessions table:', err.message);
    }
}

// Initialize table on service load
initKioskSessionTable();

/**
 * Resolves the mobile client base URL based on incoming request headers or environment variables.
 *
 * @param {import('express').Request} [req]
 * @returns {string} e.g. "http://localhost:3000" or "http://192.168.1.50:3000"
 */
function getMobileBaseUrl(req) {
    if (process.env.MOBILE_BASE_URL) {
        return process.env.MOBILE_BASE_URL.replace(/\/$/, '');
    }

    if (req) {
        const proto = req.headers['x-forwarded-proto'] || (req.secure ? 'https' : 'http');
        const host = req.headers['x-forwarded-host'] || req.headers.host;
        if (host) {
            return `${proto}://${host}`;
        }

        const origin = req.headers.origin;
        if (origin) {
            return origin.replace(/\/$/, '');
        }

        const referer = req.headers.referer;
        if (referer) {
            try {
                return new URL(referer).origin;
            } catch (_) {
                // Ignore parse error
            }
        }
    }

    return 'http://localhost:5000';
}

/**
 * Creates a secure, short-lived navigation session and generates a corresponding QR code data URL.
 *
 * @param {Object} params
 * @param {Object} params.navResult - Route navigation calculation result
 * @param {Object} params.mapContext - Role-filtered map context model
 * @param {number|string} params.startId - Starting node ID
 * @param {number|string} params.endId - Destination node ID
 * @param {number|string} params.roleId - RBAC role used
 * @param {number} [params.walkingSpeed=1.2] - Walking speed in m/s
 * @param {import('express').Request} [params.req] - Express request object for host resolution
 *
 * @returns {Promise<{session_token: string, mobile_url: string, qr_code_data_url: string, expires_at: string, expires_in_minutes: number}>}
 */
async function createSession({ navResult, mapContext, startId, endId, roleId, walkingSpeed = 1.2, req }) {
    await initKioskSessionTable();

    // Generate unguessable 48-character cryptographic hex token
    const token = crypto.randomBytes(24).toString('hex');

    // Configurable TTL (default: 15 minutes)
    const ttlMinutes = parseInt(process.env.KIOSK_SESSION_TTL_MINUTES || '15', 10);
    const expiresAt = new Date(Date.now() + ttlMinutes * 60 * 1000);

    const baseUrl = getMobileBaseUrl(req);
    const mobileUrl = `${baseUrl}/mobile-route/${token}`;

    // 1. Generate offline high-contrast QR code data URL
    const qrCodeDataUrl = await QRCode.toDataURL(mobileUrl, {
        width: 320,
        margin: 2,
        color: {
            dark: '#0f172a',  // slate-900
            light: '#ffffff'
        },
        errorCorrectionLevel: 'M'
    });

    // 2. Also save physical PNG to disk so Qt Quick / QML Image and browsers can load via HTTP URL
    const fs = require('fs');
    const path = require('path');
    const QR_DIR = path.resolve(__dirname, '..', 'uploads', 'qr_codes');
    if (!fs.existsSync(QR_DIR)) {
        fs.mkdirSync(QR_DIR, { recursive: true });
    }
    const qrFilename = `qr_${token}.png`;
    const qrFilePath = path.join(QR_DIR, qrFilename);
    try {
        await QRCode.toFile(qrFilePath, mobileUrl, {
            width: 320,
            margin: 2,
            color: {
                dark: '#0f172a',
                light: '#ffffff'
            },
            errorCorrectionLevel: 'M'
        });
    } catch (qrFileErr) {
        console.warn('[KioskSessionService] Could not write QR file:', qrFileErr.message);
    }
    const qrCodeUrl = `${baseUrl}/uploads/qr_codes/${qrFilename}`;
    const qrCodeFileUrl = `file:///${qrFilePath.replace(/\\/g, '/')}`;
    const qrCodeLocalUrl = `http://127.0.0.1:5000/uploads/qr_codes/${qrFilename}`;

    // Store the pre-filtered navigation data and map context in the database
    await queryAsync(
        `INSERT INTO kiosk_sessions 
         (session_token, current_location, destination_node, rbac_role, walking_speed, navigation_data, map_context, expires_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        [
            token,
            Number(startId) || 0,
            Number(endId) || 0,
            String(roleId || 'visitor'),
            Number(walkingSpeed) || 1.2,
            JSON.stringify(navResult),
            JSON.stringify(mapContext),
            expiresAt
        ]
    );

    return {
        session_token: token,
        mobile_url: mobileUrl,
        qr_code_data_url: qrCodeDataUrl,
        qr_code_url: qrCodeUrl,
        qr_code_local_url: qrCodeLocalUrl,
        qr_code_file_url: qrCodeFileUrl,
        expires_at: expiresAt.toISOString(),
        expires_in_minutes: ttlMinutes
    };
}

/**
 * Retrieves an active navigation session by token.
 * Strictly verifies the token format and that the session has not expired.
 *
 * @param {string} token
 * @returns {Promise<Object|null>}
 */
async function getSession(token) {
    if (!token || typeof token !== 'string' || !/^[a-f0-9]{48,64}$/i.test(token.trim())) {
        return null;
    }

    await initKioskSessionTable();

    const cleanToken = token.trim();
    const rows = await queryAsync(
        `SELECT session_token, current_location, destination_node, rbac_role, walking_speed,
                navigation_data, map_context, created_at, expires_at
         FROM kiosk_sessions
         WHERE session_token = ? AND expires_at > NOW()`,
        [cleanToken]
    );

    if (!rows || rows.length === 0) {
        return null;
    }

    const row = rows[0];
    let navData = null;
    let mapData = null;

    try {
        navData = typeof row.navigation_data === 'string' ? JSON.parse(row.navigation_data) : row.navigation_data;
    } catch (_) {
        navData = null;
    }

    try {
        mapData = typeof row.map_context === 'string' ? JSON.parse(row.map_context) : row.map_context;
    } catch (_) {
        mapData = null;
    }

    return {
        session_token: row.session_token,
        current_location: row.current_location,
        destination_node: row.destination_node,
        rbac_role: row.rbac_role,
        walking_speed: row.walking_speed,
        navigation: navData,
        map_context: mapData,
        created_at: row.created_at,
        expires_at: row.expires_at
    };
}

/**
 * Purges expired navigation sessions from the database.
 *
 * @returns {Promise<number>} Number of expired sessions deleted
 */
async function cleanupExpiredSessions() {
    try {
        await initKioskSessionTable();
        const result = await queryAsync(`DELETE FROM kiosk_sessions WHERE expires_at < NOW()`);
        const deleted = result?.affectedRows || 0;
        if (deleted > 0) {
            console.log(`[KioskSessionService] Purged ${deleted} expired navigation session(s).`);
        }
        return deleted;
    } catch (err) {
        console.error('[KioskSessionService] Error cleaning up expired sessions:', err.message);
        return 0;
    }
}

module.exports = {
    initKioskSessionTable,
    createSession,
    getSession,
    cleanupExpiredSessions,
    getMobileBaseUrl
};
