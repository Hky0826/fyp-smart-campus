/**
 * @file nodeUtils.js
 * @description Node utility functions for the Campus Navigation System frontend.
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
