const express = require('express');
const router = express.Router();
const notificationController = require('../controllers/notificationController');
const { authenticateToken } = require('../middleware/authMiddleware');

// Get notification logs (JWT required)
router.get('/notifications', authenticateToken, notificationController.getNotifications);

// Get all users with roles (JWT required)
router.get('/notification-users', authenticateToken, notificationController.getUsers);

// Trigger a test notification (JWT required)
router.post('/notifications/test', authenticateToken, notificationController.triggerTestNotification);

module.exports = router;
