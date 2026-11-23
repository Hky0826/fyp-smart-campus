import React, { useState, useRef, useEffect, useCallback } from 'react';

export function KioskMap({ mapData, routeHighlight, navResult }) {
    const svgRef = useRef(null);
    const [viewBox, setViewBox] = useState({ x: 0, y: 0, w: 800, h: 600 });
    const [isDragging, setIsDragging] = useState(false);
    const [lastPos, setLastPos] = useState({ x: 0, y: 0 });

    /** Convert screen pixels to SVG viewBox units */
    const screenToSvg = useCallback((screenDx, screenDy) => {
        const svg = svgRef.current;
        if (!svg) return { dx: screenDx, dy: screenDy };
        const rect = svg.getBoundingClientRect();
        return {
            dx: (screenDx / rect.width) * viewBox.w,
            dy: (screenDy / rect.height) * viewBox.h
        };
    }, [viewBox.w, viewBox.h]);

    const handleWheel = useCallback((e) => {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 1.1 : 0.9;
        const svg = svgRef.current;
        if (!svg) return;

        const rect = svg.getBoundingClientRect();
        const mx = ((e.clientX - rect.left) / rect.width) * viewBox.w + viewBox.x;
        const my = ((e.clientY - rect.top) / rect.height) * viewBox.h + viewBox.y;

        const newW = Math.min(Math.max(200, viewBox.w * factor), 1600);
        const newH = Math.min(Math.max(150, viewBox.h * factor), 1200);

        setViewBox({
            w: newW, h: newH,
            x: mx - (mx - viewBox.x) * (newW / viewBox.w),
            y: my - (my - viewBox.y) * (newH / viewBox.h)
        });
    }, [viewBox]);

    const handleMouseDown = (e) => {
        setIsDragging(true);
        setLastPos({ x: e.clientX, y: e.clientY });
    };

    const handleMouseMove = (e) => {
        if (!isDragging) return;
        const { dx, dy } = screenToSvg(e.clientX - lastPos.x, e.clientY - lastPos.y);
        setViewBox(prev => ({ ...prev, x: prev.x - dx, y: prev.y - dy }));
        setLastPos({ x: e.clientX, y: e.clientY });
    };

    const handleMouseUp = () => setIsDragging(false);

    useEffect(() => {
        const svg = svgRef.current;
        if (svg) {
            svg.addEventListener('wheel', handleWheel, { passive: false });
            return () => svg.removeEventListener('wheel', handleWheel);
        }
    }, [handleWheel]);

    const zoomIn = () => setViewBox(prev => {
        const nw = Math.max(200, prev.w * 0.8);
        const nh = Math.max(150, prev.h * 0.8);
        return { x: prev.x + (prev.w - nw) / 2, y: prev.y + (prev.h - nh) / 2, w: nw, h: nh };
    });
    const zoomOut = () => setViewBox(prev => {
        const nw = Math.min(1600, prev.w * 1.25);
        const nh = Math.min(1200, prev.h * 1.25);
        return { x: prev.x + (prev.w - nw) / 2, y: prev.y + (prev.h - nh) / 2, w: nw, h: nh };
    });
    const resetZoom = () => setViewBox({ x: 0, y: 0, w: 800, h: 600 });

    if (!mapData) return null;

    const { wall_grid, nodes = [], edges = [] } = mapData;
    const highlightEdges = new Set(routeHighlight?.edge_ids || []);
    
    let pathEdges = [];
    if (navResult && navResult.edges_traversed) {
        pathEdges = navResult.edges_traversed;
    }

    const startNode = navResult?.path?.[0];
    const endNode = navResult?.path?.[navResult.path.length - 1];

    const renderCustomPath = (edge, isHighlighted) => {
        if (!edge.custom_path) return null;
        let points = [];
        try {
            points = JSON.parse(edge.custom_path);
        } catch (e) {
            return null;
        }

        // Determine traversal direction
        let pathPoints = [...points];
        if (isHighlighted) {
            const traversed = pathEdges.find(e => e.edge_id === edge.edge_id);
            if (traversed && traversed.source_node_id !== traversed.from_node_id) {
                pathPoints.reverse();
            }
        }

        const pointString = pathPoints.map(p => `${p.x},${p.y}`).join(' ');

        if (isHighlighted) {
            return (
                <g key={`route-edge-${edge.edge_id}`}>
                    <polyline points={pointString} fill="none" stroke="#14b8a6" strokeWidth={10} opacity={0.2} strokeLinecap="round" strokeLinejoin="round" />
                    <polyline points={pointString} fill="none" stroke="#14b8a6" strokeWidth={4} opacity={0.9} strokeLinecap="round" strokeLinejoin="round" />
                    {renderArrows(pathPoints)}
                </g>
            );
        } else {
            return <polyline key={`edge-${edge.edge_id}`} points={pointString} fill="none" stroke="#334155" strokeWidth={1.5} opacity={0.3} />;
        }
    };

    const renderArrows = (points) => {
        const arrows = [];
        for (let i = 0; i < points.length - 1; i++) {
            const p1 = points[i];
            const p2 = points[i + 1];
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            
            if (dist > 30) {
                const angle = Math.atan2(dy, dx) * 180 / Math.PI;
                const mx = (p1.x + p2.x) / 2;
                const my = (p1.y + p2.y) / 2;
                
                arrows.push(
                    <g key={`arrow-${i}`} transform={`translate(${mx}, ${my}) rotate(${angle})`}>
                        <polygon points="-6,-5 6,0 -6,5" fill="#14b8a6" stroke="#fff" strokeWidth="1" />
                    </g>
                );
            }
        }
        return arrows;
    };

    const renderStraightEdge = (edge, isHighlighted) => {
        const s = nodes.find(n => n.node_id === edge.source_node_id);
        const d = nodes.find(n => n.node_id === edge.destination_node_id);
        if (!s || !d) return null;

        let p1 = { x: s.coord_x, y: s.coord_y };
        let p2 = { x: d.coord_x, y: d.coord_y };

        if (isHighlighted) {
            const traversed = pathEdges.find(e => e.edge_id === edge.edge_id);
            if (traversed && traversed.source_node_id !== traversed.from_node_id) {
                const temp = p1;
                p1 = p2;
                p2 = temp;
            }

            return (
                <g key={`route-edge-${edge.edge_id}`}>
                    <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="#14b8a6" strokeWidth={10} opacity={0.2} strokeLinecap="round" />
                    <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="#14b8a6" strokeWidth={4} opacity={0.9} strokeLinecap="round" />
                    {renderArrows([p1, p2])}
                </g>
            );
        } else {
            return <line key={`edge-${edge.edge_id}`} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="#334155" strokeWidth={1.5} opacity={0.3} />;
        }
    };

    const renderNode = (node) => {
        const x = node.coord_x;
        const y = node.coord_y;
        
        let shape = null;
        const isCorridor = node.node_type === 'CORRIDOR' || node.room_label?.toLowerCase().includes('corridor');
        const isRoute = routeHighlight?.node_ids?.includes(node.node_id);
        const isStartOrEnd = node.node_id === startNode?.node_id || node.node_id === endNode?.node_id;

        if (isCorridor) {
            shape = isRoute 
                ? <circle cx={x} cy={y} r={3} fill="#14b8a6" /> 
                : <circle cx={x} cy={y} r={1.5} fill="#334155" opacity={0.6} />;
        } else if (node.node_type === 'ELEVATOR') {
            shape = (
                <g>
                    <rect x={x - 6} y={y - 6} width={12} height={12} rx={2} fill="#8b5cf6" stroke="#c084fc" strokeWidth={isRoute ? 2 : 1} />
                    <text x={x} y={y + 3} fontSize={8} fill="#fff" textAnchor="middle">🛗</text>
                </g>
            );
        } else if (node.node_type === 'STAIRWELL') {
            shape = (
                <g>
                    <polygon points={`${x},${y - 7} ${x - 6},${y + 5} ${x + 6},${y + 5}`} fill="#8b5cf6" stroke="#c084fc" strokeWidth={isRoute ? 2 : 1} />
                    <text x={x} y={y + 3} fontSize={7} fill="#fff" textAnchor="middle">🪜</text>
                </g>
            );
        } else if (node.node_type === 'ENTRANCE') {
            shape = (
                <g>
                    <circle cx={x} cy={y} r={6} fill="#16a34a" stroke="#4ade80" strokeWidth={isRoute ? 2 : 1} />
                    <text x={x} y={y + 3} fontSize={7} fill="#fff" textAnchor="middle">🚪</text>
                </g>
            );
        } else if (node.node_type === 'FOOD') {
            shape = (
                <g>
                    <circle cx={x} cy={y} r={5.5} fill="#ea580c" stroke="#fb923c" strokeWidth={1} />
                    <text x={x} y={y + 3} fontSize={7} fill="#fff" textAnchor="middle">🍴</text>
                </g>
            );
        } else if (node.node_type === 'WASHROOM') {
            shape = (
                <g>
                    <circle cx={x} cy={y} r={5.5} fill="#0284c7" stroke="#38bdf8" strokeWidth={1} />
                    <text x={x} y={y + 2.5} fontSize={6} fontWeight="bold" fill="#fff" textAnchor="middle">WC</text>
                </g>
            );
        } else if (node.node_type === 'FACILITIES') {
            shape = <circle cx={x} cy={y} r={isRoute ? 6 : 4.5} fill={isRoute ? "#0d9488" : "#64748b"} stroke={isRoute ? "#2dd4bf" : "#94a3b8"} strokeWidth={isRoute ? 2 : 1} />;
        } else {
            shape = <circle cx={x} cy={y} r={isRoute ? 6 : 4.5} fill={isRoute ? "#0d9488" : "#475569"} stroke={isRoute ? "#2dd4bf" : "#64748b"} strokeWidth={isRoute ? 2 : 1} />;
        }

        return (
            <g key={`node-${node.node_id}`}>
                {shape}
                {!isCorridor && !isStartOrEnd && node.room_label && (
                    <text 
                        x={x} 
                        y={y + 13} 
                        fontSize={7.5} 
                        fontWeight="500"
                        fill={isRoute ? "#5eead4" : "#94a3b8"} 
                        textAnchor="middle"
                        paintOrder="stroke"
                        stroke="#0f172a"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                    >
                        {node.room_label}
                    </text>
                )}
            </g>
        );
    };

    const renderMarker = (node, isStart) => {
        if (!node) return null;
        // Check if node is on this map
        const localNode = nodes.find(n => n.node_id === node.node_id);
        if (!localNode) return null;

        const x = localNode.coord_x;
        const y = localNode.coord_y;
        const color = isStart ? '#14b8a6' : '#f59e0b';
        const pulseClass = isStart ? 'pulse-start' : 'pulse-dest';
        const roleTitle = isStart ? 'Start' : 'Destination';
        const bannerW = isStart ? 46 : 72;

        return (
            <g key={`marker-${isStart ? 'start' : 'end'}`} transform={`translate(${x}, ${y})`}>
                {/* Pulsing ring */}
                <circle className={pulseClass} r={18} fill={color} opacity={0.2} />
                <circle r={12} stroke={color} strokeWidth={2.5} fill="#0f172a" />
                <circle r={5} fill={color} />
                
                {/* Pin callout banner */}
                <g transform="translate(0, -22)">
                    <rect x={-bannerW / 2} y={-9} width={bannerW} height={18} fill="#0f172a" rx={5} stroke={color} strokeWidth={1.5} />
                    <text x={0} y={3.5} fontSize={8.5} fontWeight="bold" fill={color} textAnchor="middle">
                        {roleTitle}
                    </text>
                </g>
                <text 
                    x={0} 
                    y={25} 
                    fontSize={9} 
                    fontWeight="bold" 
                    fill="#fff" 
                    textAnchor="middle" 
                    paintOrder="stroke"
                    stroke="#0f172a"
                    strokeWidth="3"
                >
                    {localNode.room_label}
                </text>
            </g>
        );
    };

    const renderWallGrid = () => {
        if (!wall_grid || !wall_grid.grid) return null;
        const rects = [];
        const { grid, grid_scale } = wall_grid;
        
        for (let row = 0; row < grid.length; row++) {
            let col = 0;
            const rowLen = grid[row].length;
            while (col < rowLen) {
                if (grid[row][col] === 1) {
                    const startCol = col;
                    while (col < rowLen && grid[row][col] === 1) {
                        col++;
                    }
                    const span = col - startCol;
                    rects.push(
                        <rect 
                            key={`wall-${row}-${startCol}`} 
                            x={startCol * grid_scale} 
                            y={row * grid_scale} 
                            width={span * grid_scale} 
                            height={grid_scale} 
                            fill="#334155" 
                            opacity={0.85}
                            rx={1}
                        />
                    );
                } else {
                    col++;
                }
            }
        }
        return <g className="walls-layer">{rects}</g>;
    };

    return (
        <div 
            className="w-full h-full relative select-none overflow-hidden" 
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
        >
            <svg 
                ref={svgRef} 
                className="w-full h-full bg-[#0f172a]" 
                viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
                preserveAspectRatio="xMidYMid meet"
            >
                <defs>
                    <style>{`
                        @keyframes pulseGlow {
                            0% { r: 16px; opacity: 0.35; }
                            50% { r: 24px; opacity: 0.08; }
                            100% { r: 16px; opacity: 0.35; }
                        }
                        .pulse-start { animation: pulseGlow 2s infinite ease-in-out; }
                        .pulse-dest { animation: pulseGlow 2s infinite ease-in-out; animation-delay: 1s; }
                    `}</style>
                </defs>
                {renderWallGrid()}
                    
                    {edges.filter(e => !highlightEdges.has(e.edge_id)).map(e => e.custom_path ? renderCustomPath(e, false) : renderStraightEdge(e, false))}
                    
                    {edges.filter(e => highlightEdges.has(e.edge_id)).map(e => e.custom_path ? renderCustomPath(e, true) : renderStraightEdge(e, true))}
                    
                    {nodes.map(renderNode)}
                    
                    {renderMarker(startNode, true)}
                    {renderMarker(endNode, false)}
            </svg>
            
            <div className="absolute bottom-6 right-6 flex flex-col gap-2 bg-slate-900/80 p-1.5 rounded-lg border border-slate-700 backdrop-blur-sm shadow-lg">
                <button onClick={zoomIn} className="w-8 h-8 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-white rounded text-lg font-bold border border-slate-600 transition-colors">+</button>
                <button onClick={resetZoom} className="w-8 h-8 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-teal-400 rounded text-sm font-bold border border-slate-600 transition-colors">R</button>
                <button onClick={zoomOut} className="w-8 h-8 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-white rounded text-lg font-bold border border-slate-600 transition-colors">−</button>
            </div>
        </div>
    );
}
