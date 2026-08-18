/**
 * @file App.js
 * @description Main entry point for the Campus Navigation System admin dashboard.
 *
 * This component acts as the orchestrator. It imports domain-specific custom hooks
 * (auth, floorplan data, OpenCV processing, map editing, navigation, and notifications)
 * and passes their state/handlers down to dedicated presentational UI components.
 * 
 * The Konva canvas is retained here to act as the visual centerpiece.
 */

import React from 'react';
import { Stage, Layer, Circle, Line, Text, Image as KonvaImage } from 'react-konva';

// --- Custom Hooks ---
import { useAuth } from './hooks/useAuth';
import { useFloorplanData } from './hooks/useFloorplanData';
import { useMapEditor } from './hooks/useMapEditor';
import { useNavigation } from './hooks/useNavigation';
import { useNotificationHub } from './hooks/useNotificationHub';

// --- UI Components ---
import LoginScreen from './components/LoginScreen';
import { Header } from './components/Header';
import { MapManagerCard } from './components/MapManagerCard';
import { Toolbar } from './components/Toolbar';
import { PropertiesPanel } from './components/PropertiesPanel';
import { NavigationPanel } from './components/NavigationPanel';
import { NotificationPanel } from './components/NotificationPanel';

// --- Constants ---
import { TRANSITION_TYPES } from './constants/mapConstants';

function App() {
    // 1. Auth Hook
    const auth = useAuth({
        onLoginSuccess: () => floorplanData.fetchInitialData(),
        onLogout: () => {
            floorplanData.setCurrentFloorplanId(null);
            mapEditor.setAppMode('test');
        }
    });

    // We need to keep a local reference to the image object loaded by the floorplan hook
    // so OpenCV and Konva can render it.
    const [currentImageObj, setCurrentImageObj] = React.useState(null);

    // 2. Floorplan Data Hook
    const floorplanData = useFloorplanData({
        onFloorplanLoaded: ({ img, nodes, edges }) => {
            setCurrentImageObj(img);
            mapEditor.setNodes(nodes);
            mapEditor.setEdges(edges);
            mapEditor.setSelectedElement({ type: null, index: null });
            mapEditor.setHoveredNodeIndex(null);
            mapEditor.setHoveredEdgeIndex(null);
            mapEditor.setMode(''); // Clear any active tool, but preserve Edit/Test mode
        },
        onFloorplanCleared: () => {
            setCurrentImageObj(null);
            mapEditor.setNodes([]);
            mapEditor.setEdges([]);
            mapEditor.setMode(''); // Clear any active tool, but preserve Edit/Test mode
        },
        fileInputRef: null // Will be assigned shortly via mapEditor ref
    });

    // 3. Map Editor Hook (Core interaction state)
    const mapEditor = useMapEditor({
        rolesList: floorplanData.rolesList,
        globalNodes: floorplanData.globalNodes,
        getWallGrid: () => floorplanData.wallGrid || [],
        editScaleRatio: floorplanData.editScaleRatio,
        imageObj: currentImageObj
    });
    
    // Bind the file input ref now that it exists
    floorplanData.fileInputRef = mapEditor.fileInputRef;
    
    mapEditor.imageObj = currentImageObj;

    // 5. Navigation Tester Hook
    const navigation = useNavigation({
        currentFloorplanId: floorplanData.currentFloorplanId
    });

    // 6. Notification Hub Hook
    const notifications = useNotificationHub({
        token: auth.token,
        navStartId: navigation.navStartId,
        navEndId: navigation.navEndId,
        navRoleId: navigation.navRoleId,
        globalNodes: floorplanData.globalNodes,
        currentFloorplanId: floorplanData.currentFloorplanId,
        setNavResult: navigation.setNavResult,
        setNavHighlight: navigation.setNavHighlight
    });


    // ── AI Analyze Handler ─────────────────────────────────────────────────
    /**
     * Triggers the Phase 1 AI analysis and imports resulting nodes into the canvas.
     * Called when the admin clicks the "AI Analyze" button in the Toolbar.
     */
    const handleAiAnalyze = async () => {
        const result = await floorplanData.analyzeFloorplan();
        if (result) {
            mapEditor.importAiNodes(result);
        }
    };

    // ── Render ─────────────────────────────────────────────────────────────
    
    if (!auth.token) {
        return <LoginScreen {...auth} />;
    }

    return (
        <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-['Outfit'] antialiased">
            
            {/* Header / Topbar */}
            <Header 
                cvLoaded={true} 
                cvLoadingError={false} 
                adminName={auth.adminName} 
                handleLogout={auth.handleLogout} 
            />

            {/* Main Grid Workspace */}
            <main className="flex-1 grid grid-cols-1 xl:grid-cols-4 gap-3 p-3 overflow-hidden">
                
                {/* Left column: Controls & Map loading */}
                <section className="xl:col-span-1 flex flex-col gap-3">
                    <MapManagerCard 
                        {...floorplanData} 
                        nodes={mapEditor.nodes}
                        setNodes={mapEditor.setNodes}
                    />
                </section>

                {/* Center Workspace (Canvas and Toolbar) */}
                <section className="xl:col-span-2 flex flex-col gap-3">
                    <Toolbar 
                        appMode={mapEditor.appMode}
                        setAppMode={mapEditor.setAppMode}
                        mode={mapEditor.mode}
                        selectTool={mapEditor.selectTool}
                        currentFloorplanId={floorplanData.currentFloorplanId}
                        handleDeleteSelected={mapEditor.handleDeleteSelected}
                        navPanelOpen={navigation.navPanelOpen}
                        setNavPanelOpen={navigation.setNavPanelOpen}
                        notifPanelOpen={notifications.notifPanelOpen}
                        setNotifPanelOpen={notifications.setNotifPanelOpen}
                        handleSaveMapData={() => floorplanData.handleSaveMapData(mapEditor.nodes, mapEditor.edges)}
                        nodes={mapEditor.nodes}
                        edges={mapEditor.edges}
                        handleAiAnalyze={handleAiAnalyze}
                        isAnalyzing={floorplanData.isAnalyzing}
                    />

                    {/* Konva Stage Map Viewer */}
                    <div ref={mapEditor.containerRef} className="bg-slate-900 border border-slate-800 rounded-lg p-2 shadow-md flex justify-center items-center overflow-hidden min-h-[440px] w-full h-[460px] relative">
                        {!floorplanData.currentFloorplanId && (
                            <div className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm flex flex-col items-center justify-center rounded-2xl p-6 text-center z-10">
                                <svg className="w-16 h-16 text-slate-600 mb-4 animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
                                <h3 className="text-xl font-bold text-white mb-2">No Map Loaded</h3>
                                <p className="text-sm text-slate-400 max-w-sm">Please select an existing map from the dropdown list or upload a new floorplan image to get started.</p>
                            </div>
                        )}
                        
                        {/* Floating Canvas Controls */}
                        {floorplanData.currentFloorplanId && (
                            <div className="absolute bottom-4 right-4 flex flex-col gap-1.5 bg-slate-900/90 p-1.5 rounded-lg border border-slate-700/50 shadow-lg backdrop-blur-md z-20">
                                <button onClick={() => mapEditor.setStageScale(s => Math.min(s * 1.2, 5))} className="w-8 h-8 flex items-center justify-center text-slate-300 hover:text-white hover:bg-slate-800 rounded bg-slate-950/80 transition-colors cursor-pointer border border-slate-800" title="Zoom In">
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" /></svg>
                                </button>
                                <button onClick={() => mapEditor.setStageScale(s => Math.max(s / 1.2, 0.1))} className="w-8 h-8 flex items-center justify-center text-slate-300 hover:text-white hover:bg-slate-800 rounded bg-slate-950/80 transition-colors cursor-pointer border border-slate-800" title="Zoom Out">
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20 12H4" /></svg>
                                </button>
                                <button onClick={mapEditor.handleResetView} className="w-8 h-8 flex items-center justify-center text-slate-300 hover:text-white hover:bg-slate-800 rounded bg-slate-950/80 transition-colors cursor-pointer border border-slate-800" title="Reset View">
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" /></svg>
                                </button>
                            </div>
                        )}
                        
                        {floorplanData.currentFloorplanId && (
                            <Stage 
                                ref={mapEditor.stageRef}
                                width={mapEditor.dimensions.width} 
                                height={mapEditor.dimensions.height}
                                scaleX={mapEditor.stageScale}
                                scaleY={mapEditor.stageScale}
                                x={mapEditor.stageX}
                                y={mapEditor.stageY}
                                draggable={true}
                                onWheel={mapEditor.handleWheel}
                                onMouseDown={mapEditor.handleStageMouseDown}
                                onDragStart={(e) => {
                                    if (e.target === e.target.getStage()) {
                                        if (mapEditor.isDraggingStage) {
                                            mapEditor.isDraggingStage.current = true;
                                        }
                                    }
                                }}
                                onDragEnd={(e) => {
                                    if (e.target === e.target.getStage()) {
                                        mapEditor.setStageX(e.target.x());
                                        mapEditor.setStageY(e.target.y());
                                        if (mapEditor.isDraggingStage) {
                                            mapEditor.isDraggingStage.current = false;
                                        }
                                    }
                                }}
                                onClick={mapEditor.handleMapClick} 
                                onDblClick={mapEditor.handleMapDblClick}
                                className={`bg-slate-950 rounded-xl overflow-hidden shadow-inner ${
                                    (mapEditor.mode === 'add_nodes' || mapEditor.mode === 'draw_paths') ? 'cursor-crosshair' : (mapEditor.mode === 'delete_element' ? 'cursor-not-allowed' : 'cursor-default')
                                }`}
                            >
                                <Layer>
                                    {/* Floorplan Image */}
                                    {currentImageObj && <KonvaImage image={currentImageObj} width={800} height={600} />}
                                    
                                    {/* Persistent Wall Mask Layer */}
                                    {floorplanData.showWallOverlay && floorplanData.wallOverlayImage && (
                                        <KonvaImage image={floorplanData.wallOverlayImage} width={800} height={600} opacity={1} listening={false} />
                                    )}

                                    {/* Edge Preview Line */}
                                    {mapEditor.edgeDrawState && (
                                        <Line 
                                            points={[
                                                mapEditor.nodes[mapEditor.edgeDrawState.startNodeIndex].x,
                                                mapEditor.nodes[mapEditor.edgeDrawState.startNodeIndex].y,
                                                mapEditor.edgeDrawState.currentPos.x,
                                                mapEditor.edgeDrawState.currentPos.y
                                            ]} 
                                            stroke="#14b8a6" 
                                            strokeWidth={3} 
                                            dash={[5, 5]} 
                                            listening={false}
                                        />
                                    )}

                                    {mapEditor.edges.map((edge, i) => {
                                        const isSelected = mapEditor.selectedElement.type === 'edge' && mapEditor.selectedElement.index === i;
                                        if (edge.is_cross_floor) return null;

                                        let points = [];
                                        if (edge.pathPoints && edge.pathPoints.length >= 2) {
                                            points = edge.pathPoints.flatMap(p => [p.x, p.y]);
                                        } else {
                                            const startNode = mapEditor.nodes[edge.start];
                                            const endNode = mapEditor.nodes[edge.end];
                                            if (startNode && endNode) {
                                                points = [startNode.x, startNode.y, endNode.x, endNode.y];
                                            }
                                        }
                                        if (points.length < 4) return null;

                                        return (
                                            <React.Fragment key={`edge-${i}`}>
                                                <Line 
                                                    points={points} 
                                                    stroke={
                                                        isSelected 
                                                            ? "#f59e0b" // gold
                                                            : (mapEditor.hoveredEdgeIndex === i 
                                                                ? (mapEditor.mode === 'delete_element' ? "#ef4444" : (mapEditor.appMode === 'test' ? "#14b8a6" : "#10b981")) 
                                                                : (edge.is_accessible === 'DENY' ? "#475569" : "#3b82f6"))
                                                    } 
                                                    strokeWidth={isSelected ? 6 : 4} 
                                                    hitStrokeWidth={22} 
                                                    onMouseEnter={() => mapEditor.setHoveredEdgeIndex(i)} 
                                                    onMouseLeave={() => mapEditor.setHoveredEdgeIndex(null)} 
                                                    onClick={(e) => mapEditor.handleEdgeClick(i, e)} 
                                                    onTap={(e) => mapEditor.handleEdgeClick(i, e)}
                                                    onDblClick={(e) => mapEditor.handleLineDblClick(i, e)}
                                                />
                                                {mapEditor.hoveredEdgeIndex === i && (
                                                    <Text 
                                                        x={(points[0] + points[points.length - 2]) / 2 + 10} 
                                                        y={(points[1] + points[points.length - 1]) / 2 - 15} 
                                                        text={`${edge.weight}m`} 
                                                        fontSize={13} 
                                                        fill="#f8fafc" 
                                                        fontStyle="bold" 
                                                        padding={6} 
                                                        backgroundColor="rgba(15, 23, 42, 0.9)" 
                                                        cornerRadius={4}
                                                    />
                                                )}
                                            </React.Fragment>
                                        );
                                    })}

                                    {/* Draggable Control Points for Selected Edge */}
                                    {mapEditor.selectedElement.type === 'edge' && mapEditor.appMode === 'edit' && (
                                        mapEditor.edges[mapEditor.selectedElement.index]?.pathPoints?.map((pt, ptIdx) => {
                                            if (ptIdx === 0 || ptIdx === mapEditor.edges[mapEditor.selectedElement.index].pathPoints.length - 1) return null;

                                            return (
                                                <Circle
                                                    key={`ctrl-${mapEditor.selectedElement.index}-${ptIdx}`}
                                                    x={pt.x}
                                                    y={pt.y}
                                                    radius={8}
                                                    fill="#3b82f6"
                                                    stroke="#ffffff"
                                                    strokeWidth={2}
                                                    draggable
                                                    dragBoundFunc={mapEditor.getClampedDragBounds}
                                                    onDragStart={(e) => {
                                                        e.cancelBubble = true;
                                                        mapEditor.isDraggingControlPoint.current = true;
                                                        e.target.prevX = pt.x;
                                                        e.target.prevY = pt.y;
                                                    }}
                                                    onDragMove={(e) => {
                                                        e.cancelBubble = true;
                                                        const newPoints = [...mapEditor.edges[mapEditor.selectedElement.index].pathPoints];
                                                        newPoints[ptIdx] = { x: e.target.x(), y: e.target.y() };
                                                        const newEdges = [...mapEditor.edges];
                                                        // NOTE: Weight calculation is delayed to onDragEnd for performance
                                                        newEdges[mapEditor.selectedElement.index] = {
                                                            ...newEdges[mapEditor.selectedElement.index],
                                                            pathPoints: newPoints
                                                        };
                                                        mapEditor.setEdges(newEdges);
                                                    }}
                                                    onDragEnd={(e) => {
                                                        e.cancelBubble = true;
                                                        mapEditor.isDraggingControlPoint.current = false;
                                                        
                                                        const newX = e.target.x();
                                                        const newY = e.target.y();
                                                        
                                                        const edge = mapEditor.edges[mapEditor.selectedElement.index];
                                                        const finalPoints = [...edge.pathPoints];
                                                        finalPoints[ptIdx] = { x: newX, y: newY };
                                                        
                                                        // Collision check is handled by the visual representation or backend for now
                                                        
                                                        const newEdges = [...mapEditor.edges];
                                                        // Rough weight update (we leave full recalc to the hook if needed, but here we just update points)
                                                        newEdges[mapEditor.selectedElement.index] = {
                                                            ...newEdges[mapEditor.selectedElement.index],
                                                            pathPoints: finalPoints,
                                                            customPathPoints: finalPoints,
                                                            isCustom: true
                                                        };
                                                        mapEditor.setEdges(newEdges);
                                                    }}
                                                    onDblClick={(e) => mapEditor.handleControlPointDblClick(mapEditor.selectedElement.index, ptIdx, e)}
                                                />
                                            );
                                        })
                                    )}

                                    {/* Render Nodes — AI-generated nodes get a distinct teal dashed outer ring */}
                                    {mapEditor.nodes.map((node, i) => {
                                        const isSelected = mapEditor.selectedElement.type === 'node' && mapEditor.selectedElement.index === i;
                                        const isAiPending = node.ai_generated && node.review_status === 'PENDING';
                                        const isAiModified = node.ai_generated && node.review_status === 'MODIFIED';

                                        // Fill color logic
                                        let fillColor;
                                        if (isSelected) {
                                            fillColor = '#f59e0b'; // gold
                                        } else if (mapEditor.hoveredNodeIndex === i && mapEditor.mode === 'delete_element') {
                                            fillColor = '#ef4444'; // red
                                        } else if (mapEditor.hoveredNodeIndex === i) {
                                            fillColor = '#f97316';
                                        } else if (isAiPending) {
                                            fillColor = '#10b981'; // green — AI pending review
                                        } else if (node.is_accessible === 'DENY') {
                                            fillColor = '#64748b';
                                        } else if (TRANSITION_TYPES.includes(node.node_type)) {
                                            fillColor = '#a855f7';
                                        } else {
                                            fillColor = '#ef4444';
                                        }

                                        const nodeRadius = 8;

                                        return (
                                            <React.Fragment key={`node-${i}`}>
                                                {/* Outer dashed ring for AI pending nodes */}
                                                {isAiPending && (
                                                    <Circle
                                                        x={node.x}
                                                        y={node.y}
                                                        radius={nodeRadius + 7}
                                                        fill="transparent"
                                                        stroke="#2dd4bf"
                                                        strokeWidth={2}
                                                        dash={[5, 4]}
                                                        listening={false}
                                                    />
                                                )}
                                                {/* Visual indicator for Draw Edges: first-selected node */}
                                                {mapEditor.drawPathStartNode?.current === i && mapEditor.mode === 'draw_paths' && (
                                                    <Circle
                                                        x={node.x}
                                                        y={node.y}
                                                        radius={nodeRadius + 7}
                                                        fill="transparent"
                                                        stroke="#a855f7"
                                                        strokeWidth={2.5}
                                                        dash={[6, 3]}
                                                        listening={false}
                                                    />
                                                )}
                                                <Circle 
                                                    x={node.x} 
                                                    y={node.y} 
                                                    radius={nodeRadius}
                                                    fill={fillColor}
                                                    stroke={TRANSITION_TYPES.includes(node.node_type) ? "#ffffff" : "#0f172a"} 
                                                    strokeWidth={TRANSITION_TYPES.includes(node.node_type) ? 2.5 : 2} 
                                                    draggable={mapEditor.appMode === 'edit'} 
                                                    dragBoundFunc={mapEditor.appMode === 'edit' ? mapEditor.getClampedDragBounds : undefined} 
                                                    onDragMove={mapEditor.appMode === 'edit' ? (e) => mapEditor.handleNodeDragMove(i, e) : undefined}
                                                    onDragEnd={mapEditor.appMode === 'edit' ? (e) => mapEditor.handleNodeDragEnd(i, e) : undefined} 
                                                    onClick={(e) => mapEditor.handleNodeClick(i, e)} 
                                                    onTap={(e) => mapEditor.handleNodeClick(i, e)} 
                                                    onMouseEnter={() => mapEditor.setHoveredNodeIndex(i)} 
                                                    onMouseLeave={() => mapEditor.setHoveredNodeIndex(null)} 
                                                />
                                                {(mapEditor.hoveredNodeIndex === i || isSelected) && (
                                                    <Text 
                                                        x={node.x + 15} 
                                                        y={node.y - 25} 
                                                        text={node.room_label} 
                                                        fontSize={12} 
                                                        fill={isAiPending ? '#ef4444' : '#f8fafc'} 
                                                        fontStyle="bold" 
                                                        backgroundColor="rgba(15, 23, 42, 0.9)" 
                                                        padding={5} 
                                                        cornerRadius={4} 
                                                    />
                                                )}
                                                
                                                {/* Connection Handles */}
                                                {(mapEditor.hoveredNodeIndex === i || mapEditor.hoveredHandleNode === i) && mapEditor.appMode === 'edit' && (
                                                    ['top', 'right', 'bottom', 'left'].map(pos => {
                                                        const offset = 14;
                                                        let hx = node.x;
                                                        let hy = node.y;
                                                        if (pos === 'top') hy -= offset;
                                                        if (pos === 'bottom') hy += offset;
                                                        if (pos === 'left') hx -= offset;
                                                        if (pos === 'right') hx += offset;

                                                        return (
                                                            <Circle
                                                                key={`handle-${i}-${pos}`}
                                                                x={hx}
                                                                y={hy}
                                                                radius={5}
                                                                fill="#14b8a6"
                                                                stroke="#0f172a"
                                                                strokeWidth={1.5}
                                                                draggable
                                                                onMouseEnter={() => mapEditor.setHoveredHandleNode(i)}
                                                                onMouseLeave={() => mapEditor.setHoveredHandleNode(null)}
                                                                onDragStart={(e) => mapEditor.handleHandleDragStart(i, e)}
                                                                onDragMove={mapEditor.handleHandleDragMove}
                                                                onDragEnd={mapEditor.handleHandleDragEnd}
                                                            />
                                                        );
                                                    })
                                                )}
                                            </React.Fragment>
                                        );
                                    })}


                                </Layer>

                                {/* ── Navigation Route Highlight Overlay Layer ─────────────── */}
                                {navigation.navHighlight && (
                                    <Layer listening={false}>
                                        {mapEditor.edges.map((edge, i) => {
                                            if (edge.is_cross_floor || !edge.edge_id) return null;
                                            if (!navigation.navHighlight.edge_ids || !navigation.navHighlight.edge_ids.includes(edge.edge_id)) return null;
                                            let points = [];
                                            if (edge.pathPoints && edge.pathPoints.length >= 2) {
                                                points = edge.pathPoints.flatMap(p => [p.x, p.y]);
                                            } else {
                                                const sN = mapEditor.nodes[edge.start]; const eN = mapEditor.nodes[edge.end];
                                                if (sN && eN) points = [sN.x, sN.y, eN.x, eN.y];
                                            }
                                            if (points.length < 4) return null;
                                            return (
                                                <React.Fragment key={`nav-edge-${i}`}>
                                                    <Line points={points} stroke="#14b8a6" strokeWidth={12} opacity={0.25} lineCap="round" lineJoin="round" />
                                                    <Line points={points} stroke="#14b8a6" strokeWidth={5} opacity={0.9} lineCap="round" lineJoin="round" dash={[10, 4]} />
                                                </React.Fragment>
                                            );
                                        })}
                                        {mapEditor.nodes.map((node, i) => {
                                            if (!node.node_id) return null;
                                            if (!navigation.navHighlight.node_ids || !navigation.navHighlight.node_ids.includes(node.node_id)) return null;
                                            const isStart = navigation.navHighlight.node_ids[0] === node.node_id;
                                            const isEnd   = navigation.navHighlight.node_ids[navigation.navHighlight.node_ids.length - 1] === node.node_id;
                                            return (
                                                <React.Fragment key={`nav-node-${i}`}>
                                                    <Circle x={node.x} y={node.y} radius={17} fill="#14b8a6" opacity={0.18} />
                                                    <Circle x={node.x} y={node.y} radius={12} fill="transparent" stroke="#14b8a6" strokeWidth={2.5} opacity={0.9} />
                                                    {(isStart || isEnd) && (
                                                        <Circle x={node.x} y={node.y} radius={6} fill={isEnd ? '#f59e0b' : '#14b8a6'} opacity={1} />
                                                    )}
                                                </React.Fragment>
                                            );
                                        })}
                                    </Layer>
                                )}
                            </Stage>
                        )}
                    </div>
                </section>

                {/* Right column: Properties & Transitions */}
                <section className="xl:col-span-1 flex flex-col gap-4">
                    <PropertiesPanel 
                        {...mapEditor} 
                        handleDeleteSelected={mapEditor.handleDeleteSelected}
                        rolesList={floorplanData.rolesList}
                        globalNodes={floorplanData.globalNodes}
                        currentFloorplanId={floorplanData.currentFloorplanId}
                        currentBuildingName={floorplanData.editBuildingName}
                        currentFloorLevel={floorplanData.editFloorLevel}
                    />

                    <NavigationPanel 
                        {...navigation}
                        rolesList={floorplanData.rolesList}
                        globalNodes={floorplanData.globalNodes}
                        setNotifVisitorId={notifications.setNotifVisitorId}
                        setNotifVisitorEmail={notifications.setNotifVisitorEmail}
                        setNotifMessage={notifications.setNotifMessage}
                        setIsAutoMessage={notifications.setIsAutoMessage}
                    />

                    <NotificationPanel 
                        {...notifications}
                        navStartId={navigation.navStartId} setNavStartId={navigation.setNavStartId}
                        navEndId={navigation.navEndId} setNavEndId={navigation.setNavEndId}
                        navRoleId={navigation.navRoleId} setNavRoleId={navigation.setNavRoleId}
                        globalNodes={floorplanData.globalNodes}
                        rolesList={floorplanData.rolesList}
                    />
                    
                    {!mapEditor.activeObj && !navigation.navPanelOpen && !notifications.notifPanelOpen && (
                        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 shadow-xl flex flex-col items-center justify-center text-center py-6">
                            <div className="w-8 h-8 rounded-lg bg-slate-950 flex items-center justify-center mb-2 text-slate-600 border border-slate-850">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                            </div>
                            <h4 className="text-xs font-bold text-white mb-0.5">Properties Panel</h4>
                            <p className="text-[10px] text-slate-500 max-w-[180px]">Select a node or path on the map to view and modify its details.</p>
                        </div>
                    )}
                </section>
            </main>
        </div>
    );
}

export default App;