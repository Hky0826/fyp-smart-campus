const express = require('express');
const router = express.Router();
const kioskController = require('../controllers/kioskController');
const mapController = require('../controllers/mapController');
const { authenticateKioskAccess } = require('../middleware/kioskAuthMiddleware');

// Public endpoint for mobile phones to retrieve active navigation session by token
router.get('/kiosk/session/:token', kioskController.getMobileSession);
router.get('/mobile-session/:token', kioskController.getMobileSession);
router.get('/mobile-route/:token', kioskController.renderMobileRoutePage);

// Protected kiosk endpoints (require JWT Bearer token or API key)
router.post('/kiosk/navigate', authenticateKioskAccess, kioskController.navigateForKiosk);
router.get('/kiosk/global-nodes', authenticateKioskAccess, kioskController.getKioskGlobalNodes);
router.get('/kiosk/roles', authenticateKioskAccess, mapController.getRoles);

module.exports = router;
