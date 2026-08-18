const express = require('express');
const router = express.Router();
const multer = require('multer');
const path = require('path');
const mapController = require('../controllers/mapController');
const { authenticateToken } = require('../middleware/authMiddleware');

const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, path.join(__dirname, '../uploads/')),
    filename: (req, file, cb) => {
        const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
        cb(null, uniqueSuffix + path.extname(file.originalname));
    }
});
const upload = multer({ storage: storage });

router.get('/roles', mapController.getRoles);
router.get('/floorplans', mapController.getFloorplans);
router.get('/map-data/:id', mapController.getMapData);

// Protected Routes
router.get('/global-nodes', authenticateToken, mapController.getAllGlobalNodes);
router.post('/floorplans', authenticateToken, upload.single('floorplanImage'), mapController.uploadFloorplan);
router.put('/floorplans/:id', authenticateToken, mapController.updateFloorplan);
router.delete('/floorplans/:id', authenticateToken, mapController.deleteFloorplan);
router.post('/map-data', authenticateToken, mapController.saveMapData);

// ── AI Service Routes ──────────────────────────────────────────────────────────
// POST /api/wall-detection
//   Proxies Wall Detection requests to the Python AI microservice.
router.post('/wall-detection', authenticateToken, mapController.getWallDetection);
router.get('/ai-health', mapController.checkAIHealth);

// POST /api/analyze-floorplan
//   Phase 1 AI Analysis: Wall Detection → Room Detection → OCR → Room Node Generation.
//   Returns FloorplanAnalysisResult JSON for the frontend review panel.
router.post('/analyze-floorplan', authenticateToken, mapController.analyzeFloorplan);

module.exports = router;