/**
 * @file useMapEditor.js
 * @description Map editor state and interaction hook for the Campus Navigation System.
 *
 * Manages all canvas-level interaction state and event handlers including:
 *  - Node and edge arrays (graph data)
 *  - Editor tool mode (add_nodes, draw_paths, edit_props, delete_element)
 *  - Selected and hovered element tracking
 *  - Node drag (real-time and drag-end with A* recalculation trigger)
 *  - Edge creation, path control point editing (add/delete via double-click)
 *  - Properties panel state (updateProperty, handleRoleToggle)
 *  - Cross-floor transition linker state and CRUD handlers
 *  - Canvas pan/zoom (wheel, mousedown, drag) and auto-fit on image load
 *  - Konva stage reference and dimension tracking
 */

import { useState, useEffect, useRef } from 'react';
import { findAStarPath, simplifyPath, getPathLength } from '../utils/pathfinding';
import { TRANSITION_TYPES, CANVAS_WIDTH, CANVAS_HEIGHT } from '../constants/mapConstants';

/**
 * Manages all map editor state and Konva canvas interaction handlers.
 *
 * @param {Object} deps
 * @param {Array}   deps.rolesList    - Available campus roles for RBAC assignment.
 * @param {Array}   deps.globalNodes  - All nodes across all floorplans (for transition linker).
 * @param {Function} deps.getWallGrid - Getter function for the 2D wall mask grid from useFloorplanData.
 * @param {string}  deps.editScaleRatio - Pixel-to-metres scale ratio for the current floorplan.
 * @param {Object|null} deps.imageObj - The loaded floorplan image object.
 * @returns {Object} Full editor state and all event handler functions.
 */
export function useMapEditor({ rolesList, globalNodes, getWallGrid, editScaleRatio, imageObj }) {
    // ── Graph State ───────────────────────────────────────────────────────────
    const [nodes, setNodes]             = useState([]);
    const [edges, setEdges]             = useState([]);
    const [appMode, setAppMode]         = useState('edit'); // 'edit' or 'test'
    const [mode, setMode]               = useState('');
    const [selectedElement, setSelectedElement] = useState({ type: null, index: null });
    const [hoveredNodeIndex, setHoveredNodeIndex] = useState(null);
    const [hoveredEdgeIndex, setHoveredEdgeIndex] = useState(null);
    const [hoveredHandleNode, setHoveredHandleNode] = useState(null);
    const [edgeDrawState, setEdgeDrawState] = useState(null);

    const selectTool = (tool, floorplanId) => {
        if (!floorplanId) return;
        setMode(prev => prev === tool ? '' : tool);
    };

    // ── AI Analysis State ─────────────────────────────────────────────────────
    // Holds the last FloorplanAnalysisResult returned from POST /api/analyze-floorplan.
    // Null when no analysis has been run or after the result has been cleared.
    const [aiAnalysisResult, setAiAnalysisResult] = useState(null);

    // ── Properties Panel Tab State ────────────────────────────────────────────
    const [activeNodeTab, setActiveNodeTab] = useState('general');

    // ── Transition Linker State ───────────────────────────────────────────────
    const [transitionTargetId, setTransitionTargetId]         = useState('');
    const [transitionWeight, setTransitionWeight]             = useState('10');
    const [transitionIsAccessible, setTransitionIsAccessible] = useState(true);
    const [transitionIsBidirectional, setTransitionIsBidirectional] = useState(true);

    // ── Canvas Pan / Zoom State ───────────────────────────────────────────────
    const [dimensions, setDimensions] = useState({ width: CANVAS_WIDTH, height: CANVAS_HEIGHT });
    const [stageScale, setStageScale] = useState(1.0);
    const [stageX, setStageX]         = useState(0);
    const [stageY, setStageY]         = useState(0);

    // ── Refs ──────────────────────────────────────────────────────────────────
    const containerRef            = useRef(null);
    const stageRef                = useRef(null);
    const isDraggingStage         = useRef(false);
    const isDraggingControlPoint  = useRef(false);
    const drawPathStartNode       = useRef(null); // Tracks first node for Draw Edges tool
    const mouseDownPos            = useRef(null);
    const fileInputRef            = useRef(null);

    // ── Mode Switch Effect ────────────────────────────────────────────────────
    useEffect(() => {
        if (appMode === 'test') {
            setSelectedElement({ type: null, index: null });
            setHoveredHandleNode(null);
            setEdgeDrawState(null);
            setHoveredNodeIndex(null);
            setHoveredEdgeIndex(null);
            drawPathStartNode.current = null;
        }
    }, [appMode]);

    // ── Clear draw path start node when mode changes ─────────────────────────
    useEffect(() => {
        if (mode !== 'draw_paths') {
            drawPathStartNode.current = null;
        }
    }, [mode]);

    // ── Reset transition fields when selected node changes ────────────────────
    useEffect(() => {
        if (selectedElement.type === 'node') {
            const node = nodes[selectedElement.index];
            if (node) {
                if (!TRANSITION_TYPES.includes(node.node_type)) {
                    setActiveNodeTab('general');
                }
                const existingTransition = edges.find(
                    e => e.start === selectedElement.index && e.is_cross_floor
                );
                if (existingTransition) {
                    setTransitionTargetId(String(existingTransition.target_node_id));
                    setTransitionWeight(String(existingTransition.weight));
                    setTransitionIsAccessible(existingTransition.is_accessible === 'ALLOW');
                    setTransitionIsBidirectional(existingTransition.is_bidirectional);
                } else {
                    setTransitionTargetId('');
                    setTransitionWeight('10');
                    setTransitionIsAccessible(true);
                    setTransitionIsBidirectional(true);
                }
            }
        } else {
            setActiveNodeTab('general');
        }
    }, [selectedElement, nodes, edges, rolesList]);

    // ── Respond to container resize ───────────────────────────────────────────
    useEffect(() => {
        if (!containerRef.current) return;
        const resizeObserver = new ResizeObserver(entries => {
            for (const entry of entries) {
                setDimensions({
                    width:  entry.contentRect.width  || CANVAS_WIDTH,
                    height: entry.contentRect.height || CANVAS_HEIGHT
                });
            }
        });
        resizeObserver.observe(containerRef.current);
        return () => resizeObserver.disconnect();
    }, []);

    // ── Auto-fit image on load or container resize ────────────────────────────
    useEffect(() => {
        if (imageObj) {
            const scaleX   = dimensions.width  / CANVAS_WIDTH;
            const scaleY   = dimensions.height / CANVAS_HEIGHT;
            const fitScale = Math.min(scaleX, scaleY) * 0.95;
            setStageScale(fitScale);
            setStageX((dimensions.width  - CANVAS_WIDTH  * fitScale) / 2);
            setStageY((dimensions.height - CANVAS_HEIGHT * fitScale) / 2);
        }
    }, [imageObj, dimensions.width, dimensions.height]);

    // ── Derived computed values ───────────────────────────────────────────────

    /** The currently selected node or edge object, or null if nothing is selected. */
    const activeObj = selectedElement.index !== null
        ? (selectedElement.type === 'node'
            ? nodes[selectedElement.index]
            : edges[selectedElement.index])
        : null;

    /** Whether the selected node is a transition type (elevator / stairwell / entrance). */
    const isTransitionNode =
        selectedElement.type === 'node' &&
        activeObj &&
        TRANSITION_TYPES.includes(activeObj.node_type);

    // ── Canvas Geometry Helpers ───────────────────────────────────────────────

    /**
     * Clamps a drag position to remain within the 800×600 virtual canvas boundaries.
     * Must be passed to `dragBoundFunc` on Konva nodes.
     *
     * @param {{ x: number, y: number }} pos - The proposed screen-space drag position.
     * @returns {{ x: number, y: number }} The clamped screen-space position.
     */
    const getClampedDragBounds = (pos) => {
        const stage = stageRef.current;
        if (!stage) return pos;
        const transform  = stage.getAbsoluteTransform().copy().invert();
        const localPos   = transform.point(pos);
        const clampedLocal = {
            x: Math.max(0, Math.min(localPos.x, CANVAS_WIDTH)),
            y: Math.max(0, Math.min(localPos.y, CANVAS_HEIGHT))
        };
        return stage.getAbsoluteTransform().point(clampedLocal);
    };

    /**
     * Resets the stage pan/zoom to center-fit the floorplan in the container.
     */
    const handleResetView = () => {
        if (!imageObj) return;
        const scaleX   = dimensions.width  / CANVAS_WIDTH;
        const scaleY   = dimensions.height / CANVAS_HEIGHT;
        const fitScale = Math.min(scaleX, scaleY) * 0.95;
        setStageScale(fitScale);
        setStageX((dimensions.width  - CANVAS_WIDTH  * fitScale) / 2);
        setStageY((dimensions.height - CANVAS_HEIGHT * fitScale) / 2);
    };

    // ── Wheel Zoom Handler ────────────────────────────────────────────────────

    /**
     * Handles mouse wheel zoom on the Konva Stage.
     * Zooms toward the cursor position, clamped between the fit-to-screen scale and 10×.
     *
     * @param {Konva.KonvaEventObject<WheelEvent>} e
     */
    const handleWheel = (e) => {
        e.evt.preventDefault();
        const stage    = e.currentTarget.getStage();
        const oldScale = stage.scaleX();
        const pointer  = stage.getPointerPosition();
        if (!pointer) return;

        const scaleX   = dimensions.width  / CANVAS_WIDTH;
        const scaleY   = dimensions.height / CANVAS_HEIGHT;
        const fitScale = Math.min(scaleX, scaleY) * 0.95;

        const scaleBy      = 1.15;
        const newScale     = e.evt.deltaY < 0 ? oldScale * scaleBy : oldScale / scaleBy;
        const clampedScale = Math.max(fitScale, Math.min(newScale, 10));

        const mousePointTo = {
            x: (pointer.x - stage.x()) / oldScale,
            y: (pointer.y - stage.y()) / oldScale
        };

        setStageScale(clampedScale);
        setStageX(pointer.x - mousePointTo.x * clampedScale);
        setStageY(pointer.y - mousePointTo.y * clampedScale);
    };

    /** Records the pointer position at the start of a mousedown for click-vs-drag detection. */
    const handleStageMouseDown = (e) => {
        const stage = e.currentTarget.getStage();
        mouseDownPos.current = stage.getPointerPosition();
    };

    // ── Node & Edge Click / Interaction Handlers ──────────────────────────────

    const handleDeleteSelected = () => {
        if (selectedElement.type === 'node') {
            const index = selectedElement.index;
            if (!window.confirm('Delete this node and its connected paths?')) return;
            setNodes(prev => prev.filter((_, i) => i !== index));
            setEdges(prev => prev
                .filter(edge => edge.start !== index && edge.end !== index)
                .map(edge => ({
                    ...edge,
                    start: edge.start > index ? edge.start - 1 : edge.start,
                    end:   edge.end   > index ? edge.end   - 1 : edge.end
                }))
            );
            setSelectedElement({ type: null, index: null });
            setHoveredNodeIndex(null);
            setHoveredHandleNode(null);
        } else if (selectedElement.type === 'edge') {
            const index = selectedElement.index;
            if (!window.confirm('Delete this path?')) return;
            setEdges(prev => prev.filter((_, i) => i !== index));
            setSelectedElement({ type: null, index: null });
            setHoveredEdgeIndex(null);
        }
    };

    useEffect(() => {
        const onKeyDown = (e) => {
            if (appMode !== 'edit') return;
            if (e.key === 'Delete' || e.key === 'Backspace') {
                if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
                if (selectedElement.type !== null) {
                    handleDeleteSelected();
                }
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [appMode, selectedElement, nodes, edges]);

    const handleMapClick = (e) => {
        if (e.target !== e.target.getStage() && e.target.className !== 'Image') return;
        
        if (appMode === 'edit' && mode === 'add_nodes') {
            const stage = e.target.getStage();
            const pos = stage.getPointerPosition();
            const transform = stage.getAbsoluteTransform().copy().invert();
            const relativePos = transform.point(pos);
            const clampedX = Math.max(0, Math.min(relativePos.x, CANVAS_WIDTH));
            const clampedY = Math.max(0, Math.min(relativePos.y, CANVAS_HEIGHT));

            const allRoleIds = rolesList.map(r => r.role_id);
            const newNode = {
                node_id: null,
                x: clampedX,
                y: clampedY,
                room_label: `Node ${nodes.length + 1}`,
                node_type: 'CORRIDOR',
                is_accessible: 'ALLOW',
                allowed_roles: allRoleIds
            };
            
            setNodes(prev => {
                const newNodes = [...prev, newNode];
                setSelectedElement({ type: 'node', index: newNodes.length - 1 });
                return newNodes;
            });
            return;
        }

        if (appMode === 'edit') {
            setSelectedElement({ type: null, index: null });
        }
    };

    const handleMapDblClick = (e) => {
        if (e.target !== e.target.getStage() && e.target.className !== 'Image') return;
        if (appMode !== 'edit' || !imageObj) return;

        const stage = e.target.getStage();
        const pos   = stage.getPointerPosition();
        const transform   = stage.getAbsoluteTransform().copy().invert();
        const relativePos = transform.point(pos);
        const clampedX    = Math.max(0, Math.min(relativePos.x, CANVAS_WIDTH));
        const clampedY    = Math.max(0, Math.min(relativePos.y, CANVAS_HEIGHT));

        const allRoleIds = rolesList.map(r => r.role_id);
        const newNode = {
            node_id:       null,
            x:             clampedX,
            y:             clampedY,
            room_label:    `Node ${nodes.length + 1}`,
            node_type:     'CORRIDOR',
            is_accessible: 'ALLOW',
            allowed_roles: allRoleIds
        };
        
        setNodes(prev => {
            const newNodes = [...prev, newNode];
            setSelectedElement({ type: 'node', index: newNodes.length - 1 });
            return newNodes;
        });
    };

    /**
     * Creates an edge between two nodes using A* pathfinding.
     * Shared by both the Draw Edges tool and the connection-handle drag.
     */
    const createEdgeBetweenNodes = (startIndex, endIndex) => {
        const startNode = nodes[startIndex];
        const endNode   = nodes[endIndex];
        if (!startNode || !endNode) return;

        const startRoles   = startNode.allowed_roles || [];
        const endRoles     = endNode.allowed_roles || [];
        const intersection = startRoles.filter(r => endRoles.includes(r));
        let isAccessible   = 'ALLOW';

        if (intersection.length === 0) {
            const confirmSave = window.confirm(
                'The selected nodes do not share any access roles. This edge will not be traversable by any user.\n\n' +
                'Click OK to save the edge as a disabled/inactive path, or Cancel to abort.'
            );
            if (!confirmSave) return;
            isAccessible = 'DENY';
        }

        let pathPoints = null;
        const currentWallGrid = getWallGrid ? getWallGrid() : [];
        if (currentWallGrid && currentWallGrid.length > 0) {
            const astar = findAStarPath(startNode, endNode, currentWallGrid, 8);
            if (astar) pathPoints = simplifyPath(astar);
        }
        if (!pathPoints) {
            pathPoints = [{ x: startNode.x, y: startNode.y }, { x: endNode.x, y: endNode.y }];
        }

        const scale = parseFloat(editScaleRatio) || 1.0;
        const newEdge = {
            edge_id:         null,
            start:           startIndex,
            end:             endIndex,
            weight:          getPathLength(pathPoints, scale),
            is_bidirectional: true,
            is_accessible:   isAccessible,
            allowed_roles:   intersection,
            isCustom:        false,
            customPathPoints: null,
            pathPoints
        };

        setEdges(prev => {
            const newEdges = [...prev, newEdge];
            setSelectedElement({ type: 'edge', index: newEdges.length - 1 });
            return newEdges;
        });
    };

    const handleNodeClick = (index, e) => {
        e.cancelBubble = true;

        // Delete Element mode
        if (appMode === 'edit' && mode === 'delete_element') {
            if (!window.confirm('Delete this node and its connected paths?')) return;
            setNodes(prev => prev.filter((_, i) => i !== index));
            setEdges(prev => prev
                .filter(edge => edge.start !== index && edge.end !== index)
                .map(edge => ({
                    ...edge,
                    start: edge.start > index ? edge.start - 1 : edge.start,
                    end:   edge.end   > index ? edge.end   - 1 : edge.end
                }))
            );
            setSelectedElement({ type: null, index: null });
            setHoveredNodeIndex(null);
            setHoveredHandleNode(null);
            return;
        }

        // Draw Edges mode
        if (appMode === 'edit' && mode === 'draw_paths') {
            if (drawPathStartNode.current === null) {
                // First click — store start node
                drawPathStartNode.current = index;
                setSelectedElement({ type: 'node', index });
            } else if (drawPathStartNode.current === index) {
                // Same node — cancel
                drawPathStartNode.current = null;
                setSelectedElement({ type: null, index: null });
            } else {
                // Second click — create edge
                createEdgeBetweenNodes(drawPathStartNode.current, index);
                drawPathStartNode.current = null;
            }
            return;
        }

        setSelectedElement({ type: 'node', index });
    };

    const handleEdgeClick = (index, e) => {
        e.cancelBubble = true;
        if (appMode === 'edit' && mode === 'delete_element') {
            if (!window.confirm('Delete this path?')) return;
            setEdges(prev => prev.filter((_, i) => i !== index));
            setSelectedElement({ type: null, index: null });
            setHoveredEdgeIndex(null);
            return;
        }
        setSelectedElement({ type: 'edge', index });
    };

    const getDistanceToSegment = (p, p1, p2) => {
        const A = p.x - p1.x, B = p.y - p1.y;
        const C = p2.x - p1.x, D = p2.y - p1.y;
        const dot = A * C + B * D;
        const lenSq = C * C + D * D;
        let param = lenSq !== 0 ? dot / lenSq : -1;

        let xx, yy;
        if (param < 0)      { xx = p1.x; yy = p1.y; }
        else if (param > 1) { xx = p2.x; yy = p2.y; }
        else                { xx = p1.x + param * C; yy = p1.y + param * D; }

        return Math.hypot(p.x - xx, p.y - yy);
    };

    const handleLineDblClick = (index, e) => {
        if (appMode !== 'edit') return;
        e.cancelBubble = true;

        const stage      = e.currentTarget.getStage();
        const pos        = stage.getPointerPosition();
        const transform  = stage.getAbsoluteTransform().copy().invert();
        const relativePos = transform.point(pos);

        const edge = edges[index];
        if (!edge || !edge.pathPoints || edge.pathPoints.length < 2) return;

        let minDistance = Infinity;
        let insertIndex = -1;

        for (let i = 0; i < edge.pathPoints.length - 1; i++) {
            const dist = getDistanceToSegment(relativePos, edge.pathPoints[i], edge.pathPoints[i + 1]);
            if (dist < minDistance) { minDistance = dist; insertIndex = i + 1; }
        }

        if (insertIndex !== -1) {
            const newPoints = [...edge.pathPoints];
            newPoints.splice(insertIndex, 0, { x: relativePos.x, y: relativePos.y });
            const newEdges = [...edges];
            newEdges[index] = {
                ...edge,
                pathPoints:       newPoints,
                customPathPoints: newPoints,
                isCustom:         true,
                weight:           getPathLength(newPoints, parseFloat(editScaleRatio) || 1.0)
            };
            setEdges(newEdges);
        }
    };

    const handleControlPointDblClick = (edgeIndex, ptIdx, e) => {
        e.cancelBubble = true;
        if (appMode !== 'edit') return;

        const edge = edges[edgeIndex];
        if (!edge || !edge.pathPoints || edge.pathPoints.length <= 2) return;

        const newPoints = edge.pathPoints.filter((_, idx) => idx !== ptIdx);
        const newEdges  = [...edges];
        newEdges[edgeIndex] = {
            ...edge,
            pathPoints:       newPoints,
            customPathPoints: newPoints,
            isCustom:         true,
            weight:           getPathLength(newPoints, parseFloat(editScaleRatio) || 1.0)
        };
        setEdges(newEdges);
    };

    // ── Edge Drawing via Hover Handles ────────────────────────────────────────

    const handleHandleDragStart = (nodeIndex, e) => {
        e.cancelBubble = true;
        if (appMode !== 'edit') return;
        const stage = e.target.getStage();
        const pos = stage.getPointerPosition();
        const transform = stage.getAbsoluteTransform().copy().invert();
        setEdgeDrawState({
            startNodeIndex: nodeIndex,
            currentPos: transform.point(pos)
        });
    };

    const handleHandleDragMove = (e) => {
        e.cancelBubble = true;
        if (!edgeDrawState) return;
        const stage = e.target.getStage();
        const pos = stage.getPointerPosition();
        const transform = stage.getAbsoluteTransform().copy().invert();
        setEdgeDrawState({
            ...edgeDrawState,
            currentPos: transform.point(pos)
        });
    };

    const handleHandleDragEnd = (e) => {
        e.cancelBubble = true;
        if (!edgeDrawState) return;
        
        const stage = e.target.getStage();
        const pos = stage.getPointerPosition();
        const transform = stage.getAbsoluteTransform().copy().invert();
        const localPos = transform.point(pos);
        
        let targetNodeIndex = null;
        let minDist = Infinity;
        
        for (let i = 0; i < nodes.length; i++) {
            if (i === edgeDrawState.startNodeIndex) continue;
            const node = nodes[i];
            const dist = Math.hypot(node.x - localPos.x, node.y - localPos.y);
            if (dist < 20 && dist < minDist) {
                minDist = dist;
                targetNodeIndex = i;
            }
        }
        
        if (targetNodeIndex !== null) {
            createEdgeBetweenNodes(edgeDrawState.startNodeIndex, targetNodeIndex);
        }
        
        setEdgeDrawState(null);
    };

    // ── Node Drag Handlers ────────────────────────────────────────────────────

    /**
     * Handles real-time node position updates during drag.
     * Stretches connected edge paths to follow the moving node without full A* recalculation.
     *
     * @param {number} index - Node index.
     * @param {Konva.KonvaEventObject<MouseEvent>} e
     */
    const handleNodeDragMove = (index, e) => {
        e.cancelBubble = true;
        const newX = Math.max(0, Math.min(e.target.x(), CANVAS_WIDTH));
        const newY = Math.max(0, Math.min(e.target.y(), CANVAS_HEIGHT));

        const newNodes = [...nodes];
        newNodes[index] = { ...newNodes[index], x: newX, y: newY };
        setNodes(newNodes);

        const newEdges = edges.map(edge => {
            if (edge.is_cross_floor) return edge;
            if (edge.start === index || edge.end === index) {
                const points = edge.pathPoints ? [...edge.pathPoints] : [];
                if (points.length >= 2) {
                    if (edge.start === index) points[0]                   = { x: newX, y: newY };
                    if (edge.end   === index) points[points.length - 1]   = { x: newX, y: newY };
                    return {
                        ...edge,
                        pathPoints: points,
                        weight:     getPathLength(points, parseFloat(editScaleRatio) || 1.0)
                    };
                }
            }
            return edge;
        });
        setEdges(newEdges);
    };

    /**
     * Handles the end of a node drag, triggering A* recalculation on connected non-custom edges.
     * Sets `needsRecalc: true` on affected edges so the AI A* effect recalculates paths.
     *
     * @param {number} index - Node index.
     * @param {Konva.KonvaEventObject<MouseEvent>} e
     */
    const handleNodeDragEnd = (index, e) => {
        e.cancelBubble = true;
        const newX = Math.max(0, Math.min(e.target.x(), CANVAS_WIDTH));
        const newY = Math.max(0, Math.min(e.target.y(), CANVAS_HEIGHT));

        const newNodes = [...nodes];
        const movedNode = { ...newNodes[index], x: newX, y: newY };

        // If the admin dragged an AI-generated node, mark it as MODIFIED
        if (movedNode.ai_generated && movedNode.review_status === 'PENDING') {
            movedNode.review_status = 'MODIFIED';
        }

        newNodes[index] = movedNode;
        setNodes(newNodes);

        const newEdges = edges.map(edge => {
            if (edge.is_cross_floor) return edge;
            if (edge.start === index || edge.end === index) {
                return { ...edge, needsRecalc: true };
            }
            return edge;
        });
        setEdges(newEdges);
    };

    // ── Properties Panel Handlers ─────────────────────────────────────────────

    /**
     * Updates a single property on the currently selected node or edge.
     * When updating `allowed_roles` on a node, automatically recalculates edge RBAC intersections.
     *
     * @param {string} field - The property key to update.
     * @param {*}      value - The new value.
     */
    const updateProperty = (field, value) => {
        if (selectedElement.type === 'node') {
            const newNodes = [...nodes];
            const updatedNode = { ...newNodes[selectedElement.index], [field]: value };

            // If admin edits any property on an AI-generated PENDING node, mark it MODIFIED
            if (updatedNode.ai_generated && updatedNode.review_status === 'PENDING') {
                updatedNode.review_status = 'MODIFIED';
            }

            newNodes[selectedElement.index] = updatedNode;

            let updatedEdges = [...edges];
            let emptyIntersectionCount = 0;

            if (field === 'allowed_roles') {
                const updatedNodeRoles = value || [];
                updatedEdges = edges.map(edge => {
                    if (edge.start === selectedElement.index || (edge.end === selectedElement.index && !edge.is_cross_floor)) {
                        let otherRoles = [];
                        if (edge.is_cross_floor) {
                            const targetNode = globalNodes.find(gn => Number(gn.node_id) === Number(edge.target_node_id));
                            otherRoles = targetNode
                                ? (typeof targetNode.allowed_roles === 'string'
                                    ? targetNode.allowed_roles.split(',').map(Number)
                                    : targetNode.allowed_roles || [])
                                : [];
                        } else {
                            const otherNodeIndex = edge.start === selectedElement.index ? edge.end : edge.start;
                            otherRoles = newNodes[otherNodeIndex]?.allowed_roles || [];
                        }

                        const intersection = updatedNodeRoles.filter(r => otherRoles.includes(r));
                        let isAccessible   = edge.is_accessible;
                        if (intersection.length === 0 && edge.is_accessible === 'ALLOW') {
                            isAccessible = 'DENY';
                            emptyIntersectionCount++;
                        }
                        return { ...edge, allowed_roles: intersection, is_accessible: isAccessible };
                    }
                    return edge;
                });
            }

            setNodes(newNodes);
            setEdges(updatedEdges);
            if (emptyIntersectionCount > 0) {
                alert(`Warning: Updating node permissions left ${emptyIntersectionCount} connected path(s) with an empty access role intersection. These path(s) have been automatically set to disabled.`);
            }
        } else if (selectedElement.type === 'edge') {
            const newEdges = [...edges];
            newEdges[selectedElement.index] = { ...newEdges[selectedElement.index], [field]: value };
            setEdges(newEdges);
        }
    };

    /**
     * Toggles a role ID in the `allowed_roles` array of the selected node or edge.
     * Delegates to `updateProperty('allowed_roles', ...)`.
     *
     * @param {number} roleId - The role ID to toggle.
     */
    const handleRoleToggle = (roleId) => {
        const element      = selectedElement.type === 'node' ? nodes[selectedElement.index] : edges[selectedElement.index];
        const currentRoles = element.allowed_roles || [];
        const newRoles     = currentRoles.includes(roleId)
            ? currentRoles.filter(id => id !== roleId)
            : [...currentRoles, roleId];
        updateProperty('allowed_roles', newRoles);
    };

    // ── Transition Linker Handlers ────────────────────────────────────────────

    /**
     * Creates a new cross-floor transition edge from the currently selected node
     * to the specified target node on another floorplan.
     */
    const handleCreateTransition = () => {
        if (!transitionTargetId || !transitionWeight) {
            alert('Please select a target destination and specify a distance.');
            return;
        }

        const startNode   = nodes[selectedElement.index];
        const startRoles  = startNode?.allowed_roles || [];
        const targetNode  = globalNodes.find(gn => Number(gn.node_id) === Number(transitionTargetId));
        const targetRoles = targetNode
            ? (typeof targetNode.allowed_roles === 'string'
                ? targetNode.allowed_roles.split(',').map(Number)
                : targetNode.allowed_roles || [])
            : [];
        const intersection = startRoles.filter(r => targetRoles.includes(r));
        let isAccessible   = transitionIsAccessible ? 'ALLOW' : 'DENY';

        if (intersection.length === 0) {
            const confirmSave = window.confirm(
                'The selected nodes do not share any access roles. This edge will not be traversable by any user.\n\n' +
                'Click OK to save the edge as a disabled/inactive path, or Cancel to abort.'
            );
            if (!confirmSave) return;
            isAccessible = 'DENY';
        }

        setEdges([...edges, {
            edge_id:          null,
            start:            selectedElement.index,
            is_cross_floor:   true,
            target_node_id:   Number(transitionTargetId),
            weight:           parseFloat(transitionWeight),
            is_bidirectional: transitionIsBidirectional,
            is_accessible:    isAccessible,
            allowed_roles:    intersection
        }]);
        alert("Transition link created! Remember to click 'Save Official Map' to persist changes.");
    };

    /**
     * Updates an existing cross-floor transition edge's attributes.
     *
     * @param {number} existingIndex - Index of the transition edge in the `edges` array.
     */
    const handleUpdateTransition = (existingIndex) => {
        if (!transitionWeight) { alert('Please specify a distance.'); return; }

        const edge       = edges[existingIndex];
        const startNode  = nodes[selectedElement.index];
        const startRoles = startNode?.allowed_roles || [];
        const targetNode = globalNodes.find(gn => Number(gn.node_id) === Number(edge.target_node_id));
        const targetRoles = targetNode
            ? (typeof targetNode.allowed_roles === 'string'
                ? targetNode.allowed_roles.split(',').map(Number)
                : targetNode.allowed_roles || [])
            : [];
        const intersection = startRoles.filter(r => targetRoles.includes(r));
        let isAccessible   = transitionIsAccessible ? 'ALLOW' : 'DENY';

        if (intersection.length === 0) {
            const confirmSave = window.confirm(
                'The selected nodes do not share any access roles. This edge will not be traversable by any user.\n\n' +
                'Click OK to save the edge as a disabled/inactive path, or Cancel to abort.'
            );
            if (!confirmSave) return;
            isAccessible = 'DENY';
        }

        const newEdges = [...edges];
        newEdges[existingIndex] = {
            ...newEdges[existingIndex],
            weight:           parseFloat(transitionWeight),
            is_bidirectional: transitionIsBidirectional,
            is_accessible:    isAccessible,
            allowed_roles:    intersection
        };
        setEdges(newEdges);
        alert("Transition link details updated! Remember to click 'Save to Database' to persist.");
    };

    /**
     * Deletes an existing cross-floor transition edge and resets the transition form fields.
     *
     * @param {number} existingIndex - Index of the transition edge in the `edges` array.
     */
    const handleDeleteTransition = (existingIndex) => {
        if (!window.confirm('Are you sure you want to delete this transition link? The node itself will not be deleted.')) return;
        setEdges(edges.filter((_, idx) => idx !== existingIndex));
        setTransitionTargetId('');
        setTransitionWeight('10');
        setTransitionIsAccessible(true);
        setTransitionIsBidirectional(true);
        alert("Transition link deleted! Remember to click 'Save to Database' to persist.");
    };

    // ── Edge A* Manipulation Handlers ─────────────────────────────────────────

    /**
     * Triggers a manual A* re-route for the currently selected edge.
     * Updates the edge path to navigate around walls and clears the `isCustom` flag.
     */
    const triggerSelectedEdgeAStar = () => {
        if (selectedElement.type !== 'edge') return;
        const index     = selectedElement.index;
        const edge      = edges[index];
        const startNode = nodes[edge.start];
        const endNode   = nodes[edge.end];

        const currentWallGrid = getWallGrid ? getWallGrid() : [];
        if (!startNode || !endNode || !currentWallGrid || currentWallGrid.length === 0) {
            alert('AI Route cannot be calculated. Ensure CV wall mask is loaded.');
            return;
        }

        const astar = findAStarPath(startNode, endNode, currentWallGrid, 8);
        if (astar) {
            const simplified = simplifyPath(astar);
            const newEdges   = [...edges];
            newEdges[index]  = {
                ...edge,
                pathPoints:       simplified,
                customPathPoints: null,
                isCustom:         false,
                weight:           getPathLength(simplified, parseFloat(editScaleRatio) || 1.0)
            };
            setEdges(newEdges);
        } else {
            alert('Warning: AI pathfinding could not navigate around walls. Path remains unchanged.');
        }
    };

    /**
     * Resets the selected edge to a straight line between its two endpoint nodes.
     */
    const resetSelectedEdgeToStraight = () => {
        if (selectedElement.type !== 'edge') return;
        const index         = selectedElement.index;
        const edge          = edges[index];
        const startNode     = nodes[edge.start];
        const endNode       = nodes[edge.end];
        const straightPoints = [{ x: startNode.x, y: startNode.y }, { x: endNode.x, y: endNode.y }];
        const newEdges      = [...edges];
        newEdges[index]     = {
            ...edge,
            pathPoints:       straightPoints,
            customPathPoints: straightPoints,
            isCustom:         true,
            weight:           getPathLength(straightPoints, parseFloat(editScaleRatio) || 1.0)
        };
        setEdges(newEdges);
    };

    // ─────────────────────────────────────────────────────────────────────────
    // AI NODE IMPORT
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Import AI-generated nodes from a FloorplanAnalysisResult into the canvas.
     *
     * Each AiNode from the analysis result is converted to the canvas node format
     * and appended to the existing nodes array. Preserves all AI metadata fields
     * (ai_generated, ai_confidence, ai_source, review_status, source_room_id)
     * so the canvas renderer can display a distinct visual style for AI nodes,
     * and the PropertiesPanel can show the review UI.
     *
     * Existing manually created nodes are NOT replaced.
     *
     * @param {Object} analysisResult - FloorplanAnalysisResult from the AI service.
     */
    const importAiNodes = (analysisResult) => {
        if (!analysisResult || !analysisResult.nodes) return;

        setAiAnalysisResult(analysisResult);

        const aiNodes = analysisResult.nodes.map((aiNode) => ({
            // Standard canvas node fields
            node_id:       null,                          // Not in DB yet
            x:             aiNode.x,
            y:             aiNode.y,
            room_label:    aiNode.room_label,
            node_type:     aiNode.node_type || 'ROOM',
            is_accessible: aiNode.is_accessible || 'ALLOW',
            allowed_roles: aiNode.allowed_roles || [],   // Empty — no RBAC from AI

            // AI metadata fields — used by the canvas renderer for distinct styling
            // and by PropertiesPanel for the review UI
            ai_generated:   true,
            ai_confidence:  aiNode.ai_confidence,
            ai_source:      aiNode.ai_source,
            review_status:  aiNode.review_status || 'PENDING',
            source_room_id: aiNode.source_room_id,
            temp_id:        aiNode.temp_id,
        }));

        // Append AI nodes to existing canvas nodes (do not replace manual nodes)
        setNodes(prev => [...prev, ...aiNodes]);
    };

    /**
     * Clears the stored AI analysis result and removes all PENDING AI-generated
     * nodes from the canvas. MODIFIED or APPROVED AI nodes are kept as they
     * have already been reviewed and may have been intentionally edited.
     */
    const clearAiAnalysis = () => {
        setAiAnalysisResult(null);
        setNodes(prev => prev.filter(
            n => !(n.ai_generated && n.review_status === 'PENDING')
        ));
    };

    return {
        // State
        nodes, setNodes,
        edges, setEdges,
        appMode, setAppMode,
        mode, setMode, selectTool,
        selectedElement, setSelectedElement,
        hoveredNodeIndex, setHoveredNodeIndex,
        hoveredEdgeIndex, setHoveredEdgeIndex,
        hoveredHandleNode, setHoveredHandleNode,
        edgeDrawState, setEdgeDrawState,
        activeNodeTab, setActiveNodeTab,
        transitionTargetId, setTransitionTargetId,
        transitionWeight, setTransitionWeight,
        transitionIsAccessible, setTransitionIsAccessible,
        transitionIsBidirectional, setTransitionIsBidirectional,
        dimensions,
        stageScale, setStageScale, 
        stageX, setStageX, 
        stageY, setStageY,
        containerRef,
        stageRef,
        isDraggingStage,
        isDraggingControlPoint,
        drawPathStartNode,
        mouseDownPos,
        fileInputRef,
        // AI Analysis State
        aiAnalysisResult,
        // Derived
        activeObj,
        isTransitionNode,
        // Handlers
        getClampedDragBounds,
        handleResetView,
        handleWheel,
        handleStageMouseDown,
        handleMapClick,
        handleMapDblClick,
        handleNodeClick,
        handleEdgeClick,
        handleLineDblClick,
        handleControlPointDblClick,
        handleNodeDragMove,
        handleNodeDragEnd,
        handleHandleDragStart,
        handleHandleDragMove,
        handleHandleDragEnd,
        updateProperty,
        handleRoleToggle,
        handleCreateTransition,
        handleUpdateTransition,
        handleDeleteTransition,
        handleDeleteSelected,
        triggerSelectedEdgeAStar,
        resetSelectedEdgeToStraight,
        importAiNodes,
        clearAiAnalysis,
    };
}
