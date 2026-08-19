const mysql = require('mysql2');

const isTidbOrSsl = (process.env.DB_PORT === '4000') || process.env.DB_SSL === 'true' || (process.env.DB_HOST && process.env.DB_HOST.includes('tidbcloud.com'));

const db = mysql.createPool({
    host: process.env.DB_HOST || '127.0.0.1',
    port: parseInt(process.env.DB_PORT || '3306', 10),
    user: process.env.DB_USER || 'root',
    password: process.env.DB_PASSWORD || process.env.DB_PASS || '',
    database: process.env.DB_NAME || 'smart_campus_db',
    ssl: isTidbOrSsl ? { rejectUnauthorized: false } : undefined,
    waitForConnections: true,
    connectionLimit: 10,
    queueLimit: 0
});

db.getConnection((err, connection) => {
    if (err) console.error('Database error:', err.message);
    else {
        console.log('Successfully connected to the MySQL database!');
        connection.release();
    }
});

module.exports = db;