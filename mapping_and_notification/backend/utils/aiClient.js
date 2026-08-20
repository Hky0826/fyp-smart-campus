/**
 * @file aiClient.js
 * @description HTTP client for the Python AI microservice.
 *
 * This utility provides a clean interface for the Node.js backend to call
 * the Python AI service. All AI communication is centralised here so that:
 *   - The AI service URL is configured in a single place (.env)
 *   - Error handling is consistent across all AI calls
 *   - Timeouts are enforced to prevent hanging requests
 *   - Future AI modules only need new functions added here
 *
 * Uses Node.js 18+ native fetch and FormData (no npm package required).
 *
 * Communication pattern:
 *   React → Node.js (this module) → Python AI Service → Node.js → React
 */

const fs   = require('fs');
const path = require('path');

const AI_SERVICE_URL = process.env.AI_SERVICE_URL || 'http://localhost:8000';
const AI_TIMEOUT_MS  = parseInt(process.env.AI_TIMEOUT_MS || '30000', 10);

/**
 * Checks whether the Python AI service is reachable and healthy.
 *
 * @returns {Promise<boolean>} True if the service is healthy, false otherwise.
 */
async function checkAIServiceHealth() {
    try {
        const response = await fetch(`${AI_SERVICE_URL}/health`, {
            signal: AbortSignal.timeout(5000)
        });
        return response.ok;
    } catch {
        return false;
    }
}

/**
 * Sends a floorplan image to the Python AI service for wall detection.
 *
 * Reads the image file from disk using its stored path from the database,
 * forwards it to POST /api/v1/wall-detection, and returns the wall grid.
 *
 * The returned `grid` array is structurally identical to the `wallGrid`
 * React state in useOpenCV.js — 2D array of 0/1 integers, indexed [y][x].
 *
 * @param {string} imagePath    - Relative image path from the database (e.g. "/uploads/123.jpeg").
 *                                Will be resolved against the backend root directory.
 * @param {Object} [options]    - Optional parameters.
 * @param {number} [options.sensitivity=120]   - Binary threshold 0–255.
 * @param {number} [options.canvasWidth=800]   - Virtual canvas width.
 * @param {number} [options.canvasHeight=600]  - Virtual canvas height.
 * @param {number} [options.gridScale=8]       - Pixels per grid cell.
 *
 * @returns {Promise<Object>} The full JSON response from the AI service.
 * @throws {Error} If the image file is missing, the AI service is unreachable,
 *                 or the AI service returns a non-2xx response.
 */
/**
 * Safely unwraps the ProcessingResult schema from the AI service.
 * Standard schema: { status, version, algorithm, processing_time_ms, data }
 */
async function parseAndExtractData(response, endpointName) {
    if (!response.ok) {
        const errorBody = await response.text();
        throw new Error(`AI service returned HTTP ${response.status} for ${endpointName}: ${errorBody}`);
    }
    
    const json = await response.json();
    
    // Check if it's the standard wrapper
    if (json.status && json.data) {
        if (json.status !== 'success') {
            throw new Error(`AI service reported failure for ${endpointName}: ${json.message || 'Unknown error'}`);
        }
        return json.data;
    }
    
    // Fallback if the response is not wrapped (e.g. if an endpoint hasn't been updated)
    return json;
}

function resolveImagePath(imagePath) {
    const cleanPath = (imagePath || '').replace(/^\/?(uploads\/)?/, '');
    const filename = path.basename(cleanPath);
    const candidates = [
        path.join(__dirname, '../uploads', filename),
        path.join(__dirname, '..', cleanPath),
        path.join('/app/cloud/dashboard/backend/app/static/uploads', filename),
        path.join('/app/mapping_and_notification/backend/uploads', filename),
        path.join('/app/runtime-data/private/floorplans', filename),
        path.resolve(cleanPath)
    ];
    for (const p of candidates) {
        if (fs.existsSync(p)) return p;
    }
    return candidates[0];
}

async function detectWalls(imagePath, options = {}) {
    const {
        sensitivity   = 120,
        canvasWidth   = 800,
        canvasHeight  = 600,
        gridScale     = 8,
    } = options;

    const absolutePath = resolveImagePath(imagePath);
    if (!fs.existsSync(absolutePath)) {
        throw new Error(`Floorplan image file not found: ${absolutePath}`);
    }

    const fileBuffer = fs.readFileSync(absolutePath);
    const fileBlob   = new Blob([fileBuffer], { type: 'image/jpeg' });
    const filename   = path.basename(absolutePath);

    const form = new FormData();
    form.append('file',          fileBlob, filename);
    form.append('sensitivity',   String(sensitivity));
    form.append('canvas_width',  String(canvasWidth));
    form.append('canvas_height', String(canvasHeight));
    form.append('grid_scale',    String(gridScale));

    const response = await fetch(`${AI_SERVICE_URL}/api/v1/wall-detection`, {
        method:  'POST',
        body:    form,
        signal:  AbortSignal.timeout(AI_TIMEOUT_MS),
    });

    return parseAndExtractData(response, 'Wall Detection');
}

/**
 * Sends a floorplan image to the Python AI service for full Phase 1 analysis.
 *
 * Runs the complete pipeline: Image Preprocessing → Wall Detection →
 * Room Detection → OCR Text Detection → Room-Label Association →
 * Automatic Room Node Generation.
 *
 * @param {string} imagePath    - Relative image path from the database (e.g. "/uploads/123.jpeg").
 * @param {Object} [options]    - Optional tuning parameters.
 * @param {number} [options.canvasWidth=800]        - Virtual canvas width.
 * @param {number} [options.canvasHeight=600]       - Virtual canvas height.
 * @param {number} [options.sensitivity=120]        - Wall detection threshold 0–255.
 * @param {number} [options.gridScale=8]            - Pixels per grid cell.
 * @param {number} [options.roomGapClosePx=25]      - Door gap closing kernel size.
 * @param {number} [options.minRoomAreaPx=2000]     - Minimum room area (px²).
 * @param {number} [options.maxRoomAreaRatio=0.30]  - Max room area fraction of canvas.
 * @param {number} [options.minOcrConfidence=0.60]  - Minimum OCR confidence.
 * @param {number} [options.wallClearancePx=8]      - Node clearance from walls (px).
 *
 * @returns {Promise<Object>} The FloorplanAnalysisResult JSON from the AI service.
 * @throws {Error} If the image file is missing, the AI service is unreachable,
 *                 or the AI service returns a non-2xx response.
 */
async function analyzeFloorplan(imagePath, options = {}) {
    const {
        canvasWidth        = 800,
        canvasHeight       = 600,
        sensitivity        = 120,
        gridScale          = 8,
        roomGapClosePx     = 25,
        minRoomAreaPx      = 2000,
        maxRoomAreaRatio   = 0.30,
        minOcrConfidence   = 0.60,
        wallClearancePx    = 8,
    } = options;

    const absolutePath = resolveImagePath(imagePath);
    if (!fs.existsSync(absolutePath)) {
        throw new Error(`Floorplan image file not found: ${absolutePath}`);
    }

    const fileBuffer = fs.readFileSync(absolutePath);
    const fileBlob   = new Blob([fileBuffer], { type: 'image/jpeg' });
    const filename   = path.basename(absolutePath);

    const form = new FormData();
    form.append('file',                fileBlob, filename);
    form.append('canvas_width',        String(canvasWidth));
    form.append('canvas_height',       String(canvasHeight));
    form.append('sensitivity',         String(sensitivity));
    form.append('grid_scale',          String(gridScale));
    form.append('room_gap_close_px',   String(roomGapClosePx));
    form.append('min_room_area_px',    String(minRoomAreaPx));
    form.append('max_room_area_ratio', String(maxRoomAreaRatio));
    form.append('min_ocr_confidence',  String(minOcrConfidence));
    form.append('wall_clearance_px',   String(wallClearancePx));

    // Note: The analyze/floorplan endpoint returns a FloorplanAnalysisResult
    // directly (not wrapped in a ProcessingResult envelope), so we skip
    // parseAndExtractData and parse the JSON directly.
    const response = await fetch(`${AI_SERVICE_URL}/api/v1/analyze/floorplan`, {
        method: 'POST',
        body:   form,
        signal: AbortSignal.timeout(AI_TIMEOUT_MS * 3), // Allow more time for OCR
    });

    if (!response.ok) {
        const errorBody = await response.text();
        throw new Error(
            `AI service returned HTTP ${response.status} for Floorplan Analysis: ${errorBody}`
        );
    }

    return await response.json();
}

module.exports = {
    checkAIServiceHealth,
    detectWalls,
    analyzeFloorplan,
};
