const jwt = require('jsonwebtoken');

// Pull the secret securely from the .env file
const JWT_SECRET = process.env.JWT_SECRET;

const authenticateToken = (req, res, next) => {
    const authHeader = req.headers['authorization'];
    const match = typeof authHeader === 'string' && authHeader.match(/^Bearer ([^\s]+)$/i);
    if (!match || !JWT_SECRET) return res.status(401).json({ message: "Access Denied. Valid bearer token required." });

    jwt.verify(match[1], JWT_SECRET, { algorithms: ['HS256'] }, (err, user) => {
        if (err || !user || typeof user !== 'object' || !Number.isFinite(user.exp) || user.exp * 1000 <= Date.now()) {
            return res.status(401).json({ message: "Access Denied. Invalid or expired token." });
        }
        const role = user.role || user.type || user.admin_type;
        if (!['SUPER_ADMIN', 'SYSTEM_ADMIN', 'CONTENT_ADMIN'].includes(role)) {
            return res.status(403).json({ message: "Access Denied. Administrator role required." });
        }
        req.user = { ...user, role };
        next();
    });
};

module.exports = { authenticateToken, JWT_SECRET };
