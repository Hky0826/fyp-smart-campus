/**
 * @file nodeUtils.js
 * @description Node utility functions for the Campus Navigation System frontend.
 *
 * Contains helper functions for classifying and working with map node objects.
 * These utilities are used across multiple components and hooks without coupling
 * them to any specific React component or state management layer.
 */

/**
 * Determines whether a node is a corridor (non-landmark) node.
 *
 * Corridor nodes are:
 *  - Excluded from navigation panel dropdowns (they don't appear as selectable start/end points).
 *  - Shown with a different visual style in the canvas (greyed-out, smaller).
 *  - Omitted from instruction landmark labels in the navigation tester.
 *
 * A node is considered a corridor if its `node_type` is `'CORRIDOR'`, or if its
 * `room_label` begins with "corridor" (case-insensitive), accounting for spaces and hyphens.
 *
 * @param {Object} node - A node object from the local state or API response.
 * @param {string} [node.node_type] - The node's classification (e.g. 'CORRIDOR', 'CLASSROOM').
 * @param {string} [node.room_label] - The human-readable label for the node.
 * @returns {boolean} True if the node should be treated as a corridor (non-landmark).
 *
 * @example
 * isCorridorNode({ node_type: 'CORRIDOR' });                   // true
 * isCorridorNode({ room_label: 'Corridor A' });                // true
 * isCorridorNode({ node_type: 'CLASSROOM', room_label: 'LT1' }); // false
 */
export function isCorridorNode(node) {
    if (!node) return true;
    if (node.node_type === 'CORRIDOR') return true;
    if (node.room_label) {
        const label = node.room_label.trim().toLowerCase();
        if (
            label === 'corridor' ||
            label.startsWith('corridor ') ||
            label.startsWith('corridor-')
        ) {
            return true;
        }
    }
    return false;
}
