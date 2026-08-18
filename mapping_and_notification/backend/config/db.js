const mysql = require('mysql2');

const db = mysql.createPool({
    host: process.env.DB_HOST,
    user: process.env.DB_USER,
    password: process.env.DB_PASS,
    database: process.env.DB_NAME
});

db.getConnection((err, connection) => {
    if (err) console.error('Database error:', err.message);
    else {
        console.log('Successfully connected to the MySQL database!');
        connection.release();
    }
});

module.exports = db;