/**
 * @file visualisationModelService.js
 * @description Role-filtered Map Context Model Service for the Campus Navigation System.
 *
 * Implements strict RBAC filtering and route-relevance pruning for the Kiosk and
 * Mobile visual map representations.
 */

'use strict';

const queryAsync = require('../utils/queryAsync');

const ROLE_MAP = {
    admin: 1,
    staff: 2,
    student: 3,
    visitor: 4
};

const TRANSITION_TYPES = ['ELEVATOR', 'STAIRWELL', 'ENTRANCE'];
const PUBLIC_LANDMARK_TYPES = ['FOOD', 'WASHROOM', 'FACILITIES'];

/**
 * Utility keywords for facility/back-of-house rooms that should not appear
 * in user visualisations (e.g. storerooms, server rooms, pantries, electrical/plant rooms).
 */
const UNINTENDED_FACILITY_KEYWORDS = [
    'storeroom', 'storage', 'store',
    'server',
    'pantry',
    'electrical', 'switchboard', 'substation',
    'mechanical', 'utility',
    'janitor', 'cleaner', 'housekeeping', 'maintenance',
    'plant room', 'ahu', 'pump room',
    'equipment room', 'boiler'
];

/**
 * Checks if a node is an unintended facility/back-of-house room.
 *
 * @param {Object} node
 * @returns {boolean} true if node is an unintended facility room and should be excluded.
 */
function isUnintendedFacilityNode(node) {
    if (node.node_type === 'FACILITIES') {
        const label = (node.room_label || '').trim().toLowerCase();
        // If facility node has no label or a generic name, exclude it
        if (!label || label === 'facility' || label === 'facilities') {
            return true;
        }
        // Exclude back-of-house utility rooms matching any utility keyword
        return UNINTENDED_FACILITY_KEYWORDS.some(kw => label.includes(kw));
    }
    return false;
}

/**
 * Resolves a role string or number into a valid numeric role ID.
 * Defaults to 4 (visitor) if unknown.
 *
 * @param {string|number} role
 * @returns {number}
 */
function resolveRoleId(role) {
    if (typeof role === 'number') return role;
    if (!role) return 4;
    const lower = String(role).trim().toLowerCase();
    return ROLE_MAP[lower] ?? (parseInt(lower, 10) || 4);
}

/**
 * Validates whether an entity (node or edge) with allowed_roles and is_accessible
 * is permitted for the given role ID.
 *
 * @param {Object} entity
 * @param {string|null} entity.is_accessible - 'DENY' or other status
 * @param {string|null} entity.allowed_roles - Comma-separated list of role IDs, or null
 * @param {number} userRoleId
 * @returns {boolean}
 */
function isRolePermitted(entity, userRoleId) {
    if (entity.is_accessible === 'DENY') {
        return false;
    }
    if (!entity.allowed_roles || entity.allowed_roles.trim() === '') {
        // No restriction entry -> accessible to all roles
        return true;
    }
    const allowed = entity.allowed_roles.split(',').map(r => parseInt(r.trim(), 10));
    return allowed.includes(userRoleId);
}

/**
 * Builds the filtered map context for a given route and role.
 *
 * @param {Object} params
 * @param {Object} params.routeResult - Full navigation result from runNavigation()
 * @param {string|number} params.rbacRole - User role name or numeric ID
 * @returns {Promise<Object>} Map context keyed by floorplan ID:
 *   { [fpId]: { floorplan_id, building_name, floor_level, scale_ratio, wall_grid, nodes, edges } }
 */
async function buildVisualisationModel({ routeResult, rbacRole }) {
    if (!routeResult || !routeResult.visualisation || !routeResult.visualisation.by_floorplan) {
        return {};
    }

    const userRoleId = resolveRoleId(rbacRole);
    const byFloorplan = routeResult.visualisation.by_floorplan;
    const floorplanIds = Object.keys(byFloorplan).map(Number);

    if (floorplanIds.length === 0) {
        return {};
    }

    const mapContext = {};

    for (const fpId of floorplanIds) {
        // 1. Fetch floorplan metadata and wall grid cache
        const [fpMeta] = await queryAsync(
            `SELECT f.floorplan_id, f.floor_level, f.scale_ratio, f.image_path,
                    b.building_name
             FROM floorplans f
             JOIN buildings b ON f.building_id = b.building_id
             WHERE f.floorplan_id = ?`,
            [fpId]
        );

        if (!fpMeta) continue;

        // 2. Fetch all nodes for this floorplan with RBAC role associations
        const rawNodes = await queryAsync(
            `SELECT n.node_id, n.coord_x, n.coord_y, n.room_label, n.node_type, n.is_accessible,
                    GROUP_CONCAT(nr.role_id) AS allowed_roles
             FROM nodes n
             LEFT JOIN node_rbac nr ON n.node_id = nr.node_id
             WHERE n.floorplan_id = ?
             GROUP BY n.node_id`,
            [fpId]
        );

        // 3. Determine route nodes and route edges for this floor
        const routeNodeIdSet = new Set((byFloorplan[String(fpId)]?.node_ids || []).map(Number));
        const routeEdgeIdSet = new Set((byFloorplan[String(fpId)]?.edge_ids || []).map(Number));

        // 4. Filter nodes:
        // Rule 1: MUST be RBAC-permitted (strict check; route nodes are NOT exempt).
        // Rule 2: Exclude unintended facility nodes (back-of-house utility/storage rooms).
        // All role-permitted nodes on this floorplan are included to provide spatial context.
        const permittedNodes = [];
        const permittedNodeIdSet = new Set();

        for (const node of rawNodes) {
            if (!isRolePermitted(node, userRoleId)) {
                // Denied by RBAC
                continue;
            }

            if (isUnintendedFacilityNode(node)) {
                // Unintended facility room (storeroom, server room, pantry, etc.)
                continue;
            }

            permittedNodes.push({
                node_id: node.node_id,
                coord_x: node.coord_x,
                coord_y: node.coord_y,
                room_label: node.room_label,
                node_type: node.node_type,
                is_accessible: node.is_accessible
            });
            permittedNodeIdSet.add(node.node_id);
        }

        // 5. Fetch edges with RBAC role associations for this floorplan
        // Only consider edges actually traversed in the route for this floorplan
        let permittedEdges = [];
        if (routeEdgeIdSet.size > 0) {
            const edgeIdsArray = Array.from(routeEdgeIdSet);
            const rawEdges = await queryAsync(
                `SELECT e.edge_id, e.source_node_id, e.destination_node_id,
                        e.weight_distance, e.is_bidirectional, e.is_accessible, e.custom_path,
                        GROUP_CONCAT(er.role_id) AS allowed_roles
                 FROM edges e
                 LEFT JOIN edge_rbac er ON e.edge_id = er.edge_id
                 WHERE e.edge_id IN (?)
                 GROUP BY e.edge_id`,
                [edgeIdsArray]
            );

            for (const edge of rawEdges) {
                // Must be RBAC-permitted
                if (!isRolePermitted(edge, userRoleId)) {
                    continue;
                }
                // Both source and destination must exist in permittedNodes
                if (!permittedNodeIdSet.has(edge.source_node_id) || !permittedNodeIdSet.has(edge.destination_node_id)) {
                    continue;
                }

                permittedEdges.push({
                    edge_id: edge.edge_id,
                    source_node_id: edge.source_node_id,
                    destination_node_id: edge.destination_node_id,
                    weight_distance: edge.weight_distance,
                    is_bidirectional: edge.is_bidirectional,
                    custom_path: edge.custom_path
                });
            }
        }

        // 6. Parse wall grid cache
        let wallGrid = null;
        if (fpMeta.wall_grid_cache) {
            try {
                wallGrid = typeof fpMeta.wall_grid_cache === 'string'
                    ? JSON.parse(fpMeta.wall_grid_cache)
                    : fpMeta.wall_grid_cache;
            } catch (_) {
                wallGrid = null;
            }
        }

        mapContext[fpId] = {
            floorplan_id: fpMeta.floorplan_id,
            building_name: fpMeta.building_name,
            floor_level: fpMeta.floor_level,
            scale_ratio: fpMeta.scale_ratio,
            wall_grid: wallGrid,
            nodes: permittedNodes,
            edges: permittedEdges
        };
    }

    return mapContext;
}

module.exports = {
    buildVisualisationModel,
    resolveRoleId,
    isRolePermitted,
    isUnintendedFacilityNode,
    UNINTENDED_FACILITY_KEYWORDS,
    TRANSITION_TYPES,
    PUBLIC_LANDMARK_TYPES
};
