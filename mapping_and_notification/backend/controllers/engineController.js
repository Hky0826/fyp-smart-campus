/**
 * @file engineController.js
 * @description Navigation Engine Controller for the Campus Navigation System.
 *
 * This controller implements the core multi-floor A* pathfinding algorithm,
 * natural-language instruction generation, RBAC-aware route filtering, and
 * the RabbitMQ-backed notification trigger workflow.
 *
 * Key responsibilities:
 *  - `runNavigation`   — pure navigation calculation (reusable, no HTTP context)
 *  - `calculateRoute`  — Express route handler; runs navigation + optional notification trigger
 *
 * Algorithms:
 *  - A* search with Euclidean heuristic across a multi-floor graph
 *  - Turn detection using 2D cross-product geometry
 *  - Instruction merging for consecutive straight-walk segments
 *
 * Features supported:
 *  - Multi-floor and multi-building campus routing
 *  - RBAC (role-based access control) for nodes and edges
 *  - Custom path waypoint geometry (curve-following instructions)
 *  - Elevator / stairwell / entrance transition time estimates
 *  - Optional real-time notification dispatch via RabbitMQ
 */

const queryAsync = require('../utils/queryAsync');
const { buildNotifications } = require('../services/notificationBuilder');
const { publishNotification } = require('../utils/mqBroker');

// ─────────────────────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────────────────────

/** Node types that represent cross-floor or cross-building transition points. */
const TRANSITION_TYPES = new Set(['ELEVATOR', 'STAIRWELL', 'ENTRANCE']);

/** Average adult walking speed in metres per second. Used for ETA calculations. */
const WALKING_SPEED_MS = 1.2;

/**
 * Angle threshold in radians below which a turn is considered "straight ahead".
 * Approximately 20 degrees.
 */
const STRAIGHT_ANGLE_THRESHOLD = Math.PI / 9;

// ─────────────────────────────────────────────────────────────────────────────
// GEOMETRY HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Checks whether a node qualifies as a corridor (non-landmark) node.
 * Corridor nodes are excluded from turn-point landmark labels in instructions.
 *
 * @param {Object|null} node - A node object with optional `node_type` and `room_label`.
 * @returns {boolean} True if the node is a corridor or has no meaningful label.
 */
const isCorridor = (node) => {
    if (!node) return true;
    if (node.node_type === 'CORRIDOR') return true;
    if (node.room_label) {
        const label = node.room_label.trim().toLowerCase();
        if (label === 'corridor' || label.startsWith('corridor ') || label.startsWith('corridor-')) {
            return true;
        }
    }
    return false;
};

/**
 * Euclidean heuristic for A* (same-floor). Falls back to 0 for cross-floor
 * pairs so the algorithm degrades to cost-only Dijkstra when appropriate.
 *
 * @param {Object} nodeA - A node with `floorplan_id`, `coord_x`, `coord_y`, `scale_ratio`.
 * @param {Object} nodeB - The target node.
 * @returns {number} Estimated real-world distance in metres between the two nodes.
 */
const heuristic = (nodeA, nodeB) => {
    if (nodeA.floorplan_id !== nodeB.floorplan_id) return 0;
    const dx = nodeA.coord_x - nodeB.coord_x;
    const dy = nodeA.coord_y - nodeB.coord_y;
    // Scale pixel distance to real-world metres using the floorplan scale_ratio
    return Math.sqrt(dx * dx + dy * dy) * (nodeA.scale_ratio || 1.0);
};

/**
 * Determine the turn direction at a node given the incoming and outgoing vectors.
 * Uses screen-space coordinates (Y-axis pointing down).
 *
 * @param {{ dx: number, dy: number }} inVec  - Incoming direction vector.
 * @param {{ dx: number, dy: number }} outVec - Outgoing direction vector.
 * @returns {'straight'|'left'|'right'} The turn classification.
 */
const getTurnDirection = (inVec, outVec) => {
    const mag1 = Math.hypot(inVec.dx, inVec.dy);
    const mag2 = Math.hypot(outVec.dx, outVec.dy);
    if (mag1 < 0.001 || mag2 < 0.001) return 'straight';

    // Normalise both vectors
    const n1 = { dx: inVec.dx / mag1, dy: inVec.dy / mag1 };
    const n2 = { dx: outVec.dx / mag2, dy: outVec.dy / mag2 };

    // Cross product (z-component) and dot product
    const cross = n1.dx * n2.dy - n1.dy * n2.dx;
    const dot   = n1.dx * n2.dx + n1.dy * n2.dy;
    const angle = Math.atan2(Math.abs(cross), dot);

    if (angle < STRAIGHT_ANGLE_THRESHOLD) return 'straight';
    // Screen coords (Y-down): cross > 0 → clockwise → visual right turn
    return cross > 0 ? 'right' : 'left';
};

/**
 * Derives the DEPARTURE direction vector from a node along an edge.
 * Prefers custom_path waypoints; falls back to straight-line node coordinates.
 * Reverses waypoint order when traversing a bidirectional edge in reverse.
 *
 * @param {Object|null} dbEdge    - Raw edge row from the database.
 * @param {number}      fromNodeId - The ID of the node being departed from.
 * @param {Object}      fromNode  - Node object at the departure end.
 * @param {Object}      toNode    - Node object at the arrival end.
 * @returns {{ dx: number, dy: number }} Direction vector of departure.
 */
const getDepartureVector = (dbEdge, fromNodeId, fromNode, toNode) => {
    if (dbEdge && dbEdge.custom_path) {
        try {
            let pts = JSON.parse(dbEdge.custom_path);
            if (pts && pts.length >= 2) {
                // Reverse if traversing the edge in the opposite direction it was stored
                if (Number(dbEdge.source_node_id) !== Number(fromNodeId)) {
                    pts = pts.slice().reverse();
                }
                return { dx: pts[1].x - pts[0].x, dy: pts[1].y - pts[0].y };
            }
        } catch (_) { /* fall through to node-coordinate fallback */ }
    }
    return { dx: toNode.coord_x - fromNode.coord_x, dy: toNode.coord_y - fromNode.coord_y };
};

/**
 * Derives the ARRIVAL direction vector approaching a node along an edge.
 * Prefers custom_path waypoints; falls back to straight-line node coordinates.
 * Reverses waypoint order when traversing a bidirectional edge in reverse.
 *
 * @param {Object|null} dbEdge    - Raw edge row from the database.
 * @param {number}      fromNodeId - The ID of the node being departed from.
 * @param {Object}      fromNode  - Node object at the departure end.
 * @param {Object}      toNode    - Node object at the arrival end.
 * @returns {{ dx: number, dy: number }} Direction vector of arrival.
 */
const getArrivalVector = (dbEdge, fromNodeId, fromNode, toNode) => {
    if (dbEdge && dbEdge.custom_path) {
        try {
            let pts = JSON.parse(dbEdge.custom_path);
            if (pts && pts.length >= 2) {
                if (Number(dbEdge.source_node_id) !== Number(fromNodeId)) {
                    pts = pts.slice().reverse();
                }
                const last = pts[pts.length - 1];
                const prev = pts[pts.length - 2];
                return { dx: last.x - prev.x, dy: last.y - prev.y };
            }
        } catch (_) { /* fall through */ }
    }
    return { dx: toNode.coord_x - fromNode.coord_x, dy: toNode.coord_y - fromNode.coord_y };
};

/**
 * Formats an elapsed-seconds value as a human-readable duration string.
 *
 * @param {number} seconds - Total elapsed seconds.
 * @returns {string} E.g. "3 min 20 sec" or "45 sec".
 */
const formatTime = (seconds) => {
    if (seconds < 60) return `${seconds} sec`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return secs > 0 ? `${mins} min ${secs} sec` : `${mins} min`;
};

// ─────────────────────────────────────────────────────────────────────────────
// INSTRUCTION GENERATION
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Converts the ordered node path and edge list into natural-language
 * navigation instructions. Key behaviours:
 *  - Merges consecutive straight-walking segments into a single instruction.
 *  - Ignores intermediate nodes that do not represent meaningful direction changes.
 *  - Prefers custom_path geometry over node coordinates for geometry.
 *  - Uses room_label as a landmark wherever possible.
 *  - Emits a transition instruction for floor / building crossings.
 *
 * @param {Array<Object>} pathNodes      - Ordered array of node objects on the route.
 * @param {Array<Object>} edgesTraversed - Ordered array of edge traversal descriptors.
 * @param {Object}        edgeLookup     - Map of `"fromId-toId"` → raw DB edge row.
 * @returns {Array<Object>} Array of instruction step objects, each with `type`, `action`, `description`, etc.
 */
function generateInstructions(pathNodes, edgesTraversed, edgeLookup) {
    if (pathNodes.length < 2) return [];

    const instructions = [];
    const startNode = pathNodes[0];
    const destNode  = pathNodes[pathNodes.length - 1];

    // 1. Build a fine-grained array of coordinate points representing the entire route path
    const routePoints = [];

    // Push the starting point corresponding to startNode
    routePoints.push({
        x: startNode.coord_x,
        y: startNode.coord_y,
        floorplan_id: startNode.floorplan_id,
        floor_level: startNode.floor_level,
        building_name: startNode.building_name,
        scale_ratio: startNode.scale_ratio,
        node: startNode,
        isTransitionAfter: false,
        metersFromPrev: 0
    });

    for (let i = 0; i < edgesTraversed.length; i++) {
        const edge = edgesTraversed[i];
        const fromNode = pathNodes[i];
        const toNode = pathNodes[i + 1];

        if (edge.is_cross_floor) {
            // Flag the last added point as having a transition after it
            if (routePoints.length > 0) {
                routePoints[routePoints.length - 1].isTransitionAfter = true;
            }
            // Add the toNode as a new segment start point on the new floor
            routePoints.push({
                x: toNode.coord_x,
                y: toNode.coord_y,
                floorplan_id: toNode.floorplan_id,
                floor_level: toNode.floor_level,
                building_name: toNode.building_name,
                scale_ratio: toNode.scale_ratio,
                node: toNode,
                isTransitionAfter: false,
                metersFromPrev: parseFloat(edge.weight_distance) || 0
            });
        } else {
            // Internal floor segment — resolve custom path geometry if available
            const dbEdge = edgeLookup[`${edge.from_node_id}-${edge.to_node_id}`]
                        || edgeLookup[`${edge.to_node_id}-${edge.from_node_id}`]
                        || null;

            let pts = null;
            if (dbEdge && dbEdge.custom_path) {
                try {
                    const parsed = JSON.parse(dbEdge.custom_path);
                    if (parsed && parsed.length >= 2) {
                        pts = parsed;
                        if (Number(dbEdge.source_node_id) !== Number(edge.from_node_id)) {
                            pts = pts.slice().reverse();
                        }
                    }
                } catch (_) {
                    pts = null;
                }
            }

            if (!pts) {
                pts = [
                    { x: fromNode.coord_x, y: fromNode.coord_y },
                    { x: toNode.coord_x, y: toNode.coord_y }
                ];
            }

            // Calculate pixel lengths of all segments
            const segPxLengths = [];
            let totalPxLength = 0;
            for (let j = 0; j < pts.length - 1; j++) {
                const dx = pts[j + 1].x - pts[j].x;
                const dy = pts[j + 1].y - pts[j].y;
                const dist = Math.hypot(dx, dy);
                segPxLengths.push(dist);
                totalPxLength += dist;
            }

            const totalMeters = parseFloat(edge.weight_distance) || 0;
            const scaleFactor = totalMeters / (totalPxLength || 1);

            // Add intermediate points and end point of this edge
            for (let j = 1; j < pts.length; j++) {
                const P = pts[j];
                const segMeters = segPxLengths[j - 1] * scaleFactor;
                const isEndNode = (j === pts.length - 1);

                routePoints.push({
                    x: P.x,
                    y: P.y,
                    floorplan_id: fromNode.floorplan_id,
                    floor_level: fromNode.floor_level,
                    building_name: fromNode.building_name,
                    scale_ratio: fromNode.scale_ratio,
                    node: isEndNode ? toNode : null,
                    isTransitionAfter: false,
                    metersFromPrev: segMeters
                });
            }
        }
    }

    // 2. Loop through routePoints to generate the steps

    // Emit the "Depart" step
    instructions.push({
        type: 'start',
        action: 'depart',
        node_id: startNode.node_id,
        label: startNode.room_label || null,
        floorplan_id: startNode.floorplan_id,
        floor_level: startNode.floor_level,
        building_name: startNode.building_name,
        instruction: `Start from ${startNode.room_label || `Node ${startNode.node_id}`}`,
        description: `Start from ${startNode.room_label || `Node ${startNode.node_id}`}`
    });

    let accumDistance = 0;
    let passedLandmarks = [];

    /**
     * Emits a "walk straight" instruction step, merging accumulated distance
     * and any passed landmarks into a single human-readable string.
     *
     * @param {number}   dist      - Total walking distance in metres for this segment.
     * @param {string[]} landmarks - Array of room labels passed along the way.
     */
    const emitWalkStep = (dist, landmarks, floorCtx) => {
        const { walkFloorplanId, walkFloorLevel, walkBuildingName } = floorCtx || {};
        const roundedDist = Math.round(dist);
        const uniqueLandmarks = [...new Set(landmarks.map(l => l.trim()))].filter(Boolean);
        let desc = `Walk straight for ${roundedDist} metres.`;
        if (uniqueLandmarks.length > 0) {
            desc = `Walk straight for ${roundedDist} metres, passing ${uniqueLandmarks.join(', ')}.`;
        }
        instructions.push({
            type: 'walk',
            action: 'straight',
            distance_m: roundedDist,
            floorplan_id: walkFloorplanId,
            floor_level: walkFloorLevel,
            building_name: walkBuildingName,
            instruction: desc,
            description: desc
        });
    };

    for (let i = 1; i < routePoints.length; i++) {
        const prevPt = routePoints[i - 1];
        const currPt = routePoints[i];
        accumDistance += currPt.metersFromPrev;

        if (prevPt.isTransitionAfter) {
            // Flush walking distance accumulated before this transition
            if (accumDistance - currPt.metersFromPrev > 0.05) {
                emitWalkStep(accumDistance - currPt.metersFromPrev, passedLandmarks, {
                    walkFloorplanId: prevPt.floorplan_id,
                    walkFloorLevel: prevPt.floor_level,
                    walkBuildingName: prevPt.building_name
                });
                passedLandmarks = [];
            }
            accumDistance = 0;

            // Determine transition type and emit the transition instruction
            const transType =
                prevPt.node.node_type === 'ELEVATOR'  ? 'elevator'  :
                prevPt.node.node_type === 'STAIRWELL' ? 'stairwell' : 'entrance';
            const fromFloor = prevPt.floor_level;
            const toFloor = currPt.floor_level;
            const fromBldg = prevPt.building_name;
            const toBldg = currPt.building_name;
            const isBldgSwap = fromBldg !== toBldg;

            let transText;
            if (isBldgSwap) {
                const via = (prevPt.node.room_label && !isCorridor(prevPt.node)) ? ` via ${prevPt.node.room_label}` : '';
                transText = `Exit${via} and continue to ${toBldg}`;
            } else {
                const verb =
                    transType === 'elevator'  ? 'Take the elevator'   :
                    transType === 'stairwell' ? 'Take the stairwell'  :
                                                'Continue through the entrance';
                const landmark = (prevPt.node.room_label && !isCorridor(prevPt.node)) ? ` (${prevPt.node.room_label})` : '';
                transText = `${verb}${landmark} to Level ${toFloor}`;
            }

            instructions.push({
                type: 'transition',
                action: transType,
                from_floor: fromFloor,
                to_floor: toFloor,
                from_building: fromBldg,
                to_building: toBldg,
                node_id: prevPt.node.node_id,
                label: prevPt.node.room_label || null,
                floorplan_id: prevPt.floorplan_id,
                floor_level: prevPt.floor_level,
                building_name: prevPt.building_name,
                instruction: transText,
                description: transText
            });
        } else {
            // Normal path segment — check for direction change at currPt
            const nextPt = routePoints[i + 1];
            if (nextPt && nextPt.floorplan_id === currPt.floorplan_id) {
                const inVec = { dx: currPt.x - prevPt.x, dy: currPt.y - prevPt.y };
                const outVec = { dx: nextPt.x - currPt.x, dy: nextPt.y - currPt.y };
                const turn = getTurnDirection(inVec, outVec);

                if (turn !== 'straight') {
                    // Flush accumulated straight-walk distance before the turn
                    if (accumDistance > 0.05) {
                        emitWalkStep(accumDistance, passedLandmarks, {
                            walkFloorplanId: currPt.floorplan_id,
                            walkFloorLevel: currPt.floor_level,
                            walkBuildingName: currPt.building_name
                        });
                        accumDistance = 0;
                        passedLandmarks = [];
                    }

                    const isCorridorNode = currPt.node && isCorridor(currPt.node);
                    const landmarkName = (currPt.node && !isCorridorNode) ? currPt.node.room_label : null;
                    const turnText = landmarkName ? `Turn ${turn} at ${landmarkName}` : `Turn ${turn}`;
                    instructions.push({
                        type: 'turn',
                        action: turn,
                        direction: turn,
                        node_id: currPt.node ? currPt.node.node_id : null,
                        label: landmarkName,
                        floorplan_id: currPt.floorplan_id,
                        floor_level: currPt.floor_level,
                        building_name: currPt.building_name,
                        instruction: turnText,
                        description: turnText
                    });
                    continue; // Skip adding this node to passed landmarks since it's a turn point
                }
            }

            // If it's a straight-through node with a label, add as a passed landmark (excluding corridors)
            if (currPt.node && currPt.node.room_label && currPt.node.node_id !== destNode.node_id) {
                if (!isCorridor(currPt.node)) {
                    passedLandmarks.push(currPt.node.room_label);
                }
            }
        }
    }

    // Flush any final walk distance that hasn't been emitted yet
    if (accumDistance > 0.05) {
        emitWalkStep(accumDistance, passedLandmarks, {
            walkFloorplanId: routePoints[routePoints.length - 1].floorplan_id,
            walkFloorLevel: routePoints[routePoints.length - 1].floor_level,
            walkBuildingName: routePoints[routePoints.length - 1].building_name
        });
    }

    // Emit the "Arrive" step
    instructions.push({
        type: 'arrive',
        action: 'destination',
        node_id: destNode.node_id,
        label: destNode.room_label || null,
        floorplan_id: destNode.floorplan_id,
        floor_level: destNode.floor_level,
        building_name: destNode.building_name,
        instruction: `You have arrived at ${destNode.room_label || `Node ${destNode.node_id}`}`,
        description: `You have arrived at ${destNode.room_label || `Node ${destNode.node_id}`}`
    });

    return instructions;
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN ROUTE HANDLER
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Core navigation calculation function. Fetches all graph nodes and edges from
 * the database, applies RBAC filtering, runs A* pathfinding, and returns a full
 * route result object including path, instructions, and visualisation data.
 *
 * This function is separated from the HTTP handler so it can be called from other
 * controllers (e.g., the notification test endpoint) without an HTTP context.
 *
 * @param {Object} params
 * @param {string|number} params.currentLocation - Start node ID or room label.
 * @param {string|number} params.destinationNode - End node ID or room label.
 * @param {string|number} params.rbacRole        - Role ID or role name (e.g. 'admin', 'student').
 * @param {number}        [params.walkingSpeed=1.2] - Walking speed in m/s.
 * @returns {Promise<Object>} Full route result with path, route_summary, instructions, and visualisation.
 * @throws {{ status: number, message: string, noRoute?: boolean }} On missing nodes, same start/end, or no valid route.
 */
exports.runNavigation = async ({ currentLocation, destinationNode, rbacRole, walkingSpeed = 1.2 }) => {
    // Resolve string role names to their numeric IDs
    let userRoleId = Number(rbacRole);
    if (isNaN(userRoleId)) {
        const roleLower = String(rbacRole).toLowerCase();
        if (roleLower === 'admin') userRoleId = 1;
        else if (roleLower === 'staff') userRoleId = 2;
        else if (roleLower === 'student') userRoleId = 3;
        else if (roleLower === 'visitor') userRoleId = 4;
    }

    // Fetch all nodes with building/floor context and their RBAC roles
    const sqlNodes = `
        SELECT n.node_id, n.coord_x, n.coord_y, n.room_label, n.node_type, n.is_accessible,
               n.floorplan_id, f.floor_level, f.scale_ratio, b.building_id, b.building_name,
               GROUP_CONCAT(nr.role_id) AS allowed_roles
        FROM nodes n
        JOIN floorplans f ON n.floorplan_id = f.floorplan_id
        JOIN buildings  b ON f.building_id  = b.building_id
        LEFT JOIN node_rbac nr ON n.node_id = nr.node_id
        GROUP BY n.node_id;
    `;

    // Fetch all edges with their RBAC roles
    const sqlEdges = `
        SELECT e.edge_id, e.source_node_id, e.destination_node_id,
               e.weight_distance, e.is_bidirectional, e.is_accessible, e.custom_path,
               GROUP_CONCAT(er.role_id) AS allowed_roles
        FROM edges e
        LEFT JOIN edge_rbac er ON e.edge_id = er.edge_id
        GROUP BY e.edge_id;
    `;

    const nodesData = await queryAsync(sqlNodes);
    const edgesData = await queryAsync(sqlEdges);

    // Build an in-memory node map with neighbour adjacency lists
    const nodeMap = {};
    nodesData.forEach(n => {
        nodeMap[n.node_id] = {
            ...n,
            allowed_roles: n.allowed_roles ? n.allowed_roles.split(',').map(Number) : [],
            neighbors: []
        };
    });

    /**
     * Resolves a node reference (numeric ID or room label string) to a node ID.
     * @param {string|number} ref - Node ID or case-insensitive room label.
     * @returns {number|null} Matching node ID, or null if not found.
     */
    const resolveNode = (ref) => {
        const asNum = Number(ref);
        if (!isNaN(asNum) && nodeMap[asNum]) return asNum;
        const match = nodesData.find(
            n => n.room_label && n.room_label.toLowerCase() === String(ref).toLowerCase()
        );
        return match ? match.node_id : null;
    };

    const startId = resolveNode(currentLocation);
    const endId   = resolveNode(destinationNode);

    if (!startId) {
        throw { status: 404, message: `Start location not found: "${currentLocation}"` };
    }
    if (!endId) {
        throw { status: 404, message: `Destination not found: "${destinationNode}"` };
    }
    if (startId === endId) {
        throw { status: 400, message: 'Start and destination are the same location.' };
    }

    // Build adjacency lists from edges, applying RBAC and accessibility filters
    const edgeLookup = {};
    edgesData.forEach(e => {
        if (e.is_accessible === 'DENY') return;
        const edgeRoles = e.allowed_roles ? e.allowed_roles.split(',').map(Number) : [];
        if (edgeRoles.length > 0 && !edgeRoles.includes(userRoleId)) return;

        const src  = e.source_node_id;
        const dest = e.destination_node_id;

        if (nodeMap[src]) {
            nodeMap[src].neighbors.push({ target: dest, weight: parseFloat(e.weight_distance), edgeId: e.edge_id });
            edgeLookup[`${src}-${dest}`] = e;
        }
        if (e.is_bidirectional === 1 && nodeMap[dest]) {
            nodeMap[dest].neighbors.push({ target: src, weight: parseFloat(e.weight_distance), edgeId: e.edge_id });
            edgeLookup[`${dest}-${src}`] = e;
        }
    });

    // ── A* Search ────────────────────────────────────────────────────────────
    const endNode = nodeMap[endId];
    const gScore  = {};
    const fScore  = {};
    const cameFrom = {};

    Object.keys(nodeMap).forEach(id => {
        gScore[id] = Infinity;
        fScore[id] = Infinity;
    });
    gScore[startId] = 0;
    fScore[startId] = heuristic(nodeMap[startId], endNode);

    const openSet    = new Set([String(startId)]);
    const openSetArr = [String(startId)];

    while (openSetArr.length > 0) {
        // Pick node with lowest fScore (linear scan — adequate for campus-scale graphs)
        openSetArr.sort((a, b) => fScore[a] - fScore[b]);
        const currentId = openSetArr.shift();
        openSet.delete(currentId);

        if (Number(currentId) === endId) {
            // ── Reconstruct path ─────────────────────────────────────────────
            const nodePath = [];
            const edgePath = [];
            let curr = String(endId);

            while (cameFrom[curr]) {
                nodePath.unshift(Number(curr));
                const { fromId, edgeId } = cameFrom[curr];
                edgePath.unshift({ edgeId, fromId: Number(fromId), toId: Number(curr) });
                curr = String(fromId);
            }
            nodePath.unshift(Number(startId));

            const pathNodes = nodePath.map(id => {
                const n = nodeMap[id];
                return {
                    node_id:      n.node_id,
                    room_label:   n.room_label,
                    node_type:    n.node_type,
                    coord_x:      n.coord_x,
                    coord_y:      n.coord_y,
                    floorplan_id: n.floorplan_id,
                    floor_level:  n.floor_level,
                    building_id:  n.building_id,
                    building_name: n.building_name
                };
            });

            const edgesTraversed = edgePath.map(ep => {
                const rawEdge = edgeLookup[`${ep.fromId}-${ep.toId}`]
                             || edgeLookup[`${ep.toId}-${ep.fromId}`]
                             || {};
                return {
                    edge_id:         rawEdge.edge_id || null,
                    from_node_id:    ep.fromId,
                    to_node_id:      ep.toId,
                    source_node_id:  rawEdge.source_node_id != null ? Number(rawEdge.source_node_id) : ep.fromId,
                    weight_distance: parseFloat(rawEdge.weight_distance) || 0,
                    is_cross_floor:
                        nodeMap[ep.fromId]?.floorplan_id !== nodeMap[ep.toId]?.floorplan_id,
                    custom_path:     rawEdge.custom_path || null
                };
            });

            // ── Transition & ETA metrics ─────────────────────────────────────
            const totalDistance = parseFloat(gScore[String(endId)].toFixed(2));
            let floorTransitions    = 0;
            let buildingTransitions = 0;
            let elevatorTransitions = 0;
            let stairTransitions    = 0;

            for (let i = 0; i < pathNodes.length - 1; i++) {
                const nodeA = pathNodes[i];
                const nodeB = pathNodes[i + 1];
                const isCrossFloor    = nodeA.floorplan_id !== nodeB.floorplan_id;
                const isCrossBuilding = nodeA.building_id  !== nodeB.building_id;

                if (isCrossFloor && !isCrossBuilding) {
                    if (nodeA.node_type === 'ELEVATOR' || nodeA.node_type === 'STAIRWELL' ||
                        nodeB.node_type === 'ELEVATOR' || nodeB.node_type === 'STAIRWELL') {
                        floorTransitions++;
                        if (nodeA.node_type === 'ELEVATOR' || nodeB.node_type === 'ELEVATOR') {
                            elevatorTransitions++;
                        } else if (nodeA.node_type === 'STAIRWELL' || nodeB.node_type === 'STAIRWELL') {
                            stairTransitions++;
                        }
                    }
                }
                if (isCrossBuilding) {
                    if (nodeA.node_type === 'ENTRANCE' || nodeB.node_type === 'ENTRANCE') {
                        buildingTransitions++;
                    }
                }
            }

            // ETA = walking time + transition delay estimates (30s elevator, 15s stairwell)
            const walkingTimeSec      = totalDistance / walkingSpeed;
            const transitionTimeSec   = (elevatorTransitions * 30) + (stairTransitions * 15);
            const estimatedTimeSec    = Math.round(walkingTimeSec + transitionTimeSec);

            const instructions = generateInstructions(pathNodes, edgesTraversed, edgeLookup);

            // ── Build floorplan-keyed visualisation map ───────────────────────
            const byFloorplan = {};
            pathNodes.forEach(n => {
                const key = String(n.floorplan_id);
                if (!byFloorplan[key]) byFloorplan[key] = { node_ids: [], edge_ids: [] };
                byFloorplan[key].node_ids.push(n.node_id);
            });
            edgesTraversed.forEach(e => {
                if (!e.edge_id) return;
                const fromFp = String(nodeMap[e.from_node_id]?.floorplan_id);
                if (fromFp && byFloorplan[fromFp]) {
                    byFloorplan[fromFp].edge_ids.push(e.edge_id);
                }
            });

            return {
                status: 'success',
                route: {
                    start_node:             nodeMap[startId].room_label || String(startId),
                    destination_node:       nodeMap[endId].room_label   || String(endId),
                    total_distance_m:       totalDistance,
                    estimated_time_seconds: estimatedTimeSec,
                    estimated_time_label:   formatTime(estimatedTimeSec),
                    floor_transitions:      floorTransitions,
                    building_transitions:   buildingTransitions
                },
                route_summary: {
                    start_label:            nodeMap[startId].room_label || String(startId),
                    destination_label:      nodeMap[endId].room_label   || String(endId),
                    total_distance_m:       totalDistance,
                    estimated_time_seconds: estimatedTimeSec,
                    estimated_time_label:   formatTime(estimatedTimeSec),
                    floor_transitions:      floorTransitions,
                    building_transitions:   buildingTransitions,
                    step_count:             instructions.length
                },
                path:            pathNodes,
                edges_traversed: edgesTraversed,
                instructions,
                visualisation:   { by_floorplan: byFloorplan }
            };
        }

        // Expand neighbours — apply RBAC and accessibility constraints
        nodeMap[currentId].neighbors.forEach(neighbor => {
            const neighborNode = nodeMap[neighbor.target];
            if (!neighborNode) return;
            if (neighborNode.is_accessible === 'DENY') return;
            if (neighborNode.allowed_roles.length > 0 &&
                !neighborNode.allowed_roles.includes(userRoleId)) return;

            const tentativeG = gScore[currentId] + neighbor.weight;
            if (tentativeG < gScore[neighbor.target]) {
                cameFrom[String(neighbor.target)] = { fromId: currentId, edgeId: neighbor.edgeId };
                gScore[neighbor.target] = tentativeG;
                fScore[neighbor.target] = tentativeG + heuristic(neighborNode, endNode);

                if (!openSet.has(String(neighbor.target))) {
                    openSet.add(String(neighbor.target));
                    openSetArr.push(String(neighbor.target));
                }
            }
        });
    }

    throw { status: 404, noRoute: true, message: 'No authorised route exists between these locations for the specified role.' };
};

/**
 * Express route handler for the navigation endpoint.
 *
 * Accepts POST body with navigation parameters and an optional notification trigger.
 * Delegates pathfinding to `runNavigation`, then conditionally dispatches
 * RabbitMQ notification events and records the audit trail.
 *
 * Supports both the external API field names (`current_location`, `destination_node`, `rbac_role`)
 * and the legacy admin dashboard field names (`startNodeId`, `endNodeId`, `userRoleId`).
 *
 * @param {import('express').Request}  req
 * @param {import('express').Response} res
 */
exports.calculateRoute = async (req, res) => {
    const currentLocation = req.body.current_location ?? req.body.startNodeId;
    const destinationNode = req.body.destination_node  ?? req.body.endNodeId;
    const rbacRole        = req.body.rbac_role          ?? req.body.userRoleId;

    if (!currentLocation || !destinationNode || !rbacRole) {
        return res.status(400).json({
            message: 'current_location (or startNodeId), destination_node (or endNodeId), and rbac_role (or userRoleId) are required.'
        });
    }

    const walkingSpeed = parseFloat(req.body.walking_speed) || parseFloat(req.query.walking_speed) || 1.2;

    try {
        // 1. Run the core navigation calculation
        const result = await exports.runNavigation({ currentLocation, destinationNode, rbacRole, walkingSpeed });

        // 2. Optionally dispatch a notification if a trigger payload is present or if it's a visitor navigation event
        const hasTrigger = req.body.notification_trigger || req.body.target_host_id || req.body.event_type === 'visitor_navigation';
        if (hasTrigger) {
            console.log('[EngineController] Notification trigger present, running Notification Builder...');

            // Build and validate host/visitor notification payloads
            const {
                hostPayload,
                visitorPayload,
                resolvedHost,
                resolvedVisitor,
                visitorEmailAvailable,
                hostMsgId,
                visitorMsgId
            } = await buildNotifications({ reqBody: req.body, routeResult: result });

            // Ensure visitor recipient satisfies MySQL users table Foreign Key reference
            let visitorRecipientId = resolvedVisitor.user_id;
            if (!visitorRecipientId) {
                const fallbackUsers = await queryAsync('SELECT user_id FROM users LIMIT 1');
                visitorRecipientId = fallbackUsers.length > 0 ? fallbackUsers[0].user_id : 1;
            }

            // Insert initial Audit Trail records (Status = PENDING or FAILED)
            if (hostPayload) {
                const hostTitle = `Campus Visitor Alert: ${resolvedVisitor.full_name}`;
                const hostAlert = req.body.notification_trigger?.alert_message || req.body.alert_message || 'Visitor is en route';
                await queryAsync(
                    'INSERT INTO notifications (recipient_user_id, event_type, title, body, status, message_id) VALUES (?, ?, ?, ?, ?, ?)',
                    [resolvedHost.user_id, req.body.event_type || 'appointment_routing', hostTitle, hostAlert, 'PENDING', hostMsgId]
                );
            }

            const visitorTitle  = `Campus Visitor Journey: ${resolvedVisitor.full_name}`;
            const visitorBody   = `Journey instructions to ${result.route_summary.destination_label}`;
            const visitorStatus = visitorEmailAvailable ? 'PENDING' : 'FAILED';
            const visitorError  = visitorEmailAvailable ? null : 'Visitor email unavailable';
            await queryAsync(
                'INSERT INTO notifications (recipient_user_id, event_type, title, body, status, message_id, delivery_error) VALUES (?, ?, ?, ?, ?, ?, ?)',
                [visitorRecipientId, req.body.event_type || 'appointment_routing', visitorTitle, visitorBody, visitorStatus, visitorMsgId, visitorError]
            );

            // Forward the admin-selected delivery mode into both payloads
            const emailDeliveryMode = req.body.email_delivery_mode || process.env.EMAIL_MODE || 'ethereal';
            if (hostPayload) {
                hostPayload.email_delivery_mode    = emailDeliveryMode;
            }
            if (visitorPayload) {
                visitorPayload.email_delivery_mode = emailDeliveryMode;
            }

            // Publish payloads to RabbitMQ and await broker acknowledgements
            try {
                const publishPromises = [];
                if (hostPayload) {
                    publishPromises.push(publishNotification(hostPayload));
                }
                if (visitorEmailAvailable) {
                    publishPromises.push(publishNotification(visitorPayload));
                }
                await Promise.all(publishPromises);
            } catch (mqErr) {
                console.error('[EngineController] RabbitMQ publish failed, executing audit trail compensation:', mqErr.message);

                // Compensate database logs to avoid orphaned PENDING records (Option B)
                if (hostPayload) {
                    await queryAsync(
                        'UPDATE notifications SET status = "FAILED", delivery_error = "RabbitMQ publish failed" WHERE message_id = ?',
                        [hostMsgId]
                    );
                }
                if (visitorEmailAvailable) {
                    await queryAsync(
                        'UPDATE notifications SET status = "FAILED", delivery_error = "RabbitMQ publish failed" WHERE message_id = ?',
                        [visitorMsgId]
                    );
                }
                throw new Error('Failed to publish notification events to RabbitMQ.');
            }

            // Append notification details to the response (backward compatible)
            result.notification = {
                message_id:     hostMsgId || null,
                status:         'QUEUED',
                published_at:   new Date().toISOString(),
                target_host_id: resolvedHost ? resolvedHost.user_id : null,
                host: hostPayload ? {
                    message_id: hostMsgId,
                    status:     'QUEUED'
                } : null,
                visitor: {
                    message_id:     visitorMsgId,
                    status:         visitorEmailAvailable ? 'QUEUED' : 'FAILED',
                    delivery_error: visitorError
                }
            };
        }

        return res.json(result);
    } catch (err) {
        if (err.noRoute) {
            return res.status(404).json({
                status:        'no_route',
                message:       err.message,
                route_summary: null,
                instructions:  []
            });
        }
        return res.status(err.statusCode || err.status || 500).json({ error: err.message || 'Navigation calculation error.' });
    }
};