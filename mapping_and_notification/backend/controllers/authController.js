/**
 * @file authController.js
 * @description Authentication Controller for the Campus Navigation System Admin Panel.
 *
 * Handles admin login by validating credentials against the `admins` table,
 * comparing bcrypt password hashes, and issuing a signed JWT on success.
 *
 * The JWT payload contains the admin's email and `admin_type` (e.g. 'superadmin').
 * Tokens are valid for 8 hours by default.
 */

const db = require('../config/db');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const { JWT_SECRET } = require('../middleware/authMiddleware');

/**
 * Authenticate an admin user and return a signed JWT.
 *
 * Looks up the user by email via a JOIN between `users` and `admins`.
 * Compares the provided plain-text password against the stored bcrypt hash.
 * Returns a signed JWT and the admin's display name on success.
 *
 * @param {import('express').Request}  req - Body must contain `email` and `password`.
 * @param {import('express').Response} res
 */
exports.loginAdmin = (req, res) => {
    const { email, password } = req.body;
    if (!email || !password) return res.status(400).json({ message: "Email and password required." });

    const sql = `SELECT u.email, a.password_hash, a.admin_type, u.full_name 
                 FROM users u JOIN admins a ON u.user_id = a.user_id 
                 WHERE u.email = ?`;

    db.query(sql, [email], async (err, results) => {
        if (err) return res.status(500).json({ error: "Database error during login." });
        if (results.length === 0) return res.status(401).json({ message: "Invalid email or password." });

        const admin = results[0];
        const isMatch = await bcrypt.compare(password, admin.password_hash);

        if (!isMatch) return res.status(401).json({ message: "Invalid email or password." });

        const token = jwt.sign(
            { email: admin.email, type: admin.admin_type },
            JWT_SECRET,
            { expiresIn: '8h' }
        );
        res.json({ message: "Login successful", token, adminName: admin.full_name });
    });
};