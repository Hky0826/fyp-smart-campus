/**
 * @file kioskAuthMiddleware.js
 * @description Authentication middleware for Kiosk API routes.
 *
 * Secures kiosk endpoints against unauthenticated access.
 * Accepts either:
 *   1. A valid JWT Bearer token (issued upon Admin Portal login)
 *   2. A valid system API key (x-api-key header)
 *
 * If neither is valid, returns HTTP 401 Unauthorized.
 */

const jwt = require('jsonwebtoken');

const JWT_SECRET = process.env.JWT_SECRET;
const KIOSK_API_KEY = process.env.NAVIGATION_API_KEY || 'campus-nav-key';

const authenticateKioskAccess = (req, res, next) => {
    // 1. Check for JWT Bearer token
    const authHeader = req.headers['authorization'];
    const bearerToken = authHeader && authHeader.startsWith('Bearer ') ? authHeader.split(' ')[1] : null;

    if (bearerToken && JWT_SECRET) {
        try {
            const decoded = jwt.verify(bearerToken, JWT_SECRET);
            req.user = decoded;
            return next();
        } catch (jwtErr) {
            // Token was provided but invalid/expired; fall through to check API key
        }
    }

    // 2. Check for system API key
    const clientApiKey = req.headers['x-api-key'];
    if (clientApiKey && clientApiKey === KIOSK_API_KEY) {
        req.apiKeyAuth = true;
        return next();
    }

    // Neither valid JWT nor API key provided
    return res.status(401).json({
        message: 'Access Denied. Authentication required to access kiosk services.'
    });
};

module.exports = { authenticateKioskAccess };
