/**
 * @file edgeUtils.js
 * @description Edge serialization utilities for the Campus Navigation System frontend.
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
        custom_path: (edge.isCustom && edge.pathPoints && edge.pathPoints.length >= 2)
            ? JSON.stringify(edge.pathPoints)
            : null
    }));
}

export function deserializeEdgesFromApi(apiEdges, nodeIdToIndex) {
    return apiEdges.map(e => {
        let pathPoints = null;
        let isCustom   = false;

        if (e.custom_path) {
            try {
                const parsed = JSON.parse(e.custom_path);
                if (Array.isArray(parsed) && parsed.length >= 2) {
                    pathPoints = parsed;
                    isCustom   = true;
                }
            } catch (_) {
                pathPoints = null;
                isCustom   = false;
            }
        }

        return {
            edge_id:          e.edge_id,
            start:            nodeIdToIndex[e.source_node_id]      ?? null,
            end:              nodeIdToIndex[e.destination_node_id] ?? null,
            weight:           parseFloat(e.weight_distance) || 0,
            is_bidirectional: e.is_bidirectional === 1 || e.is_bidirectional === true,
            is_accessible:    e.is_accessible,
            allowed_roles:    e.allowed_roles || [],
            is_cross_floor:   e.is_cross_floor === 1 || e.is_cross_floor === true,
            target_node_id:   e.destination_node_id || null,
            isCustom,
            pathPoints,
            customPathPoints: pathPoints
        };
    });
}
