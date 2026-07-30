import { useState, useEffect, useRef } from 'react';
import { findAStarPath, simplifyPath, getPathLength } from '../utils/pathfinding';
import { TRANSITION_TYPES, CANVAS_WIDTH, CANVAS_HEIGHT } from '../constants/mapConstants';

export function useMapEditor({ rolesList, globalNodes, getWallGrid, editScaleRatio, imageObj }) {
    const [nodes, setNodes]             = useState([]);
    const [edges, setEdges]             = useState([]);
    const [mode, setMode]               = useState('');
    const [selectedElement, setSelectedElement] = useState({ type: null, index: null });
    const [hoveredNodeIndex, setHoveredNodeIndex] = useState(null);
    const [hoveredEdgeIndex, setHoveredEdgeIndex] = useState(null);

    const [activeNodeTab, setActiveNodeTab] = useState('general');

    const [transitionTargetId, setTransitionTargetId]         = useState('');
    const [transitionWeight, setTransitionWeight]             = useState('10');
    const [transitionIsAccessible, setTransitionIsAccessible] = useState(true);
    const [transitionIsBidirectional, setTransitionIsBidirectional] = useState(true);

    const [dimensions, setDimensions] = useState({ width: CANVAS_WIDTH, height: CANVAS_HEIGHT });
    const [stageScale, setStageScale] = useState(1.0);
    const [stageX, setStageX]         = useState(0);
    const [stageY, setStageY]         = useState(0);

    const containerRef            = useRef(null);
    const stageRef                = useRef(null);
    const isDraggingStage         = useRef(false);
    const isDraggingControlPoint  = useRef(false);
    const mouseDownPos            = useRef(null);
    const fileInputRef            = useRef(null);

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

    useEffect(() => {
        if (imageObj) {
            const scaleX   = dimensions.width  / CANVAS_WIDTH;
            const scaleY   = dimensions.height / CANVAS_HEIGHT;
            const fitScale = Math.min(scaleX, scaleY) * 0.95;
            setStageScale(fitScale);
            setStageX((dimensions.width  - CANVAS_WIDTH  * fitScale) / 2);
            setStageY((dimensions.height - CANVAS_HEIGHT * fitScale) / 2);
        }
    }, [imageObj]);

    const activeObj = selectedElement.index !== null
        ? (selectedElement.type === 'node'
            ? nodes[selectedElement.index]
            : edges[selectedElement.index])
        : null;

    const isTransitionNode =
        selectedElement.type === 'node' &&
        activeObj &&
        TRANSITION_TYPES.includes(activeObj.node_type);

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

    const handleResetView = () => {
        if (!imageObj) return;
        const scaleX   = dimensions.width  / CANVAS_WIDTH;
        const scaleY   = dimensions.height / CANVAS_HEIGHT;
        const fitScale = Math.min(scaleX, scaleY) * 0.95;
        setStageScale(fitScale);
        setStageX((dimensions.width  - CANVAS_WIDTH  * fitScale) / 2);
        setStageY((dimensions.height - CANVAS_HEIGHT * fitScale) / 2);
    };

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

    const handleStageMouseDown = (e) => {
        const stage = e.currentTarget.getStage();
        mouseDownPos.current = stage.getPointerPosition();
    };

    const handleMapClick = (e) => {
        if (e.target !== e.target.getStage() && e.target.className !== 'Image') return;

        const stage = e.target.getStage();
        const pos   = stage.getPointerPosition();
        if (mouseDownPos.current) {
            const dist = Math.hypot(pos.x - mouseDownPos.current.x, pos.y - mouseDownPos.current.y);
            if (dist > 5) return;
        }

        if (!imageObj || mode !== 'add_nodes') return;

        const transform   = stage.getAbsoluteTransform().copy().invert();
        const relativePos = transform.point(pos);
        const clampedX    = Math.max(0, Math.min(relativePos.x, CANVAS_WIDTH));
        const clampedY    = Math.max(0, Math.min(relativePos.y, CANVAS_HEIGHT));

        const allRoleIds = rolesList.map(r => r.role_id || r.id);
        setNodes([...nodes, {
            node_id:       null,
            x:             clampedX,
            y:             clampedY,
            room_label:    `Node ${nodes.length + 1}`,
            node_type:     'CORRIDOR',
            is_accessible: 'ALLOW',
            allowed_roles: allRoleIds
        }]);
    };

    const handleNodeClick = (index, e) => {
        e.cancelBubble = true;
        if (mode === 'edit_props') {
            setSelectedElement({ type: 'node', index });
            return;
        }
        if (mode === 'delete_element') {
            if (!window.confirm('Delete this node and its connected paths?')) return;
            setNodes(nodes.filter((_, i) => i !== index));
            setEdges(edges
                .filter(edge => edge.start !== index && edge.end !== index)
                .map(edge => ({
                    ...edge,
                    start: edge.start > index ? edge.start - 1 : edge.start,
                    end:   edge.end   > index ? edge.end   - 1 : edge.end
                }))
            );
            setSelectedElement({ type: null, index: null });
            setHoveredNodeIndex(null);
            return;
        }
        if (mode !== 'draw_paths') return;

        if (selectedElement.index === null || selectedElement.type !== 'node') {
            setSelectedElement({ type: 'node', index });
        } else {
            if (selectedElement.index !== index) {
                const startNode = nodes[selectedElement.index];
                const endNode   = nodes[index];

                const startRoles   = startNode.allowed_roles || [];
                const endRoles     = endNode.allowed_roles || [];
                const intersection = startRoles.filter(r => endRoles.includes(r));
                let isAccessible   = 'ALLOW';

                if (intersection.length === 0) {
                    const confirmSave = window.confirm(
                        'The selected nodes do not share any access roles. This edge will not be traversable by any user.\n\n' +
                        'Click OK to save the edge as a disabled/inactive path, or Cancel to abort.'
                    );
                    if (!confirmSave) {
                        setSelectedElement({ type: null, index: null });
                        return;
                    }
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
                setEdges([...edges, {
                    edge_id:          null,
                    start:            selectedElement.index,
                    end:              index,
                    weight:           getPathLength(pathPoints, scale),
                    is_bidirectional: true,
                    is_accessible:    isAccessible,
                    allowed_roles:    intersection,
                    isCustom:         false,
                    customPathPoints: null,
                    pathPoints
                }]);
            }
            setSelectedElement({ type: null, index: null });
        }
    };

    const handleEdgeClick = (index, e) => {
        e.cancelBubble = true;
        if (mode === 'edit_props') { setSelectedElement({ type: 'edge', index }); return; }
        if (mode === 'delete_element') {
            if (!window.confirm('Delete this path?')) return;
            setEdges(edges.filter((_, i) => i !== index));
            setHoveredEdgeIndex(null);
        }
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
        if (mode !== 'edit_props') return;
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
        if (mode !== 'edit_props') return;

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

    const handleNodeDragEnd = (index, e) => {
        e.cancelBubble = true;
        const newX = Math.max(0, Math.min(e.target.x(), CANVAS_WIDTH));
        const newY = Math.max(0, Math.min(e.target.y(), CANVAS_HEIGHT));

        const newNodes = [...nodes];
        newNodes[index] = { ...newNodes[index], x: newX, y: newY };
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

    const updateProperty = (field, value) => {
        if (selectedElement.type === 'node') {
            const newNodes = [...nodes];
            newNodes[selectedElement.index] = { ...newNodes[selectedElement.index], [field]: value };

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

    const handleRoleToggle = (roleId) => {
        const element      = selectedElement.type === 'node' ? nodes[selectedElement.index] : edges[selectedElement.index];
        const currentRoles = element.allowed_roles || [];
        const newRoles     = currentRoles.includes(roleId)
            ? currentRoles.filter(id => id !== roleId)
            : [...currentRoles, roleId];
        updateProperty('allowed_roles', newRoles);
    };

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

    const handleDeleteTransition = (existingIndex) => {
        if (!window.confirm('Are you sure you want to delete this transition link? The node itself will not be deleted.')) return;
        setEdges(edges.filter((_, idx) => idx !== existingIndex));
        setTransitionTargetId('');
        setTransitionWeight('10');
        setTransitionIsAccessible(true);
        setTransitionIsBidirectional(true);
        alert("Transition link deleted! Remember to click 'Save to Database' to persist.");
    };

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

    const selectTool = (toolMode, floorplanId) => {
        if (!floorplanId) return alert('Please upload or select a floorplan first.');
        setMode(toolMode);
        setSelectedElement({ type: null, index: null });
    };

    return {
        nodes, setNodes,
        edges, setEdges,
        mode, setMode,
        selectedElement, setSelectedElement,
        hoveredNodeIndex, setHoveredNodeIndex,
        hoveredEdgeIndex, setHoveredEdgeIndex,
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
        mouseDownPos,
        fileInputRef,
        activeObj,
        isTransitionNode,
        getClampedDragBounds,
        handleResetView,
        handleWheel,
        handleStageMouseDown,
        handleMapClick,
        handleNodeClick,
        handleEdgeClick,
        handleLineDblClick,
        handleControlPointDblClick,
        handleNodeDragMove,
        handleNodeDragEnd,
        updateProperty,
        handleRoleToggle,
        handleCreateTransition,
        handleUpdateTransition,
        handleDeleteTransition,
        triggerSelectedEdgeAStar,
        resetSelectedEdgeToStraight,
        selectTool
    };
}
