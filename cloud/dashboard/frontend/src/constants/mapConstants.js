/**
 * @file mapConstants.js
 * @description Shared constants for the Campus Navigation System Map Editor.
 *
 * Centralizes all fixed values used across the canvas, toolbar, property panels,
 * and sidebar components. Importing from here ensures that any value change
 * propagates to all consumers automatically.
 *
 * IMPORTANT: The `TRANSITION_TYPES` array must remain synchronized with the backend
 * Set of the same name defined in `backend/controllers/engineController.js`.
 * If new transition node types are added, both files must be updated together.
 */

// ─────────────────────────────────────────────────────────────────────────────
// NODE TYPES
// ─────────────────────────────────────────────────────────────────────────────

/**
 * All supported node type values in the map editor.
 * Used to populate the "Node Type" dropdown in the Properties Panel.
 * @type {string[]}
 */
export const NODE_TYPES = [
    'CLASSROOM',
    'CORRIDOR',
    'ENTRANCE',
    'STAIRWELL',
    'ELEVATOR',
    'FOOD',
    'OFFICE',
    'FACILITIES',
    'HALL',
    'WASHROOM',
    'OUTDOOR',
    'SOCIAL SPACES',
    'OTHER'
];

/**
 * Node types that represent cross-floor or cross-building transition points.
 * These nodes receive special visual treatment on the canvas (purple fill, white stroke).
 *
 * Must match the `TRANSITION_TYPES` Set in `backend/controllers/engineController.js`.
 * @type {string[]}
 */
export const TRANSITION_TYPES = ['ELEVATOR', 'STAIRWELL', 'ENTRANCE'];

// ─────────────────────────────────────────────────────────────────────────────
// CANVAS DIMENSIONS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The logical width of the Konva canvas in pixels.
 * This is the virtual coordinate space width, independent of the display resolution.
 * @type {number}
 */
export const CANVAS_WIDTH = 800;

/**
 * The logical height of the Konva canvas in pixels.
 * @type {number}
 */
export const CANVAS_HEIGHT = 600;

// ─────────────────────────────────────────────────────────────────────────────
// WALL DETECTION GRID
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The number of pixels each wall detection grid cell represents.
 * A lower value = more precise wall detection, but slower A* computation.
 * @type {number}
 */
export const GRID_SCALE = 8;

// ─────────────────────────────────────────────────────────────────────────────
// EDITOR MODES
// ─────────────────────────────────────────────────────────────────────────────

/**
 * All valid editor mode strings for the map editor toolbar.
 * @readonly
 * @enum {string}
 */
export const EDITOR_MODES = {
    ADD_NODES:      'add_nodes',
    DRAW_PATHS:     'draw_paths',
    EDIT_PROPS:     'edit_props',
    DELETE_ELEMENT: 'delete_element',
};
