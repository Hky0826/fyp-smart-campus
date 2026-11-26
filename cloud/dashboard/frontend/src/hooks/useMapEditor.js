/**
 * @file useMapEditor.js
 * @description Map editor state and Konva interaction hook with Toast, ConfirmDialog,
 * keyboard shortcuts, unsaved-change tracking, and instant A* drag recalculation.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { findAStarPath, simplifyPath, getPathLength } from '../utils/pathfinding';
import { TRANSITION_TYPES, CANVAS_WIDTH, CANVAS_HEIGHT } from '../constants/mapConstants';
import { useToast } from '../providers/ToastProvider';

export function useMapEditor({
  rolesList,
  globalNodes,
  getWallGrid,
  editScaleRatio,
  imageObj,
  fileInputRef: externalFileInputRef,
  requestConfirm,
}) {
  const toast = useToast();

  // ── Graph State ─────────────────────────────────────────────────────────────
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [isDirty, setIsDirty] = useState(false);
  const [showAllLabels, setShowAllLabels] = useState(false);
  const [appMode, setAppMode] = useState('edit'); // 'edit' or 'test'
  const [mode, setMode] = useState('');
  const [selectedElement, setSelectedElement] = useState({ type: null, index: null });
  const [hoveredNodeIndex, setHoveredNodeIndex] = useState(null);
  const [hoveredEdgeIndex, setHoveredEdgeIndex] = useState(null);
  const [hoveredHandleNode, setHoveredHandleNode] = useState(null);
  const [edgeDrawState, setEdgeDrawState] = useState(null);

  const selectTool = useCallback((tool, floorplanId) => {
    if (!floorplanId) return;
    setMode((prev) => (prev === tool ? '' : tool));
  }, []);

  // ── AI Analysis State ───────────────────────────────────────────────────────
  const [aiAnalysisResult, setAiAnalysisResult] = useState(null);

  // ── Properties Panel Tab State ──────────────────────────────────────────────
  const [activeNodeTab, setActiveNodeTab] = useState('general');

  // ── Transition Linker State ─────────────────────────────────────────────────
  const [transitionTargetId, setTransitionTargetId] = useState('');
  const [transitionWeight, setTransitionWeight] = useState('10');
  const [transitionIsAccessible, setTransitionIsAccessible] = useState(true);
  const [transitionIsBidirectional, setTransitionIsBidirectional] = useState(true);

  // ── Canvas Pan / Zoom State ─────────────────────────────────────────────────
  const [dimensions, setDimensions] = useState({ width: CANVAS_WIDTH, height: CANVAS_HEIGHT });
  const [stageScale, setStageScale] = useState(1.0);
  const [stageX, setStageX] = useState(0);
  const [stageY, setStageY] = useState(0);

  // ── Refs ────────────────────────────────────────────────────────────────────
  const containerRef = useRef(null);
  const stageRef = useRef(null);
  const isDraggingStage = useRef(false);
  const isDraggingControlPoint = useRef(false);
  const drawPathStartNode = useRef(null);
  const mouseDownPos = useRef(null);
  const internalFileInputRef = useRef(null);
  const fileInputRef = externalFileInputRef || internalFileInputRef;

  const confirmAction = useCallback(
    (opts) => {
      if (requestConfirm) {
        requestConfirm(opts);
      } else if (window.confirm(opts.message || opts.title)) {
        opts.onConfirm?.();
      }
    },
    [requestConfirm]
  );

  // ── Mode Switch Effect ──────────────────────────────────────────────────────
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

  useEffect(() => {
    if (mode !== 'draw_paths') {
      drawPathStartNode.current = null;
    }
  }, [mode]);

  // ── Reset transition fields when selected node changes ──────────────────────
  useEffect(() => {
    if (selectedElement.type === 'node') {
      const node = nodes[selectedElement.index];
      if (node) {
        if (!TRANSITION_TYPES.includes(node.node_type)) {
          setActiveNodeTab('general');
        }
        const existingTransition = edges.find(
          (e) => e.start === selectedElement.index && e.is_cross_floor
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

  // ── Respond to container resize ─────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
          setDimensions({
            width: entry.contentRect.width,
            height: entry.contentRect.height,
          });
        }
      }
    });
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  // ── Auto-fit image on load or container resize ──────────────────────────────
  useEffect(() => {
    if (imageObj && dimensions.width > 0 && dimensions.height > 0) {
      const scaleX = dimensions.width / CANVAS_WIDTH;
      const scaleY = dimensions.height / CANVAS_HEIGHT;
      const fitScale = Math.min(scaleX, scaleY) * 0.92;
      setStageScale(fitScale);
      setStageX((dimensions.width - CANVAS_WIDTH * fitScale) / 2);
      setStageY((dimensions.height - CANVAS_HEIGHT * fitScale) / 2);
    }
  }, [imageObj, dimensions.width, dimensions.height]);

  const activeObj =
    selectedElement.index !== null
      ? selectedElement.type === 'node'
        ? nodes[selectedElement.index]
        : edges[selectedElement.index]
      : null;

  const isTransitionNode =
    selectedElement.type === 'node' &&
    Boolean(activeObj) &&
    TRANSITION_TYPES.includes(activeObj.node_type);

  const pendingAiCount = nodes.filter(
    (n) => n.ai_generated && n.review_status === 'PENDING'
  ).length;

  const getClampedDragBounds = (pos) => {
    const stage = stageRef.current;
    if (!stage) return pos;
    const transform = stage.getAbsoluteTransform().copy().invert();
    const localPos = transform.point(pos);
    const clampedLocal = {
      x: Math.max(0, Math.min(localPos.x, CANVAS_WIDTH)),
      y: Math.max(0, Math.min(localPos.y, CANVAS_HEIGHT)),
    };
    return stage.getAbsoluteTransform().point(clampedLocal);
  };

  const handleResetView = useCallback(() => {
    if (!imageObj) return;
    const scaleX = dimensions.width / CANVAS_WIDTH;
    const scaleY = dimensions.height / CANVAS_HEIGHT;
    const fitScale = Math.min(scaleX, scaleY) * 0.92;
    setStageScale(fitScale);
    setStageX((dimensions.width - CANVAS_WIDTH * fitScale) / 2);
    setStageY((dimensions.height - CANVAS_HEIGHT * fitScale) / 2);
  }, [imageObj, dimensions.width, dimensions.height]);

  const handleWheel = (e) => {
    e.evt.preventDefault();
    const stage = e.currentTarget.getStage();
    const oldScale = stage.scaleX();
    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    const scaleX = dimensions.width / CANVAS_WIDTH;
    const scaleY = dimensions.height / CANVAS_HEIGHT;
    const fitScale = Math.min(scaleX, scaleY) * 0.5;

    const scaleBy = 1.15;
    const newScale = e.evt.deltaY < 0 ? oldScale * scaleBy : oldScale / scaleBy;
    const clampedScale = Math.max(fitScale, Math.min(newScale, 10));

    const mousePointTo = {
      x: (pointer.x - stage.x()) / oldScale,
      y: (pointer.y - stage.y()) / oldScale,
    };

    setStageScale(clampedScale);
    setStageX(pointer.x - mousePointTo.x * clampedScale);
    setStageY(pointer.y - mousePointTo.y * clampedScale);
  };

  const handleStageMouseDown = (e) => {
    const stage = e.currentTarget.getStage();
    mouseDownPos.current = stage.getPointerPosition();
  };

  const deleteNodeByIndex = useCallback((index) => {
    setNodes((prev) => prev.filter((_, i) => i !== index));
    setEdges((prev) =>
      prev
        .filter((edge) => edge.start !== index && edge.end !== index)
        .map((edge) => ({
          ...edge,
          start: edge.start > index ? edge.start - 1 : edge.start,
          end: edge.end > index ? edge.end - 1 : edge.end,
        }))
    );
    setSelectedElement({ type: null, index: null });
    setHoveredNodeIndex(null);
    setHoveredHandleNode(null);
    setIsDirty(true);
  }, []);

  const deleteEdgeByIndex = useCallback((index) => {
    setEdges((prev) => prev.filter((_, i) => i !== index));
    setSelectedElement({ type: null, index: null });
    setHoveredEdgeIndex(null);
    setIsDirty(true);
  }, []);

  const handleDeleteSelected = useCallback(() => {
    if (selectedElement.type === 'node') {
      const index = selectedElement.index;
      const node = nodes[index];
      confirmAction({
        title: 'Delete Node?',
        message: `Remove "${node?.room_label || `Node ${index + 1}`}" and all connected paths?`,
        confirmLabel: 'Delete Node',
        variant: 'danger',
        onConfirm: () => deleteNodeByIndex(index),
      });
    } else if (selectedElement.type === 'edge') {
      const index = selectedElement.index;
      confirmAction({
        title: 'Delete Path?',
        message: 'Remove this path segment from the floorplan?',
        confirmLabel: 'Delete Path',
        variant: 'danger',
        onConfirm: () => deleteEdgeByIndex(index),
      });
    }
  }, [selectedElement, nodes, confirmAction, deleteNodeByIndex, deleteEdgeByIndex]);

  // ── Keyboard Shortcuts ──────────────────────────────────────────────────────
  useEffect(() => {
    const onKeyDown = (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;

      if (e.key === 'Escape') {
        setMode('');
        setSelectedElement({ type: null, index: null });
        drawPathStartNode.current = null;
        return;
      }

      if (appMode !== 'edit') return;

      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedElement.type !== null) {
          e.preventDefault();
          handleDeleteSelected();
        }
        return;
      }

      if (!e.ctrlKey && !e.metaKey && !e.altKey) {
        const key = e.key.toLowerCase();
        if (key === 'v') setMode('');
        else if (key === 'n') setMode((p) => (p === 'add_nodes' ? '' : 'add_nodes'));
        else if (key === 'e') setMode((p) => (p === 'draw_paths' ? '' : 'draw_paths'));
        else if (key === 'd') setMode((p) => (p === 'delete_element' ? '' : 'delete_element'));
        else if (key === 'f') handleResetView();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [appMode, selectedElement, handleDeleteSelected, handleResetView]);

  const addNodeAtPointer = (stage) => {
    const pos = stage.getPointerPosition();
    const transform = stage.getAbsoluteTransform().copy().invert();
    const relativePos = transform.point(pos);
    const clampedX = Math.max(0, Math.min(relativePos.x, CANVAS_WIDTH));
    const clampedY = Math.max(0, Math.min(relativePos.y, CANVAS_HEIGHT));

    const allRoleIds = rolesList.map((r) => r.role_id);
    const newNode = {
      node_id: null,
      x: clampedX,
      y: clampedY,
      room_label: `Node ${nodes.length + 1}`,
      node_type: 'CORRIDOR',
      is_accessible: 'ALLOW',
      allowed_roles: allRoleIds,
    };

    setNodes((prev) => {
      const newNodes = [...prev, newNode];
      setSelectedElement({ type: 'node', index: newNodes.length - 1 });
      return newNodes;
    });
    setIsDirty(true);
  };

  const handleMapClick = (e) => {
    if (e.target !== e.target.getStage() && e.target.className !== 'Image') return;

    if (appMode === 'edit' && mode === 'add_nodes') {
      addNodeAtPointer(e.target.getStage());
      return;
    }

    if (appMode === 'edit') {
      setSelectedElement({ type: null, index: null });
    }
  };

  const handleMapDblClick = (e) => {
    if (e.target !== e.target.getStage() && e.target.className !== 'Image') return;
    if (appMode !== 'edit' || !imageObj) return;
    addNodeAtPointer(e.target.getStage());
  };

  const createEdgeBetweenNodes = (startIndex, endIndex) => {
    const startNode = nodes[startIndex];
    const endNode = nodes[endIndex];
    if (!startNode || !endNode) return;

    const startRoles = startNode.allowed_roles || [];
    const endRoles = endNode.allowed_roles || [];
    const intersection = startRoles.filter((r) => endRoles.includes(r));

    const finalizeEdge = (isAccessible) => {
      let pathPoints = null;
      const currentWallGrid = getWallGrid ? getWallGrid() : [];
      if (currentWallGrid && currentWallGrid.length > 0) {
        const astar = findAStarPath(startNode, endNode, currentWallGrid, 8);
        if (astar) pathPoints = simplifyPath(astar);
      }
      if (!pathPoints) {
        pathPoints = [
          { x: startNode.x, y: startNode.y },
          { x: endNode.x, y: endNode.y },
        ];
      }

      const scale = parseFloat(editScaleRatio) || 1.0;
      const newEdge = {
        edge_id: null,
        start: startIndex,
        end: endIndex,
        weight: getPathLength(pathPoints, scale),
        is_bidirectional: true,
        is_accessible: isAccessible,
        allowed_roles: intersection,
        isCustom: false,
        customPathPoints: null,
        pathPoints,
      };

      setEdges((prev) => {
        const newEdges = [...prev, newEdge];
        setSelectedElement({ type: 'edge', index: newEdges.length - 1 });
        return newEdges;
      });
      setIsDirty(true);
    };

    if (intersection.length === 0) {
      confirmAction({
        title: 'No Shared Access Roles',
        message: 'The selected nodes do not share any campus roles. This path will not be traversable by any user.',
        impactNote: 'Continuing will create the edge as a disabled (DENY) path.',
        confirmLabel: 'Create Disabled Path',
        variant: 'info',
        onConfirm: () => finalizeEdge('DENY'),
      });
      return;
    }

    finalizeEdge('ALLOW');
  };

  const handleNodeClick = (index, e) => {
    e.cancelBubble = true;

    if (appMode === 'edit' && mode === 'delete_element') {
      const node = nodes[index];
      confirmAction({
        title: 'Delete Node?',
        message: `Remove "${node?.room_label || `Node ${index + 1}`}" and all connected paths?`,
        confirmLabel: 'Delete Node',
        variant: 'danger',
        onConfirm: () => deleteNodeByIndex(index),
      });
      return;
    }

    if (appMode === 'edit' && mode === 'draw_paths') {
      if (drawPathStartNode.current === null) {
        drawPathStartNode.current = index;
        setSelectedElement({ type: 'node', index });
      } else if (drawPathStartNode.current === index) {
        drawPathStartNode.current = null;
        setSelectedElement({ type: null, index: null });
      } else {
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
      confirmAction({
        title: 'Delete Path?',
        message: 'Remove this path segment from the floorplan?',
        confirmLabel: 'Delete Path',
        variant: 'danger',
        onConfirm: () => deleteEdgeByIndex(index),
      });
      return;
    }
    setSelectedElement({ type: 'edge', index });
  };

  const getDistanceToSegment = (p, p1, p2) => {
    const A = p.x - p1.x;
    const B = p.y - p1.y;
    const C = p2.x - p1.x;
    const D = p2.y - p1.y;
    const dot = A * C + B * D;
    const lenSq = C * C + D * D;
    const param = lenSq !== 0 ? dot / lenSq : -1;

    let xx, yy;
    if (param < 0) {
      xx = p1.x;
      yy = p1.y;
    } else if (param > 1) {
      xx = p2.x;
      yy = p2.y;
    } else {
      xx = p1.x + param * C;
      yy = p1.y + param * D;
    }

    return Math.hypot(p.x - xx, p.y - yy);
  };

  const handleLineDblClick = (index, e) => {
    if (appMode !== 'edit') return;
    e.cancelBubble = true;

    const stage = e.currentTarget.getStage();
    const pos = stage.getPointerPosition();
    const transform = stage.getAbsoluteTransform().copy().invert();
    const relativePos = transform.point(pos);

    const edge = edges[index];
    if (!edge || !edge.pathPoints || edge.pathPoints.length < 2) return;

    let minDistance = Infinity;
    let insertIndex = -1;

    for (let i = 0; i < edge.pathPoints.length - 1; i++) {
      const dist = getDistanceToSegment(relativePos, edge.pathPoints[i], edge.pathPoints[i + 1]);
      if (dist < minDistance) {
        minDistance = dist;
        insertIndex = i + 1;
      }
    }

    if (insertIndex !== -1) {
      const newPoints = [...edge.pathPoints];
      newPoints.splice(insertIndex, 0, { x: relativePos.x, y: relativePos.y });
      const newEdges = [...edges];
      newEdges[index] = {
        ...edge,
        pathPoints: newPoints,
        customPathPoints: newPoints,
        isCustom: true,
        weight: getPathLength(newPoints, parseFloat(editScaleRatio) || 1.0),
      };
      setEdges(newEdges);
      setIsDirty(true);
    }
  };

  const handleControlPointDblClick = (edgeIndex, ptIdx, e) => {
    e.cancelBubble = true;
    if (appMode !== 'edit') return;

    const edge = edges[edgeIndex];
    if (!edge || !edge.pathPoints || edge.pathPoints.length <= 2) return;

    const newPoints = edge.pathPoints.filter((_, idx) => idx !== ptIdx);
    const newEdges = [...edges];
    newEdges[edgeIndex] = {
      ...edge,
      pathPoints: newPoints,
      customPathPoints: newPoints,
      isCustom: true,
      weight: getPathLength(newPoints, parseFloat(editScaleRatio) || 1.0),
    };
    setEdges(newEdges);
    setIsDirty(true);
  };

  // ── Edge Drawing via Hover Handles ──────────────────────────────────────────
  const handleHandleDragStart = (nodeIndex, e) => {
    e.cancelBubble = true;
    if (appMode !== 'edit') return;
    const stage = e.target.getStage();
    const pos = stage.getPointerPosition();
    const transform = stage.getAbsoluteTransform().copy().invert();
    setEdgeDrawState({
      startNodeIndex: nodeIndex,
      currentPos: transform.point(pos),
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
      currentPos: transform.point(pos),
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
      if (dist < 22 && dist < minDist) {
        minDist = dist;
        targetNodeIndex = i;
      }
    }

    if (targetNodeIndex !== null) {
      createEdgeBetweenNodes(edgeDrawState.startNodeIndex, targetNodeIndex);
    }

    setEdgeDrawState(null);
  };

  // ── Node Drag Handlers ──────────────────────────────────────────────────────
  const handleNodeDragMove = (index, e) => {
    e.cancelBubble = true;
    const newX = Math.max(0, Math.min(e.target.x(), CANVAS_WIDTH));
    const newY = Math.max(0, Math.min(e.target.y(), CANVAS_HEIGHT));

    const newNodes = [...nodes];
    newNodes[index] = { ...newNodes[index], x: newX, y: newY };
    setNodes(newNodes);

    const newEdges = edges.map((edge) => {
      if (edge.is_cross_floor) return edge;
      if (edge.start === index || edge.end === index) {
        const points = edge.pathPoints ? [...edge.pathPoints] : [];
        if (points.length >= 2) {
          if (edge.start === index) points[0] = { x: newX, y: newY };
          if (edge.end === index) points[points.length - 1] = { x: newX, y: newY };
          return {
            ...edge,
            pathPoints: points,
            weight: getPathLength(points, parseFloat(editScaleRatio) || 1.0),
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
    const movedNode = { ...newNodes[index], x: newX, y: newY };

    if (movedNode.ai_generated && movedNode.review_status === 'PENDING') {
      movedNode.review_status = 'MODIFIED';
    }

    newNodes[index] = movedNode;
    setNodes(newNodes);
    setIsDirty(true);

    const currentWallGrid = getWallGrid ? getWallGrid() : [];
    const scale = parseFloat(editScaleRatio) || 1.0;

    const newEdges = edges.map((edge) => {
      if (edge.is_cross_floor) return edge;
      if (edge.start === index || edge.end === index) {
        if (!edge.isCustom && currentWallGrid && currentWallGrid.length > 0) {
          const sNode = newNodes[edge.start];
          const eNode = newNodes[edge.end];
          if (sNode && eNode) {
            const astar = findAStarPath(sNode, eNode, currentWallGrid, 8);
            if (astar) {
              const simplified = simplifyPath(astar);
              return {
                ...edge,
                pathPoints: simplified,
                weight: getPathLength(simplified, scale),
                needsRecalc: false,
              };
            }
          }
        }
        return { ...edge, needsRecalc: true };
      }
      return edge;
    });
    setEdges(newEdges);
  };

  // ── Properties Panel Handlers ───────────────────────────────────────────────
  const updateProperty = (field, value) => {
    if (selectedElement.type === 'node') {
      const newNodes = [...nodes];
      const updatedNode = { ...newNodes[selectedElement.index], [field]: value };

      if (updatedNode.ai_generated && updatedNode.review_status === 'PENDING') {
        updatedNode.review_status = 'MODIFIED';
      }

      newNodes[selectedElement.index] = updatedNode;

      let updatedEdges = [...edges];
      let emptyIntersectionCount = 0;

      if (field === 'allowed_roles') {
        const updatedNodeRoles = value || [];
        updatedEdges = edges.map((edge) => {
          if (
            edge.start === selectedElement.index ||
            (edge.end === selectedElement.index && !edge.is_cross_floor)
          ) {
            let otherRoles = [];
            if (edge.is_cross_floor) {
              const targetNode = globalNodes.find(
                (gn) => Number(gn.node_id) === Number(edge.target_node_id)
              );
              otherRoles = targetNode
                ? typeof targetNode.allowed_roles === 'string'
                  ? targetNode.allowed_roles.split(',').map(Number)
                  : targetNode.allowed_roles || []
                : [];
            } else {
              const otherNodeIndex =
                edge.start === selectedElement.index ? edge.end : edge.start;
              otherRoles = newNodes[otherNodeIndex]?.allowed_roles || [];
            }

            const intersection = updatedNodeRoles.filter((r) => otherRoles.includes(r));
            let isAccessible = edge.is_accessible;
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
      setIsDirty(true);
      if (emptyIntersectionCount > 0) {
        toast.info(
          `${emptyIntersectionCount} connected path(s) had no shared roles and were automatically disabled.`
        );
      }
    } else if (selectedElement.type === 'edge') {
      const newEdges = [...edges];
      newEdges[selectedElement.index] = {
        ...newEdges[selectedElement.index],
        [field]: value,
      };
      setEdges(newEdges);
      setIsDirty(true);
    }
  };

  const handleRoleToggle = (roleId) => {
    const element =
      selectedElement.type === 'node'
        ? nodes[selectedElement.index]
        : edges[selectedElement.index];
    const currentRoles = element.allowed_roles || [];
    const newRoles = currentRoles.includes(roleId)
      ? currentRoles.filter((id) => id !== roleId)
      : [...currentRoles, roleId];
    updateProperty('allowed_roles', newRoles);
  };

  // ── Transition Linker Handlers ──────────────────────────────────────────────
  const handleCreateTransition = () => {
    if (!transitionTargetId || !transitionWeight) {
      toast.error('Please select a target destination and specify a distance.');
      return;
    }

    const startNode = nodes[selectedElement.index];
    const startRoles = startNode?.allowed_roles || [];
    const targetNode = globalNodes.find(
      (gn) => Number(gn.node_id) === Number(transitionTargetId)
    );
    const targetRoles = targetNode
      ? typeof targetNode.allowed_roles === 'string'
        ? targetNode.allowed_roles.split(',').map(Number)
        : targetNode.allowed_roles || []
      : [];
    const intersection = startRoles.filter((r) => targetRoles.includes(r));

    const finalize = (isAccessible) => {
      setEdges((prev) => [
        ...prev,
        {
          edge_id: null,
          start: selectedElement.index,
          is_cross_floor: true,
          target_node_id: Number(transitionTargetId),
          weight: parseFloat(transitionWeight),
          is_bidirectional: transitionIsBidirectional,
          is_accessible: isAccessible,
          allowed_roles: intersection,
        },
      ]);
      setIsDirty(true);
      toast.success('Transition link created. Save the map to persist changes.');
    };

    if (intersection.length === 0) {
      confirmAction({
        title: 'No Shared Access Roles',
        message: 'The selected transition nodes do not share any campus roles.',
        impactNote: 'Continuing will create the link as disabled (DENY).',
        confirmLabel: 'Create Disabled Link',
        variant: 'info',
        onConfirm: () => finalize('DENY'),
      });
      return;
    }

    finalize(transitionIsAccessible ? 'ALLOW' : 'DENY');
  };

  const handleUpdateTransition = (existingIndex) => {
    if (!transitionWeight) {
      toast.error('Please specify a distance.');
      return;
    }

    const edge = edges[existingIndex];
    const startNode = nodes[selectedElement.index];
    const startRoles = startNode?.allowed_roles || [];
    const targetNode = globalNodes.find(
      (gn) => Number(gn.node_id) === Number(edge.target_node_id)
    );
    const targetRoles = targetNode
      ? typeof targetNode.allowed_roles === 'string'
        ? targetNode.allowed_roles.split(',').map(Number)
        : targetNode.allowed_roles || []
      : [];
    const intersection = startRoles.filter((r) => targetRoles.includes(r));

    const finalize = (isAccessible) => {
      const newEdges = [...edges];
      newEdges[existingIndex] = {
        ...newEdges[existingIndex],
        weight: parseFloat(transitionWeight),
        is_bidirectional: transitionIsBidirectional,
        is_accessible: isAccessible,
        allowed_roles: intersection,
      };
      setEdges(newEdges);
      setIsDirty(true);
      toast.success('Transition link updated. Save the map to persist changes.');
    };

    if (intersection.length === 0) {
      confirmAction({
        title: 'No Shared Access Roles',
        message: 'The selected transition nodes do not share any campus roles.',
        impactNote: 'Continuing will save the link as disabled (DENY).',
        confirmLabel: 'Update as Disabled',
        variant: 'info',
        onConfirm: () => finalize('DENY'),
      });
      return;
    }

    finalize(transitionIsAccessible ? 'ALLOW' : 'DENY');
  };

  const handleDeleteTransition = (existingIndex) => {
    confirmAction({
      title: 'Delete Transition Link?',
      message: 'Remove this cross-floor transition link? The node itself will be kept.',
      confirmLabel: 'Delete Link',
      variant: 'danger',
      onConfirm: () => {
        setEdges((prev) => prev.filter((_, idx) => idx !== existingIndex));
        setTransitionTargetId('');
        setTransitionWeight('10');
        setTransitionIsAccessible(true);
        setTransitionIsBidirectional(true);
        setIsDirty(true);
        toast.info('Transition link removed. Save the map to persist.');
      },
    });
  };

  // ── Edge A* Manipulation Handlers ───────────────────────────────────────────
  const triggerSelectedEdgeAStar = () => {
    if (selectedElement.type !== 'edge') return;
    const index = selectedElement.index;
    const edge = edges[index];
    const startNode = nodes[edge.start];
    const endNode = nodes[edge.end];

    const currentWallGrid = getWallGrid ? getWallGrid() : [];
    if (!startNode || !endNode || !currentWallGrid || currentWallGrid.length === 0) {
      toast.error('AI route cannot be calculated until the wall mask is loaded.');
      return;
    }

    const astar = findAStarPath(startNode, endNode, currentWallGrid, 8);
    if (astar) {
      const simplified = simplifyPath(astar);
      const newEdges = [...edges];
      newEdges[index] = {
        ...edge,
        pathPoints: simplified,
        customPathPoints: null,
        isCustom: false,
        weight: getPathLength(simplified, parseFloat(editScaleRatio) || 1.0),
      };
      setEdges(newEdges);
      setIsDirty(true);
      toast.success('Path re-routed around walls.');
    } else {
      toast.error('AI pathfinding could not navigate around walls. Path unchanged.');
    }
  };

  const resetSelectedEdgeToStraight = () => {
    if (selectedElement.type !== 'edge') return;
    const index = selectedElement.index;
    const edge = edges[index];
    const startNode = nodes[edge.start];
    const endNode = nodes[edge.end];
    const straightPoints = [
      { x: startNode.x, y: startNode.y },
      { x: endNode.x, y: endNode.y },
    ];
    const newEdges = [...edges];
    newEdges[index] = {
      ...edge,
      pathPoints: straightPoints,
      customPathPoints: straightPoints,
      isCustom: true,
      weight: getPathLength(straightPoints, parseFloat(editScaleRatio) || 1.0),
    };
    setEdges(newEdges);
    setIsDirty(true);
  };

  // ── AI Node Import ──────────────────────────────────────────────────────────
  const importAiNodes = (analysisResult) => {
    if (!analysisResult || !analysisResult.nodes) return;

    setAiAnalysisResult(analysisResult);

    const aiNodes = analysisResult.nodes.map((aiNode) => ({
      node_id: null,
      x: aiNode.x,
      y: aiNode.y,
      room_label: aiNode.room_label,
      node_type: aiNode.node_type || 'ROOM',
      is_accessible: aiNode.is_accessible || 'ALLOW',
      allowed_roles: aiNode.allowed_roles || [],
      ai_generated: true,
      ai_confidence: aiNode.ai_confidence,
      ai_source: aiNode.ai_source,
      review_status: aiNode.review_status || 'PENDING',
      source_room_id: aiNode.source_room_id,
      temp_id: aiNode.temp_id,
    }));

    setNodes((prev) => [...prev, ...aiNodes]);
    if (aiNodes.length > 0) setIsDirty(true);
  };

  const clearAiAnalysis = () => {
    setAiAnalysisResult(null);
    setNodes((prev) => prev.filter((n) => !(n.ai_generated && n.review_status === 'PENDING')));
    toast.info('Cleared unreviewed AI nodes.');
  };

  return {
    nodes,
    setNodes,
    edges,
    setEdges,
    isDirty,
    setIsDirty,
    showAllLabels,
    setShowAllLabels,
    appMode,
    setAppMode,
    mode,
    setMode,
    selectTool,
    selectedElement,
    setSelectedElement,
    hoveredNodeIndex,
    setHoveredNodeIndex,
    hoveredEdgeIndex,
    setHoveredEdgeIndex,
    hoveredHandleNode,
    setHoveredHandleNode,
    edgeDrawState,
    setEdgeDrawState,
    activeNodeTab,
    setActiveNodeTab,
    transitionTargetId,
    setTransitionTargetId,
    transitionWeight,
    setTransitionWeight,
    transitionIsAccessible,
    setTransitionIsAccessible,
    transitionIsBidirectional,
    setTransitionIsBidirectional,
    dimensions,
    stageScale,
    setStageScale,
    stageX,
    setStageX,
    stageY,
    setStageY,
    containerRef,
    stageRef,
    isDraggingStage,
    isDraggingControlPoint,
    drawPathStartNode,
    mouseDownPos,
    fileInputRef,
    aiAnalysisResult,
    pendingAiCount,
    activeObj,
    isTransitionNode,
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
