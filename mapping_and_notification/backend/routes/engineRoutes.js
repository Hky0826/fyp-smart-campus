const express = require('express');
const router = express.Router();
const engineController = require('../controllers/engineController');
const { authenticateToken } = require('../middleware/authMiddleware');
const { validateApiKey } = require('../middleware/apiKeyMiddleware');

// External endpoint — for LLM + RAG systems (API key via x-api-key header)
router.post('/navigate', validateApiKey, engineController.calculateRoute);

// Admin testing endpoint — for the admin dashboard (JWT bearer token required)
router.post('/navigate/admin-test', authenticateToken, engineController.calculateRoute);

module.exports = router;
