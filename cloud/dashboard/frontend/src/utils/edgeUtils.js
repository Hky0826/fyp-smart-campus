/**
 * @file edgeUtils.js
 * @description Edge serialization utilities for the Campus Navigation System frontend.
 *
 * Handles the transformation of edge objects between the in-memory canvas state
 * format (used by the Konva editor) and the API-compatible persistence format
 * (used by the backend save/load endpoints).
 *
 * Keeping these transformations in one file ensures that the serialization
 * contract between the editor and the API is maintained in a single place.
 */

/**
 * Serializes an array of in-memory edge objects into the format expected by the
 * backend `/api/map-data` (POST) save endpoint.
 *
 * Specifically, it converts the `pathPoints` array into a JSON string stored in
 * the `custom_path` field. Straight-line edges (non-custom) will have `custom_path: null`.
 *
 * @param {Object[]} edges - The array of edge objects from the local canvas state.
 * @param {boolean}  [edge.isCustom]     - Whether the path was manually drawn or AI-routed with waypoints.
 * @param {Object[]} [edge.pathPoints]   - Array of {x, y} control point objects.
 * @param {number}   [edge.edge_id]      - Existing DB edge ID (null for newly created edges).
 * @param {number}   edge.start          - Index of the source node in the local `nodes` array.
 * @param {number}   edge.end            - Index of the destination node in the local `nodes` array.
 * @param {number}   edge.weight         - Real-world distance in metres.
 * @param {boolean}  edge.is_bidirectional - Whether the edge can be traversed in both directions.
 * @param {string}   edge.is_accessible  - RBAC accessibility ('ALLOW' | 'DENY').
 * @param {number[]} [edge.allowed_roles] - Array of role IDs permitted to use this edge.
 * @param {boolean}  [edge.is_cross_floor] - Whether this is a cross-floor transition edge.
 * @param {number}   [edge.target_node_id] - Target node ID (for cross-floor edges only).
 * @returns {Object[]} Edge objects formatted for the save API payload.
 *
 * @example
 * const payload = serializeEdgesForSave(edges);
 * await authAxios.post('/api/map-data', { floorplan_id, nodes: nodePayload, edges: payload });
 */
export function serializeEdgesForSave(edges) {
    return edges.map(edge => ({
        edge_id:         edge.edge_id || null,
        start:           edge.start,
        end:             edge.end,
        weight:          edge.weight,
        is_bidirectional: edge.is_bidirectional,
        is_accessible:   edge.is_accessible,
        allowed_roles:   edge.allowed_roles || [],
        is_cross_floor:  edge.is_cross_floor || false,
        target_node_id:  edge.target_node_id || null,
        // Serialize custom path waypoints as a JSON string, or null for straight-line edges
        custom_path: (edge.isCustom && edge.pathPoints && edge.pathPoints.length >= 2)
            ? JSON.stringify(edge.pathPoints)
            : null
    }));
}

/**
 * Deserializes edge data from the backend API response into the local canvas state format.
 *
 * Maps DB-level `source_node_id` / `destination_node_id` back to local array indices
 * using the provided `nodeIdToIndex` lookup map. Parses the `custom_path` JSON string
 * back into a `pathPoints` array for Konva rendering.
 *
 * @param {Object[]} apiEdges       - Raw edge objects from the `GET /api/map-data/:id` response.
 * @param {Object}   nodeIdToIndex  - A map of `{ [node_id]: arrayIndex }` for the current floorplan.
 * @returns {Object[]} Edge objects in the in-memory canvas state format.
 *
 * @example
 * const idToIndex = {};
 * nodes.forEach((n, i) => { idToIndex[n.node_id] = i; });
 * const canvasEdges = deserializeEdgesFromApi(apiEdges, idToIndex);
 */
export function deserializeEdgesFromApi(apiEdges, nodeIdToIndex) {
    return apiEdges.map(e => {
        let pathPoints = null;
        let isCustom   = false;

        // Parse the stored JSON path waypoints if present
        if (e.custom_path) {
            try {
                const parsed = JSON.parse(e.custom_path);
                if (Array.isArray(parsed) && parsed.length >= 2) {
                    pathPoints = parsed;
                    isCustom   = true;
                }
            } catch (_) {
                // Malformed custom_path — fall back to straight line
                pathPoints = null;
                isCustom   = false;
            }
        }

        return {
            edge_id:          e.edge_id,
            start:            nodeIdToIndex[e.source_node_id]      ?? null,
            end:              nodeIdToIndex[e.destination_node_id] ?? null,
            weight:           parseFloat(e.weight_distance) || 0,
            is_bidirectional: e.is_bidirectional === 1,
            is_accessible:    e.is_accessible,
            allowed_roles:    e.allowed_roles || [],
            is_cross_floor:   e.is_cross_floor === 1,
            target_node_id:   e.destination_node_id || null,
            isCustom,
            pathPoints,
            // Preserve custom waypoints separately to support "Reset to AI" action
            customPathPoints: pathPoints
        };
    });
}
