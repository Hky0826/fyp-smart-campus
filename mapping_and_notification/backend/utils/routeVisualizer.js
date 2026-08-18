/**
 * @file routeVisualizer.js
 * @description Route Visualization Utility for the Campus Navigation System.
 *
 * Generates PNG images of the calculated route drawn over the relevant floorplan(s).
 *
 * Rendering style:
 *   Edges: dark slate (#1e293b) solid line with white glow underlay for contrast
 *   Arrows: dark slate filled triangles with white outline
 *   Start marker: teal (#14b8a6) ring + filled dot
 *   Destination marker: amber (#f59e0b) ring + filled dot
 *
 * Only floorplans with actual walking paths are rendered.
 * Intermediate transition-only floors (elevator/stairwell connections only) are skipped.
 *
 * Arrow direction is determined by the A* traversal direction (from_node_id → to_node_id),
 * NOT the database edge direction (source_node_id → destination_node_id).
 * When a bidirectional edge is traversed in reverse, the custom_path point sequence
 * is reversed to match the actual travel direction.
 *
 * Images are saved under backend/uploads/visualisations/ and returned as
 * { cid, filePath, filename, buildingName, floorLevel, floorplanId } objects for
 * CID-based email embedding.
 */

let createCanvas = null;
let loadImage = null;
try {
    const canvasPkg = require('canvas');
    createCanvas = canvasPkg.createCanvas;
    loadImage = canvasPkg.loadImage;
} catch (err) {
    // node-canvas not installed or not supported on this platform
}

const fs   = require('fs');
const path = require('path');
const queryAsync = require('./queryAsync');

// ─────────────────────────────────────────────────────────────────────────────
// OUTPUT DIRECTORY
// ─────────────────────────────────────────────────────────────────────────────

const VIS_DIR = path.join(__dirname, '..', 'uploads', 'visualisations');
if (!fs.existsSync(VIS_DIR)) {
    fs.mkdirSync(VIS_DIR, { recursive: true });
}

// ─────────────────────────────────────────────────────────────────────────────
// STYLING CONSTANTS
// ─────────────────────────────────────────────────────────────────────────────

const ROUTE_COLOR       = '#1e293b';  // slate-800 — high contrast dark route
const ROUTE_GLOW_COLOR  = '#ffffff';  // white glow underlay for contrast on any background
const START_COLOR       = '#14b8a6';  // teal-500 — start marker
const END_COLOR         = '#f59e0b';  // amber-400 — destination marker
const ARROW_COLOR       = '#1e293b';  // same as route for consistency
const ARROW_OUTLINE     = '#ffffff';  // white outline for arrow contrast

const EDGE_GLOW_WIDTH   = 14;
const EDGE_GLOW_ALPHA   = 0.7;
const EDGE_LINE_WIDTH   = 4.5;
const EDGE_LINE_ALPHA   = 1.0;

const NODE_GLOW_R       = 18;
const NODE_GLOW_ALPHA   = 0.22;
const NODE_RING_R       = 12;
const NODE_RING_WIDTH   = 3;
const NODE_DOT_R        = 6;

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/** Converts a hex colour string to an rgba() string with a given alpha. */
function hexToRgba(hex, alpha) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
}

/**
 * Draw the route edges for a single floorplan onto a Canvas context.
 * Includes smooth solid lines with white glow underlay and directional arrows.
 *
 * Arrow direction is determined by from_node_id → to_node_id (A* traversal),
 * NOT source_node_id → destination_node_id (DB storage).
 */
function drawRouteEdges(ctx, edgesOnFloor, nodeMap, scaleX, scaleY) {
    const avgScale = (scaleX + scaleY) / 2;
    for (const edge of edgesOnFloor) {
        // Resolve point sequence — prefer custom_path, fall back to node coords
        let pts = null;
        if (edge.custom_path) {
            try {
                const parsed = JSON.parse(edge.custom_path);
                if (parsed && parsed.length >= 2) {
                    // Compare DB edge direction (source_node_id) with A* traversal direction (from_node_id).
                    // If they differ, the edge is traversed in reverse — reverse the custom_path points.
                    pts = (Number(edge.source_node_id) === Number(edge.from_node_id))
                        ? parsed
                        : parsed.slice().reverse();
                }
            } catch (_) { /* fall through */ }
        }
        if (!pts) {
            const fromN = nodeMap[edge.from_node_id];
            const toN   = nodeMap[edge.to_node_id];
            if (!fromN || !toN) continue;
            pts = [
                { x: fromN.coord_x, y: fromN.coord_y },
                { x: toN.coord_x,   y: toN.coord_y   }
            ];
        }

        if (pts.length < 2) continue;

        // Map points from 800x600 logical canvas to original image coordinates
        const mappedPts = pts.map(p => ({ x: p.x * scaleX, y: p.y * scaleY }));

        // White glow underlay (for contrast on any background)
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(mappedPts[0].x, mappedPts[0].y);
        for (let i = 1; i < mappedPts.length; i++) ctx.lineTo(mappedPts[i].x, mappedPts[i].y);
        ctx.strokeStyle = hexToRgba(ROUTE_GLOW_COLOR, EDGE_GLOW_ALPHA);
        ctx.lineWidth   = EDGE_GLOW_WIDTH * avgScale;
        ctx.lineCap     = 'round';
        ctx.lineJoin    = 'round';
        ctx.setLineDash([]);
        ctx.stroke();
        ctx.restore();

        // Solid dark route line
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(mappedPts[0].x, mappedPts[0].y);
        for (let i = 1; i < mappedPts.length; i++) ctx.lineTo(mappedPts[i].x, mappedPts[i].y);
        ctx.strokeStyle = hexToRgba(ROUTE_COLOR, EDGE_LINE_ALPHA);
        ctx.lineWidth   = EDGE_LINE_WIDTH * avgScale;
        ctx.lineCap     = 'round';
        ctx.lineJoin    = 'round';
        ctx.setLineDash([]);
        ctx.stroke();
        ctx.restore();

        // Draw directional arrows along the segment
        ctx.save();
        for (let i = 1; i < mappedPts.length; i++) {
            const p1 = mappedPts[i - 1];
            const p2 = mappedPts[i];
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const dist = Math.hypot(dx, dy);
            
            // Only draw arrow if segment is long enough
            if (dist > 30 * avgScale) {
                const midX = p1.x + dx / 2;
                const midY = p1.y + dy / 2;
                const angle = Math.atan2(dy, dx);
                
                const arrowLen = 13 * avgScale;
                const arrowWidth = 7 * avgScale;
                
                ctx.beginPath();
                ctx.save();
                ctx.translate(midX, midY);
                ctx.rotate(angle);
                // Draw triangle pointing in the direction of travel (from_node → to_node)
                ctx.moveTo(arrowLen / 2, 0);
                ctx.lineTo(-arrowLen / 2, arrowWidth);
                ctx.lineTo(-arrowLen / 2, -arrowWidth);
                ctx.closePath();
                ctx.restore();

                // White outline for contrast
                ctx.strokeStyle = ARROW_OUTLINE;
                ctx.lineWidth = 2 * avgScale;
                ctx.lineJoin = 'round';
                ctx.stroke();

                // Fill arrow
                ctx.fillStyle = hexToRgba(ARROW_COLOR, 1.0);
                ctx.fill();
            }
        }
        ctx.restore();
    }
}

/**
 * Draw the route node markers for a single floorplan.
 * Only renders Start and Destination markers — intermediate nodes are hidden.
 * Uses room_label for node names (falls back to 'Location').
 */
function drawRouteNodes(ctx, nodesOnFloor, startNodeId, endNodeId, scaleX, scaleY) {
    const avgScale = (scaleX + scaleY) / 2;
    for (const node of nodesOnFloor) {
        const isStart = node.node_id === startNodeId;
        const isEnd   = node.node_id === endNodeId;

        // Only render Start and Destination markers
        if (!isStart && !isEnd) continue;

        // Map points from 800x600 logical canvas to original image coordinates
        const x = node.coord_x * scaleX;
        const y = node.coord_y * scaleY;

        const markerColor = isEnd ? END_COLOR : START_COLOR;

        // Outer glow disc
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, NODE_GLOW_R * avgScale, 0, Math.PI * 2);
        ctx.fillStyle = hexToRgba(markerColor, NODE_GLOW_ALPHA);
        ctx.fill();
        ctx.restore();

        // Ring
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, NODE_RING_R * avgScale, 0, Math.PI * 2);
        ctx.strokeStyle = hexToRgba(markerColor, 0.9);
        ctx.lineWidth   = NODE_RING_WIDTH * avgScale;
        ctx.stroke();
        ctx.restore();

        // Inner filled dot
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, NODE_DOT_R * avgScale, 0, Math.PI * 2);
        ctx.fillStyle = markerColor;
        ctx.fill();
        ctx.restore();

        // Text Labels (START / DESTINATION + room_label)
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.lineJoin = 'round';
        ctx.miterLimit = 2;

        const mainLabel = isStart ? 'START' : 'DESTINATION';
        const nodeName  = node.room_label || 'Location';

        // 1. Draw "START" / "DESTINATION"
        ctx.font = `bold ${14 * avgScale}px 'Inter', sans-serif`;
        const yOffsetMain = y - (24 * avgScale);
        
        // White outline for readability
        ctx.lineWidth = 4 * avgScale;
        ctx.strokeStyle = '#ffffff';
        ctx.strokeText(mainLabel, x, yOffsetMain);
        
        ctx.fillStyle = markerColor;
        ctx.fillText(mainLabel, x, yOffsetMain);

        // 2. Draw room_label
        ctx.font = `bold ${12 * avgScale}px 'Inter', sans-serif`;
        const yOffsetSub = y - (9 * avgScale);
        
        ctx.lineWidth = 4 * avgScale;
        ctx.strokeStyle = '#ffffff';
        ctx.strokeText(nodeName, x, yOffsetSub);
        
        ctx.fillStyle = '#334155';
        ctx.fillText(nodeName, x, yOffsetSub);

        ctx.restore();
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN EXPORT
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Generate route visualization images for the relevant floorplans.
 *
 * Renders only floorplans that contain actual walking paths.
 * Intermediate transition-only floorplans (floors only visited via elevator /
 * stairwell without a meaningful start/end point) are skipped.
 *
 * @param {Object}   routeResult        - Full result from `runNavigation`.
 * @param {Array}    routeResult.path   - Ordered array of node objects on the route.
 * @param {Array}    routeResult.edges_traversed - Ordered edge descriptors with source_node_id.
 * @param {string}   notificationId     - Unique ID used to form the output filename.
 *
 * @returns {Promise<Array<{cid, filePath, filename, buildingName, floorLevel, floorplanId}>>}
 */
async function generate(routeResult, notificationId) {
    const { path: routePath, edges_traversed: edgesTraversed } = routeResult;

    if (!createCanvas || !loadImage) {
        console.warn('[RouteVisualizer] node-canvas is not available; skipping static route image rendering.');
        return [];
    }

    if (!routePath || routePath.length < 2) {
        console.warn('[RouteVisualizer] Route path is too short to visualize.');
        return [];
    }

    const startNode = routePath[0];
    const endNode   = routePath[routePath.length - 1];

    // ── Build a lookup of all route nodes, keyed by node_id ──────────────────
    const routeNodeMap = {};
    for (const n of routePath) {
        routeNodeMap[n.node_id] = n;
    }

    // ── Determine which floorplans to render ──────────────────────────────────
    // Rule: Include START floorplan, DESTINATION floorplan, and any intermediate
    // floorplan that contains at least one actual navigable path/edge on that floor.
    // Intermediate floors that only contain cross-floor transitions are skipped.
    const targetFloorplanIdsSet = new Set();
    
    // Always include start and end
    targetFloorplanIdsSet.add(startNode.floorplan_id);
    targetFloorplanIdsSet.add(endNode.floorplan_id);

    // Include any floor that has a non-cross-floor edge
    for (const edge of edgesTraversed) {
        if (!edge.is_cross_floor) {
            const fromNode = routeNodeMap[edge.from_node_id];
            if (fromNode && fromNode.floorplan_id) {
                targetFloorplanIdsSet.add(fromNode.floorplan_id);
            }
        }
    }

    // ── Sort floorplans by route progression order ────────────────────────────
    const targetFloorplanIds = [];
    for (const node of routePath) {
        if (targetFloorplanIdsSet.has(node.floorplan_id) && !targetFloorplanIds.includes(node.floorplan_id)) {
            targetFloorplanIds.push(node.floorplan_id);
        }
    }

    // ── Fetch floorplan image paths from the database ─────────────────────────
    const fpRows = await queryAsync(
        `SELECT f.floorplan_id, f.image_path, f.floor_level, b.building_name
         FROM floorplans f
         JOIN buildings b ON f.building_id = b.building_id
         WHERE f.floorplan_id IN (?)`,
        [targetFloorplanIds]
    );

    const fpInfoMap = {};
    for (const row of fpRows) {
        fpInfoMap[row.floorplan_id] = row;
    }

    const results = [];

    for (const fpId of targetFloorplanIds) {
        const fpInfo = fpInfoMap[fpId];
        if (!fpInfo) {
            console.warn(`[RouteVisualizer] No DB record for floorplan_id=${fpId}. Skipping.`);
            continue;
        }

        // ── Collect route nodes on THIS floorplan ────────────────────────────
        const nodesOnFloor = routePath.filter(n => n.floorplan_id === fpId);
        if (nodesOnFloor.length === 0) continue;

        // ── Collect route edges on THIS floorplan (non-cross-floor only) ──────
        const edgesOnFloor = [];
        for (const edgeDesc of edgesTraversed) {
            if (edgeDesc.is_cross_floor) continue;
            const fromNode = routeNodeMap[edgeDesc.from_node_id];
            if (!fromNode || fromNode.floorplan_id !== fpId) continue;

            edgesOnFloor.push({
                from_node_id:   edgeDesc.from_node_id,
                to_node_id:     edgeDesc.to_node_id,
                source_node_id: edgeDesc.source_node_id,  // DB edge direction — for custom_path reversal
                custom_path:    edgeDesc.custom_path || null
            });
        }

        // ── Load the floorplan image ──────────────────────────────────────────
        const imageDiskPath = path.join(__dirname, '..', fpInfo.image_path);
        let floorplanImage = null;
        try {
            floorplanImage = await loadImage(imageDiskPath);
        } catch (err) {
            console.warn(`[RouteVisualizer] Could not load floorplan image: ${imageDiskPath} — ${err.message}`);
        }

        const canvasWidth  = floorplanImage ? floorplanImage.width  : 1200;
        const canvasHeight = floorplanImage ? floorplanImage.height : 900;

        // ── Create canvas and draw ────────────────────────────────────────────
        const canvas = createCanvas(canvasWidth, canvasHeight);
        const ctx    = canvas.getContext('2d');

        const CANVAS_WIDTH = 800;
        const CANVAS_HEIGHT = 600;
        const scaleX = canvasWidth / CANVAS_WIDTH;
        const scaleY = canvasHeight / CANVAS_HEIGHT;

        // Draw floorplan background
        if (floorplanImage) {
            ctx.drawImage(floorplanImage, 0, 0, canvasWidth, canvasHeight);
        } else {
            ctx.fillStyle = '#f1f5f9';
            ctx.fillRect(0, 0, canvasWidth, canvasHeight);
        }

        // Draw route edges and nodes
        drawRouteEdges(ctx, edgesOnFloor, routeNodeMap, scaleX, scaleY);
        drawRouteNodes(ctx, nodesOnFloor, startNode.node_id, endNode.node_id, scaleX, scaleY);

        // ── Save to disk ──────────────────────────────────────────────────────
        const safeBuilding = (fpInfo.building_name || 'building').replace(/[^a-zA-Z0-9_-]/g, '_');
        const filename = `route_${notificationId}_${safeBuilding}_f${fpInfo.floor_level}.png`;
        const filePath = path.join(VIS_DIR, filename);
        const cid      = `route-${notificationId}-fp${fpId}@campusnavigation`;

        const out = fs.createWriteStream(filePath);
        const pngStream = canvas.createPNGStream();

        await new Promise((resolve, reject) => {
            pngStream.pipe(out);
            out.on('finish', resolve);
            out.on('error', reject);
        });

        console.log(`[RouteVisualizer] Generated visualization: ${filePath}`);

        results.push({
            cid,
            filePath,
            filename,
            buildingName: fpInfo.building_name,
            floorLevel:   fpInfo.floor_level,
            floorplanId:  fpId
        });
    }

    return results;
}

/**
 * Remove visualization files older than the configured retention period.
 * Defaults to 24 hours. Triggered by the scheduled cleanup process.
 */
async function cleanupOldVisualizations() {
    const retentionHours = parseInt(process.env.VISUALISATION_RETENTION_HOURS || '24', 10);
    const cutoff = Date.now() - retentionHours * 60 * 60 * 1000;

    try {
        const files = fs.readdirSync(VIS_DIR);
        let removed = 0;
        for (const file of files) {
            if (!file.endsWith('.png')) continue;
            const fullPath = path.join(VIS_DIR, file);
            const stat = fs.statSync(fullPath);
            if (stat.mtimeMs < cutoff) {
                fs.unlinkSync(fullPath);
                removed++;
            }
        }
        if (removed > 0) {
            console.log(`[RouteVisualizer] Cleanup removed ${removed} old visualization file(s).`);
        }
    } catch (err) {
        console.error('[RouteVisualizer] Cleanup error:', err.message);
    }
}

module.exports = { generate, cleanupOldVisualizations };
