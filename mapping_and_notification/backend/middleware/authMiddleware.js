const jwt = require('jsonwebtoken');

// Pull the secret securely from the .env file
const JWT_SECRET = process.env.JWT_SECRET;

const authenticateToken = (req, res, next) => {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.split(' ')[1];
    if (!token) return res.status(401).json({ message: "Access Denied. No token provided." });

    jwt.verify(token, JWT_SECRET, (err, user) => {
        if (err) return res.status(403).json({ message: "Invalid or expired session token." });
        req.user = user;
        next();
    });
};

module.exports = { authenticateToken, JWT_SECRET };