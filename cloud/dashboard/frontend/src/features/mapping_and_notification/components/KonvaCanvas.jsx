import React from 'react';
import { Stage, Layer, Image as KonvaImage, Circle, Line, Text } from 'react-konva';
import { CANVAS_WIDTH, CANVAS_HEIGHT, TRANSITION_TYPES } from '../constants/mapConstants';

export function KonvaCanvas({
    imageObj,
    wallOverlayImage,
    showWallOverlay,
    dimensions,
    stageScale,
    stageX, setStageX,
    stageY, setStageY,
    stageRef,
    mode,
    nodes,
    edges,
    selectedElement,
    hoveredNodeIndex, setHoveredNodeIndex,
    hoveredEdgeIndex, setHoveredEdgeIndex,
    getClampedDragBounds,
    handleWheel,
    handleStageMouseDown,
    handleMapClick,
    handleNodeClick,
    handleEdgeClick,
    handleLineDblClick,
    handleControlPointDblClick,
    handleNodeDragMove,
    handleNodeDragEnd,
    navHighlight
}) {
    if (!imageObj) {
        return (
            <div className="w-full h-full flex flex-col items-center justify-center bg-slate-950/80 rounded-xl border border-dashed border-slate-800 text-slate-500 p-8 min-h-[400px]">
                <div className="w-16 h-16 rounded-full bg-slate-900 flex items-center justify-center mb-3 text-2xl animate-bounce">
                    🗺️
                </div>
                <h3 className="text-sm font-bold text-slate-300 mb-1">No Map Loaded</h3>
                <p className="text-xs text-slate-500 text-center max-w-xs">Select an existing floorplan or upload a new map image to begin editing.</p>
            </div>
        );
    }

    return (
        <div className="w-full h-full relative overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
            <Stage
                ref={stageRef}
                width={dimensions.width}
                height={dimensions.height}
                scaleX={stageScale}
                scaleY={stageScale}
                x={stageX}
                y={stageY}
                draggable={true}
                onWheel={handleWheel}
                onMouseDown={handleStageMouseDown}
                onDragEnd={e => {
                    if (e.target === e.target.getStage()) {
                        setStageX(e.target.x());
                        setStageY(e.target.y());
                    }
                }}
                onClick={handleMapClick}
                style={{
                    cursor: mode === 'add_nodes' ? 'crosshair' : (mode === 'delete_element' ? 'not-allowed' : 'default')
                }}
            >
                {/* Layer 1: Background, Overlay, Edges, Nodes */}
                <Layer>
                    {/* Floorplan Image */}
                    <KonvaImage
                        image={imageObj}
                        width={CANVAS_WIDTH}
                        height={CANVAS_HEIGHT}
                    />

                    {/* Wall Mask Overlay */}
                    {showWallOverlay && wallOverlayImage && (
                        <KonvaImage
                            image={wallOverlayImage}
                            width={CANVAS_WIDTH}
                            height={CANVAS_HEIGHT}
                            listening={false}
                            opacity={0.8}
                        />
                    )}

                    {/* Edges (Paths) */}
                    {edges.map((edge, idx) => {
                        if (edge.is_cross_floor) return null;
                        const startNode = nodes[edge.start];
                        const endNode   = nodes[edge.end];
                        if (!startNode || !endNode) return null;

                        const isSelected = selectedElement.type === 'edge' && selectedElement.index === idx;
                        const isHovered  = hoveredEdgeIndex === idx;

                        let strokeColor = '#3b82f6';
                        if (edge.is_accessible === 'DENY') strokeColor = '#475569';
                        if (isHovered) strokeColor = mode === 'delete_element' ? '#ef4444' : '#10b981';
                        if (isSelected) strokeColor = '#f59e0b';

                        const strokeWidth = isSelected ? 6 : (isHovered ? 5 : 4);

                        let points = [];
                        if (edge.pathPoints && edge.pathPoints.length >= 2) {
                            points = edge.pathPoints.flatMap(pt => [pt.x, pt.y]);
                        } else {
                            points = [startNode.x, startNode.y, endNode.x, endNode.y];
                        }

                        const midX = (startNode.x + endNode.x) / 2;
                        const midY = (startNode.y + endNode.y) / 2;

                        return (
                            <React.Fragment key={`edge-${idx}`}>
                                <Line
                                    points={points}
                                    stroke={strokeColor}
                                    strokeWidth={strokeWidth}
                                    hitStrokeWidth={22}
                                    lineCap="round"
                                    lineJoin="round"
                                    onClick={e => handleEdgeClick(idx, e)}
                                    onDblClick={e => handleLineDblClick(idx, e)}
                                    onMouseEnter={() => setHoveredEdgeIndex(idx)}
                                    onMouseLeave={() => setHoveredEdgeIndex(null)}
                                />
                                {isHovered && (
                                    <Text
                                        x={midX - 20}
                                        y={midY - 12}
                                        text={`${edge.weight || 0}m`}
                                        fontSize={11}
                                        fontStyle="bold"
                                        fill="#ffffff"
                                        padding={2}
                                        align="center"
                                        listening={false}
                                    />
                                )}
                            </React.Fragment>
                        );
                    })}

                    {/* Intermediate Control Points for Selected Edge */}
                    {selectedElement.type === 'edge' && mode === 'edit_props' && (() => {
                        const edge = edges[selectedElement.index];
                        if (!edge || !edge.pathPoints || edge.pathPoints.length <= 2) return null;

                        return edge.pathPoints.slice(1, -1).map((pt, ptIdx) => {
                            const actualIdx = ptIdx + 1;
                            return (
                                <Circle
                                    key={`cp-${selectedElement.index}-${actualIdx}`}
                                    x={pt.x}
                                    y={pt.y}
                                    radius={7}
                                    fill="#3b82f6"
                                    stroke="#ffffff"
                                    strokeWidth={2}
                                    draggable
                                    dragBoundFunc={getClampedDragBounds}
                                    onDblClick={e => handleControlPointDblClick(selectedElement.index, actualIdx, e)}
                                    onDragMove={e => {
                                        const newX = e.target.x();
                                        const newY = e.target.y();
                                        const newPoints = [...edge.pathPoints];
                                        newPoints[actualIdx] = { x: newX, y: newY };
                                        const newEdges = [...edges];
                                        newEdges[selectedElement.index] = {
                                            ...edge,
                                            pathPoints: newPoints,
                                            customPathPoints: newPoints,
                                            isCustom: true
                                        };
                                    }}
                                />
                            );
                        });
                    })()}

                    {/* Nodes */}
                    {nodes.map((node, idx) => {
                        const isSelected    = selectedElement.type === 'node' && selectedElement.index === idx;
                        const isHovered     = hoveredNodeIndex === idx;
                        const isTransition  = TRANSITION_TYPES.includes(node.node_type);

                        let fillColor = '#ef4444';
                        if (isTransition) fillColor = '#a855f7';
                        if (node.is_accessible === 'DENY') fillColor = '#64748b';
                        if (isHovered) fillColor = mode === 'delete_element' ? '#dc2626' : '#f97316';
                        if (isSelected) fillColor = '#f59e0b';

                        const radius = (mode === 'add_nodes' || mode === 'draw_paths' || mode === 'edit_props') ? 10 : 8;

                        return (
                            <React.Fragment key={`node-${idx}`}>
                                <Circle
                                    x={node.x}
                                    y={node.y}
                                    radius={radius}
                                    fill={fillColor}
                                    stroke={isTransition ? '#ffffff' : '#020617'}
                                    strokeWidth={isTransition ? 2.5 : 2}
                                    draggable={mode === 'edit_props' || mode === 'add_nodes' || mode === 'draw_paths'}
                                    dragBoundFunc={getClampedDragBounds}
                                    onClick={e => handleNodeClick(idx, e)}
                                    onDragMove={e => handleNodeDragMove(idx, e)}
                                    onDragEnd={e => handleNodeDragEnd(idx, e)}
                                    onMouseEnter={() => setHoveredNodeIndex(idx)}
                                    onMouseLeave={() => setHoveredNodeIndex(null)}
                                />
                                {(isHovered || isSelected) && (
                                    <Text
                                        x={node.x - 40}
                                        y={node.y + 12}
                                        width={80}
                                        text={node.room_label || `Node ${idx + 1}`}
                                        fontSize={10}
                                        fontStyle="bold"
                                        fill="#ffffff"
                                        align="center"
                                        listening={false}
                                    />
                                )}
                            </React.Fragment>
                        );
                    })}
                </Layer>

                {/* Layer 2: Navigation Route Highlight Overlay */}
                {navHighlight && (
                    <Layer listening={false}>
                        {/* Route Edges */}
                        {(navHighlight.edge_ids || []).map((edgeId, idx) => {
                            const edge = edges.find(e => e.edge_id === edgeId);
                            if (!edge || edge.is_cross_floor) return null;
                            const startNode = nodes[edge.start];
                            const endNode   = nodes[edge.end];
                            if (!startNode || !endNode) return null;

                            let points = [];
                            if (edge.pathPoints && edge.pathPoints.length >= 2) {
                                points = edge.pathPoints.flatMap(pt => [pt.x, pt.y]);
                            } else {
                                points = [startNode.x, startNode.y, endNode.x, endNode.y];
                            }

                            return (
                                <React.Fragment key={`route-edge-${idx}`}>
                                    <Line
                                        points={points}
                                        stroke="#14b8a6"
                                        strokeWidth={12}
                                        opacity={0.25}
                                        lineCap="round"
                                        lineJoin="round"
                                    />
                                    <Line
                                        points={points}
                                        stroke="#14b8a6"
                                        strokeWidth={5}
                                        dash={[10, 4]}
                                        opacity={0.9}
                                        lineCap="round"
                                        lineJoin="round"
                                    />
                                </React.Fragment>
                            );
                        })}

                        {/* Route Nodes */}
                        {(navHighlight.node_ids || []).map((nodeId, idx) => {
                            const node = nodes.find(n => n.node_id === nodeId);
                            if (!node) return null;

                            return (
                                <React.Fragment key={`route-node-${idx}`}>
                                    <Circle
                                        x={node.x}
                                        y={node.y}
                                        radius={17}
                                        fill="#14b8a6"
                                        opacity={0.18}
                                    />
                                    <Circle
                                        x={node.x}
                                        y={node.y}
                                        radius={12}
                                        stroke="#14b8a6"
                                        strokeWidth={2}
                                    />
                                </React.Fragment>
                            );
                        })}
                    </Layer>
                )}
            </Stage>
        </div>
    );
}
