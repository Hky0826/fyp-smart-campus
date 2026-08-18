/**
 * @file mapController.js
 * @description Map Data Controller for the Campus Navigation System Admin Panel.
 *
 * Handles all CRUD operations for the map editor feature:
 *  - Roles and floorplan metadata retrieval
 *  - Floorplan image upload, update, and deletion (with orphaned building cleanup)
 *  - Node and edge UPSERT (insert-or-update) with full RBAC synchronization
 *  - Global node listing for cross-floor transition linking
 *  - AI wall detection proxy (delegates to Python AI microservice)
 *
 * All write operations are performed sequentially with promise-based queries
 * to ensure referential integrity without requiring explicit transactions.
 */

const db = require('../config/db');
const fs = require('fs');
const path = require('path');
const queryAsync = require('../utils/queryAsync');
const { detectWalls, checkAIServiceHealth, analyzeFloorplan } = require('../utils/aiClient');

// ─────────────────────────────────────────────────────────────────────────────
// READ ENDPOINTS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Fetch all campus roles ordered by role_id.
 * Used to populate role selectors in the map editor and navigation tester.
 *
 * @param {import('express').Request}  req
 * @param {import('express').Response} res
 */
exports.getRoles = (req, res) => {
    db.query('SELECT * FROM roles ORDER BY role_id ASC', (err, results) => {
        if (err) return res.status(500).json({ error: "Failed to fetch roles." });
        res.json(results);
    });
};

/**
 * Fetch all floorplans with their associated building name.
 * Results are ordered by building name and floor level for consistent dropdown display.
 *
 * @param {import('express').Request}  req
 * @param {import('express').Response} res
 */
exports.getFloorplans = (req, res) => {
    const sql = `SELECT f.floorplan_id, f.floor_level, f.scale_ratio, b.building_name 
                 FROM floorplans f JOIN buildings b ON f.building_id = b.building_id
                 ORDER BY b.building_name, f.floor_level`;
    db.query(sql, (err, results) => {
        if (err) return res.status(500).json({ error: "Failed to fetch floorplans." });
        res.json(results);
    });
};

/**
 * Fetch all nodes across every floorplan globally.
 * Used to populate the cross-floor transition linker dropdown,
 * which needs nodes from all floors simultaneously.
 *
 * Returns each node with its building name, floor level, node type,
 * and a comma-separated list of allowed role IDs.
 *
 * @param {import('express').Request}  req
 * @param {import('express').Response} res
 */
exports.getAllGlobalNodes = (req, res) => {
    const sql = `
        SELECT n.node_id, n.room_label, n.node_type, n.floorplan_id, f.floor_level, b.building_name,
               GROUP_CONCAT(nr.role_id) as allowed_roles
        FROM nodes n 
        JOIN floorplans f ON n.floorplan_id = f.floorplan_id 
        JOIN buildings b ON f.building_id = b.building_id
        LEFT JOIN node_rbac nr ON n.node_id = nr.node_id
        GROUP BY n.node_id
        ORDER BY b.building_name, f.floor_level, n.room_label
    `;
    db.query(sql, (err, results) => {
        if (err) return res.status(500).json({ error: "Failed to fetch global nodes." });
        res.json(results);
    });
};

/**
 * Fetch all map data for a single floorplan by ID.
 * Returns the floorplan metadata, all nodes (with RBAC), and all edges (with RBAC).
 *
 * Uses nested callback queries to assemble the complete data object:
 *   1. Fetch floorplan + building name
 *   2. Fetch all nodes for the floorplan
 *   3. Fetch node RBAC roles and attach to nodes
 *   4. Fetch all edges sourced from those nodes
 *   5. Fetch edge RBAC roles and attach to edges
 *
 * @param {import('express').Request}  req - Must contain `req.params.id` (floorplan ID).
 * @param {import('express').Response} res
 */
exports.getMapData = (req, res) => {
    const fpId = req.params.id;
    db.query('SELECT image_path, scale_ratio, building_id, floor_level FROM floorplans WHERE floorplan_id = ?', [fpId], (err, fpRes) => {
        if (err || fpRes.length === 0) return res.status(404).json({ error: 'Floorplan not found' });

        db.query('SELECT building_name FROM buildings WHERE building_id = ?', [fpRes[0].building_id], (err, bRes) => {
            const floorplanData = { ...fpRes[0], building_name: bRes[0].building_name };
            db.query('SELECT * FROM nodes WHERE floorplan_id = ?', [fpId], (err, nodes) => {
                if (err) return res.status(500).json({ error: 'Failed to load nodes' });
                if (nodes.length === 0) return res.json({ floorplan: floorplanData, nodes: [], edges: [] });

                const nodeIds = nodes.map(n => n.node_id);
                db.query('SELECT * FROM node_rbac WHERE node_id IN (?)', [nodeIds], (err, nodeRbac) => {
                    nodes.forEach(n => { n.allowed_roles = nodeRbac.filter(r => r.node_id === n.node_id).map(r => r.role_id); });

                    db.query('SELECT * FROM edges WHERE source_node_id IN (?)', [nodeIds], (err, edges) => {
                        if (err) return res.status(500).json({ error: 'Failed to load edges' });
                        if (edges.length === 0) return res.json({ floorplan: floorplanData, nodes, edges: [] });

                        const edgeIds = edges.map(e => e.edge_id);
                        db.query('SELECT * FROM edge_rbac WHERE edge_id IN (?)', [edgeIds], (err, edgeRbac) => {
                            edges.forEach(e => { e.allowed_roles = edgeRbac.filter(r => r.edge_id === e.edge_id).map(r => r.role_id); });
                            res.json({ floorplan: floorplanData, nodes, edges });
                        });
                    });
                });
            });
        });
    });
};

// ─────────────────────────────────────────────────────────────────────────────
// FLOORPLAN MANAGEMENT ENDPOINTS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Upload a new floorplan image and register it in the database.
 *
 * If the specified building name already exists, the floorplan is linked to the
 * existing building. Otherwise, a new building record is created automatically.
 *
 * Expects `req.file` from `multer` middleware and the following `req.body` fields:
 *   - `buildingName` {string}
 *   - `floorLevel`   {number}
 *   - `scaleRatio`   {number} (pixels to metres conversion factor)
 *
 * @param {import('express').Request}  req
 * @param {import('express').Response} res
 */
exports.uploadFloorplan = (req, res) => {
    if (!req.file) return res.status(400).json({ message: "No image file uploaded." });
    const { buildingName, floorLevel, scaleRatio } = req.body;

    const imagePath = `/uploads/${req.file.filename}`;

    /**
     * Inserts the new floorplan row into the database using a resolved building ID.
     * @param {number} bId - The building ID to associate with the floorplan.
     */
    const insertFloorplan = (bId) => {
        db.query(
            'INSERT INTO floorplans (building_id, floor_level, image_path, scale_ratio) VALUES (?, ?, ?, ?)',
            [bId, parseInt(floorLevel), imagePath, parseFloat(scaleRatio || 1.0)],
            (err, result) => {
                if (err) return res.status(500).json({ error: "Failed to save floorplan." });
                res.json({ message: "Successfully saved the floorplan into the database.", floorplan_id: result.insertId, image_path: imagePath });
            }
        );
    };

    db.query('SELECT building_id FROM buildings WHERE building_name = ?', [buildingName], (err, results) => {
        if (results.length > 0) insertFloorplan(results[0].building_id);
        else {
            db.query('INSERT INTO buildings (building_name) VALUES (?)', [buildingName], (err, insertResult) => {
                insertFloorplan(insertResult.insertId);
            });
        }
    });
};

/**
 * Update floorplan metadata (building name, floor level, scale ratio).
 *
 * If the building name changes, the floorplan is re-linked to an existing or new
 * building record. The old building is deleted if it has no remaining floorplans.
 *
 * @param {import('express').Request}  req - `req.params.id` is the floorplan ID.
 * @param {import('express').Response} res
 */
exports.updateFloorplan = (req, res) => {
    const fpId = req.params.id;
    const { buildingName, floorLevel, scaleRatio } = req.body;
    if (!buildingName || !floorLevel) return res.status(400).json({ message: "Building Name and Floor Level required." });

    db.query('SELECT building_id FROM floorplans WHERE floorplan_id = ?', [fpId], (err, fpRes) => {
        if (err || fpRes.length === 0) return res.status(404).json({ error: "Floorplan not found." });
        const oldBuildingId = fpRes[0].building_id;

        /**
         * Applies the floorplan update and cleans up the old building if it became orphaned.
         * @param {number} newBuildingId - The building ID to link to after update.
         */
        const updateFloorplanAndCleanup = (newBuildingId) => {
            db.query(
                'UPDATE floorplans SET building_id = ?, floor_level = ?, scale_ratio = ? WHERE floorplan_id = ?',
                [newBuildingId, parseInt(floorLevel), parseFloat(scaleRatio || 1.0), fpId],
                (err) => {
                    if (err) return res.status(500).json({ error: "Failed to update floorplan." });
                    if (oldBuildingId !== newBuildingId) {
                        db.query('SELECT COUNT(*) as count FROM floorplans WHERE building_id = ?', [oldBuildingId], (err, countRes) => {
                            if (!err && countRes[0].count === 0) {
                                db.query('DELETE FROM buildings WHERE building_id = ?', [oldBuildingId], () => {
                                    res.json({ message: "Floorplan updated and old unused building removed." });
                                });
                            } else res.json({ message: "Floorplan details updated successfully." });
                        });
                    } else res.json({ message: "Floorplan details updated successfully." });
                }
            );
        };

        db.query('SELECT building_id FROM buildings WHERE building_name = ?', [buildingName], (err, results) => {
            if (results.length > 0) updateFloorplanAndCleanup(results[0].building_id);
            else {
                db.query('INSERT INTO buildings (building_name) VALUES (?)', [buildingName], (err, insertResult) => {
                    updateFloorplanAndCleanup(insertResult.insertId);
                });
            }
        });
    });
};

/**
 * Delete a floorplan and all its associated data.
 *
 * Deletion sequence:
 *   1. Physically delete the floorplan image file from disk (with graceful fallback).
 *   2. Delete all edges connected to nodes on this floorplan.
 *   3. Delete all nodes on this floorplan.
 *   4. Delete the floorplan database record.
 *   5. Delete the parent building if it has no remaining floorplans.
 *
 * @param {import('express').Request}  req - `req.params.id` is the floorplan ID.
 * @param {import('express').Response} res
 */
exports.deleteFloorplan = (req, res) => {
    const fpId = req.params.id;
    db.query('SELECT building_id, image_path FROM floorplans WHERE floorplan_id = ?', [fpId], (err, fpRes) => {
        if (err || fpRes.length === 0) return res.status(404).json({ error: "Floorplan not found." });

        const oldBuildingId = fpRes[0].building_id;
        const imagePath = fpRes[0].image_path;
        const fullPath = path.join(__dirname, '../', imagePath);

        // Robust file deletion with error boundary — DB cleanup continues regardless
        try {
            if (fs.existsSync(fullPath)) {
                fs.unlinkSync(fullPath);
            } else {
                console.warn(`File not found on disk, skipping physical deletion: ${fullPath}`);
            }
        } catch (fileErr) {
            console.error(`Failed to delete physical file: ${fileErr.message}`);
        }

        /** Deletes the floorplan record and cleans up orphaned building. */
        const deleteFloorplanAndCheckBuilding = () => {
            db.query('DELETE FROM floorplans WHERE floorplan_id = ?', [fpId], () => {
                db.query('SELECT COUNT(*) as count FROM floorplans WHERE building_id = ?', [oldBuildingId], (err, countRes) => {
                    if (!err && countRes[0].count === 0) {
                        db.query('DELETE FROM buildings WHERE building_id = ?', [oldBuildingId], () =>
                            res.json({ message: "Map, file, and unused building deleted successfully." })
                        );
                    } else res.json({ message: "Map and file deleted successfully." });
                });
            });
        };

        db.query('SELECT node_id FROM nodes WHERE floorplan_id = ?', [fpId], (err, nodes) => {
            if (nodes && nodes.length > 0) {
                const nodeIds = nodes.map(n => n.node_id);
                db.query('DELETE FROM edges WHERE source_node_id IN (?) OR destination_node_id IN (?)', [nodeIds, nodeIds], () => {
                    db.query('DELETE FROM nodes WHERE floorplan_id = ?', [fpId], deleteFloorplanAndCheckBuilding);
                });
            } else deleteFloorplanAndCheckBuilding();
        });
    });
};

// ─────────────────────────────────────────────────────────────────────────────
// MAP DATA SAVE (UPSERT)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Save (upsert) the full map graph for a floorplan — nodes, edges, and their RBAC rules.
 *
 * This endpoint performs an intelligent diff-and-sync:
 *   1. Deletes nodes that were removed since the last save (with cascading edge deletion).
 *   2. UPSERTs each node (INSERT if new, UPDATE if existing) and syncs RBAC roles.
 *   3. Deletes edges that were removed since the last save.
 *   4. UPSERTs each edge and syncs edge RBAC roles.
 *
 * This approach safely preserves `node_id` and `edge_id` values across saves,
 * ensuring foreign key integrity with other tables (e.g., `notifications`).
 *
 * @param {import('express').Request}  req - Body must contain `floorplan_id`, `nodes`, `edges`.
 * @param {import('express').Response} res
 */
exports.saveMapData = async (req, res) => {
    const { floorplan_id, nodes, edges } = req.body;
    if (!floorplan_id) return res.status(400).json({ message: "Missing floorplan ID." });

    // Helper: promisified query on a specific connection (for transactions)
    const connQuery = (connection, sql, params = []) =>
        new Promise((resolve, reject) => {
            connection.query(sql, params, (err, results) => {
                if (err) reject(err);
                else resolve(results);
            });
        });

    // Get a dedicated connection from the pool for transaction safety
    const db = require('../config/db');
    let connection;
    try {
        connection = await new Promise((resolve, reject) => {
            db.getConnection((err, conn) => {
                if (err) reject(err);
                else resolve(conn);
            });
        });
    } catch (err) {
        console.error('[SaveMap] Failed to get DB connection:', err.message);
        return res.status(500).json({ message: 'Database connection error.' });
    }

    try {
        // Handle the case where all nodes have been deleted — clear entire floorplan
        if (!nodes || nodes.length === 0) {
            const currentNodesRes = await connQuery(connection, 'SELECT node_id FROM nodes WHERE floorplan_id = ?', [floorplan_id]);
            if (currentNodesRes.length > 0) {
                const nodeIds = currentNodesRes.map(n => n.node_id);
                await connQuery(connection, 'DELETE FROM edges WHERE source_node_id IN (?) OR destination_node_id IN (?)', [nodeIds, nodeIds]);
                await connQuery(connection, 'DELETE FROM nodes WHERE floorplan_id = ?', [floorplan_id]);
            }
            connection.release();
            return res.json({ message: "Map cleared successfully." });
        }

        // ── PRE-VALIDATE all edges before any database mutations ─────────────
        // Build a temporary index map to predict which node indices will resolve
        // to valid node IDs (existing nodes have node_id, new nodes will get one).
        if (edges && edges.length > 0) {
            for (let i = 0; i < edges.length; i++) {
                const e = edges[i];

                // Validate source node index exists in the nodes array
                if (e.start === undefined || e.start === null || e.start < 0 || e.start >= nodes.length) {
                    connection.release();
                    return res.status(400).json({
                        message: `Edge ${i}: source node index ${e.start} is out of range (0–${nodes.length - 1}).`
                    });
                }

                // Validate destination for same-floor edges
                if (!e.is_cross_floor) {
                    if (e.end === undefined || e.end === null || e.end < 0 || e.end >= nodes.length) {
                        connection.release();
                        return res.status(400).json({
                            message: `Edge ${i}: destination node index ${e.end} is out of range (0–${nodes.length - 1}).`
                        });
                    }
                } else {
                    // Cross-floor edges must have a valid target_node_id
                    if (!e.target_node_id) {
                        connection.release();
                        return res.status(400).json({
                            message: `Edge ${i}: cross-floor edge is missing target_node_id.`
                        });
                    }
                }
            }
        }

        // ── START TRANSACTION ────────────────────────────────────────────────
        await new Promise((resolve, reject) => {
            connection.beginTransaction(err => err ? reject(err) : resolve());
        });

        // 1. Identify and delete nodes that no longer exist in the payload
        const currentNodesRes = await connQuery(connection, 'SELECT node_id FROM nodes WHERE floorplan_id = ?', [floorplan_id]);
        const existingDbNodeIds = currentNodesRes.map(n => n.node_id);
        const payloadNodeIds    = nodes.map(n => n.node_id).filter(id => id != null);
        const nodesToDelete     = existingDbNodeIds.filter(id => !payloadNodeIds.includes(id));

        if (nodesToDelete.length > 0) {
            await connQuery(connection, 'DELETE FROM edges WHERE source_node_id IN (?) OR destination_node_id IN (?)', [nodesToDelete, nodesToDelete]);
            await connQuery(connection, 'DELETE FROM node_rbac WHERE node_id IN (?)', [nodesToDelete]);
            await connQuery(connection, 'DELETE FROM nodes WHERE node_id IN (?)', [nodesToDelete]);
        }

        // 2. UPSERT Nodes — resolves array indices to persistent database node_ids
        const indexToNodeId = {};
        for (let i = 0; i < nodes.length; i++) {
            const n = nodes[i];
            if (n.node_id) {
                // Update existing node
                await connQuery(connection,
                    'UPDATE nodes SET coord_x=?, coord_y=?, room_label=?, is_accessible=?, node_type=? WHERE node_id=?',
                    [n.x, n.y, n.room_label, n.is_accessible, n.node_type, n.node_id]
                );
                indexToNodeId[i] = n.node_id;
                // Clear and re-insert RBAC to handle role changes
                await connQuery(connection, 'DELETE FROM node_rbac WHERE node_id=?', [n.node_id]);
            } else {
                // Insert new node
                const insertRes = await connQuery(connection,
                    'INSERT INTO nodes (floorplan_id, coord_x, coord_y, room_label, is_accessible, node_type) VALUES (?, ?, ?, ?, ?, ?)',
                    [floorplan_id, n.x, n.y, n.room_label, n.is_accessible, n.node_type]
                );
                indexToNodeId[i] = insertRes.insertId;
            }

            // Insert RBAC role associations for this node
            if (n.allowed_roles && n.allowed_roles.length > 0) {
                const rbacValues = n.allowed_roles.map(rId => [indexToNodeId[i], rId]);
                await connQuery(connection, 'INSERT INTO node_rbac (node_id, role_id) VALUES ?', [rbacValues]);
            }
        }

        // 3. Identify and delete edges that no longer exist in the payload
        const allCurrentNodeIds = Object.values(indexToNodeId);
        if (allCurrentNodeIds.length > 0) {
            const existingEdgesRes  = await connQuery(connection, 'SELECT edge_id FROM edges WHERE source_node_id IN (?)', [allCurrentNodeIds]);
            const existingDbEdgeIds = existingEdgesRes.map(e => e.edge_id);
            const payloadEdgeIds    = edges ? edges.map(e => e.edge_id).filter(id => id != null) : [];
            const edgesToDelete     = existingDbEdgeIds.filter(id => !payloadEdgeIds.includes(id));

            if (edgesToDelete.length > 0) {
                await connQuery(connection, 'DELETE FROM edge_rbac WHERE edge_id IN (?)', [edgesToDelete]);
                await connQuery(connection, 'DELETE FROM edges WHERE edge_id IN (?)', [edgesToDelete]);
            }
        }

        // 4. UPSERT Edges — resolves array indices to persistent database edge_ids
        if (edges && edges.length > 0) {
            for (let i = 0; i < edges.length; i++) {
                const e = edges[i];
                const sourceId      = indexToNodeId[e.start];
                const destId        = e.is_cross_floor ? e.target_node_id : indexToNodeId[e.end];
                let currentEdgeId   = e.edge_id;

                // Validate resolved IDs (should not fail after pre-validation, but guard anyway)
                if (sourceId === undefined || sourceId === null) {
                    await new Promise((resolve, reject) => {
                        connection.rollback(() => resolve());
                    });
                    connection.release();
                    return res.status(400).json({
                        message: `Edge ${i}: source node at index ${e.start} could not be resolved to a valid database node ID.`
                    });
                }
                if (destId === undefined || destId === null) {
                    await new Promise((resolve, reject) => {
                        connection.rollback(() => resolve());
                    });
                    connection.release();
                    return res.status(400).json({
                        message: `Edge ${i}: destination node ${e.is_cross_floor ? '(cross-floor target_node_id ' + e.target_node_id + ')' : 'at index ' + e.end} could not be resolved.`
                    });
                }

                // 4.1 Validate Cross-Floor Transition Edges
                if (e.is_cross_floor && sourceId && destId) {
                    const sourceNodeRes = await connQuery(connection, `
                        SELECT n.node_type, b.building_name, f.floor_level 
                        FROM nodes n 
                        JOIN floorplans f ON n.floorplan_id = f.floorplan_id 
                        JOIN buildings b ON f.building_id = b.building_id
                        WHERE n.node_id = ?
                    `, [sourceId]);
                    
                    const destNodeRes = await connQuery(connection, `
                        SELECT n.node_type, b.building_name, f.floor_level 
                        FROM nodes n 
                        JOIN floorplans f ON n.floorplan_id = f.floorplan_id 
                        JOIN buildings b ON f.building_id = b.building_id
                        WHERE n.node_id = ?
                    `, [destId]);

                    if (destNodeRes.length === 0) {
                        await new Promise((resolve) => { connection.rollback(() => resolve()); });
                        connection.release();
                        return res.status(400).json({
                            message: `Edge ${i}: cross-floor target node ID ${destId} does not exist in the database.`
                        });
                    }

                    if (sourceNodeRes.length > 0 && destNodeRes.length > 0) {
                        const sType = sourceNodeRes[0].node_type;
                        const sBldg = sourceNodeRes[0].building_name;
                        const sFloor = sourceNodeRes[0].floor_level;
                        const dType = destNodeRes[0].node_type;
                        const dBldg = destNodeRes[0].building_name;
                        const dFloor = destNodeRes[0].floor_level;

                        if (sType === 'ELEVATOR' || sType === 'STAIRWELL' || dType === 'ELEVATOR' || dType === 'STAIRWELL') {
                            if (sType !== dType || sBldg !== dBldg || sFloor === dFloor) {
                                await new Promise((resolve) => { connection.rollback(() => resolve()); });
                                connection.release();
                                return res.status(400).json({ 
                                    message: "Invalid transition: Elevator and Stairwell nodes must connect to the same type, same building, and different floors only." 
                                });
                            }
                        }
                    }
                }

                if (currentEdgeId) {
                    // Update existing edge
                    await connQuery(connection,
                        'UPDATE edges SET source_node_id=?, destination_node_id=?, weight_distance=?, is_bidirectional=?, is_accessible=?, custom_path=? WHERE edge_id=?',
                        [sourceId, destId, parseFloat(e.weight), e.is_bidirectional ? 1 : 0, e.is_accessible, e.custom_path || null, currentEdgeId]
                    );
                    // Clear and re-insert RBAC to handle role changes
                    await connQuery(connection, 'DELETE FROM edge_rbac WHERE edge_id=?', [currentEdgeId]);
                } else {
                    // Insert new edge
                    const edgeRes = await connQuery(connection,
                        'INSERT INTO edges (source_node_id, destination_node_id, weight_distance, is_bidirectional, is_accessible, custom_path) VALUES (?, ?, ?, ?, ?, ?)',
                        [sourceId, destId, parseFloat(e.weight), e.is_bidirectional ? 1 : 0, e.is_accessible, e.custom_path || null]
                    );
                    currentEdgeId = edgeRes.insertId;
                }

                // Insert RBAC role associations for this edge
                if (e.allowed_roles && e.allowed_roles.length > 0) {
                    const edgeRbacValues = e.allowed_roles.map(rId => [currentEdgeId, rId]);
                    await connQuery(connection, 'INSERT INTO edge_rbac (edge_id, role_id) VALUES ?', [edgeRbacValues]);
                }
            }
        }

        // ── COMMIT ───────────────────────────────────────────────────────────
        await new Promise((resolve, reject) => {
            connection.commit(err => err ? reject(err) : resolve());
        });
        connection.release();

        res.json({ message: "Map data saved seamlessly." });
    } catch (error) {
        // ── ROLLBACK on any error ────────────────────────────────────────────
        try {
            await new Promise((resolve) => { connection.rollback(() => resolve()); });
        } catch (_) { /* rollback failed, connection may be broken */ }
        connection.release();

        console.error('[SaveMap] Transaction error:', error.message || error);
        const errorMsg = error.sqlMessage || error.message || 'Unknown database error.';
        res.status(500).json({ message: `Failed to save map data: ${errorMsg}` });
    }
};

// ─────────────────────────────────────────────────────────────────────────────
// AI WALL DETECTION PROXY
// ─────────────────────────────────────────────────────────────────────────────

// In-memory cache for Wall Detection results (Recommendation 2)
// Key: `${floorplan_id}_${sensitivity}_${grid_scale}`
const wallDetectionCache = {};

/**
 * Perform Wall Detection only, returning the WallGrid and timing metadata.
 * Used by the frontend to persistently render the wall overlay when a floorplan is selected.
 */
exports.getWallDetection = async (req, res) => {
    const { floorplan_id, sensitivity, canvas_width, canvas_height, grid_scale } = req.body;
    if (!floorplan_id) return res.status(400).json({ error: 'floorplan_id is required.' });

    try {
        const rows = await queryAsync('SELECT image_path FROM floorplans WHERE floorplan_id = ?', [floorplan_id]);
        if (!rows || rows.length === 0) return res.status(404).json({ success: false, error: `Floorplan not found.` });
        
        const imagePath = rows[0].image_path;
        const cacheKey = `${floorplan_id}_${sensitivity || 120}_${grid_scale || 8}`;
        
        if (wallDetectionCache[cacheKey]) {
            return res.json({ success: true, ...wallDetectionCache[cacheKey] });
        }

        const wallRes = await detectWalls(imagePath, {
            sensitivity: sensitivity !== undefined ? Number(sensitivity) : 120,
            canvasWidth: canvas_width !== undefined ? Number(canvas_width) : 800,
            canvasHeight: canvas_height !== undefined ? Number(canvas_height) : 600,
            gridScale: grid_scale !== undefined ? Number(grid_scale) : 8,
        });
        
        if (!wallRes || !wallRes.grid) throw new Error("Missing 'grid' in Wall Detection response.");
        
        const wallGrid = {
            grid: wallRes.grid,
            grid_width: wallRes.grid_width,
            grid_height: wallRes.grid_height,
            canvas_width: wallRes.canvas_width,
            canvas_height: wallRes.canvas_height,
            grid_scale: wallRes.grid_scale
        };

        const result = {
            wallGrid,
            timing: wallRes.processing_time_ms
        };
        
        wallDetectionCache[cacheKey] = result;
        res.json({ success: true, ...result });
    } catch (error) {
        console.error('[mapController] getWallDetection failed:', error.message);
        res.status(500).json({ success: false, error: error.message });
    }
};


/**
 * Health check proxy — confirms the Python AI service is reachable.
 *
 * @param {import('express').Request}  req
 * @param {import('express').Response} res
 */
exports.checkAIHealth = async (req, res) => {
    const healthy = await checkAIServiceHealth();
    if (healthy) {
        res.json({ status: 'ok', message: 'AI service is reachable.' });
    } else {
        res.status(503).json({ status: 'unavailable', message: 'AI service is not reachable.' });
    }
};

// ─────────────────────────────────────────────────────────────────────────────
// AI FLOORPLAN ANALYSIS PROXY (Phase 1)
// ─────────────────────────────────────────────────────────────────────────────

// In-memory cache for Floorplan Analysis results.
// Key: `${floorplan_id}_${sensitivity}_${room_gap_close_px}_${min_room_area_px}`
const floorplanAnalysisCache = {};

/**
 * Proxy the full Phase 1 AI Floorplan Analysis to the Python microservice.
 *
 * Reads the floorplan image from disk, forwards it with all tuning parameters
 * to POST /api/v1/analyze/floorplan, and returns the FloorplanAnalysisResult.
 *
 * The result is cached in memory by floorplan_id + key parameters to avoid
 * re-running the expensive OCR pipeline on identical requests.
 *
 * @param {import('express').Request}  req - Body must contain `floorplan_id`.
 * @param {import('express').Response} res
 */
exports.analyzeFloorplan = async (req, res) => {
    const {
        floorplan_id,
        sensitivity      = 120,
        room_gap_close_px = 25,
        min_room_area_px  = 2000,
        max_room_area_ratio = 0.30,
        min_ocr_confidence  = 0.60,
        wall_clearance_px   = 8,
        canvas_width  = 800,
        canvas_height = 600,
        grid_scale    = 8,
    } = req.body;

    if (!floorplan_id) {
        return res.status(400).json({ error: 'floorplan_id is required.' });
    }

    try {
        const rows = await queryAsync(
            'SELECT image_path FROM floorplans WHERE floorplan_id = ?',
            [floorplan_id]
        );
        if (!rows || rows.length === 0) {
            return res.status(404).json({ error: 'Floorplan not found.' });
        }

        const imagePath = rows[0].image_path;

        // Cache key — invalidated when key analysis parameters change
        const cacheKey = `${floorplan_id}_${sensitivity}_${room_gap_close_px}_${min_room_area_px}`;
        if (floorplanAnalysisCache[cacheKey]) {
            return res.json({ success: true, ...floorplanAnalysisCache[cacheKey] });
        }

        const result = await analyzeFloorplan(imagePath, {
            canvasWidth:      Number(canvas_width),
            canvasHeight:     Number(canvas_height),
            sensitivity:      Number(sensitivity),
            gridScale:        Number(grid_scale),
            roomGapClosePx:   Number(room_gap_close_px),
            minRoomAreaPx:    Number(min_room_area_px),
            maxRoomAreaRatio: Number(max_room_area_ratio),
            minOcrConfidence: Number(min_ocr_confidence),
            wallClearancePx:  Number(wall_clearance_px),
        });

        floorplanAnalysisCache[cacheKey] = result;
        res.json({ success: true, ...result });
    } catch (error) {
        console.error('[mapController] analyzeFloorplan failed:', error.message);
        res.status(500).json({ success: false, error: error.message });
    }
};