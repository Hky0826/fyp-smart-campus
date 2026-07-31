import React, { useState, useEffect } from 'react';
import { useFloorplanData } from './hooks/useFloorplanData';
import { useMapEditor } from './hooks/useMapEditor';
import { useNavigation } from './hooks/useNavigation';
import { useNotificationHub } from './hooks/useNotificationHub';

import { Toolbar } from './components/Toolbar';
import { MapManagerCard } from './components/MapManagerCard';
import { PropertiesPanel } from './components/PropertiesPanel';
import { NavigationPanel } from './components/NavigationPanel';
import { NotificationPanel } from './components/NotificationPanel';
import { KonvaCanvas } from './components/KonvaCanvas';

export default function MappingNotificationPage() {
    const [currentImageObj, setCurrentImageObj] = useState(null);
    const [activeDrawerTab, setActiveDrawerTab] = useState('none'); // 'none', 'route', 'notif'

    const floorplanData = useFloorplanData({
        onFloorplanLoaded: ({ img, nodes, edges }) => {
            setCurrentImageObj(img);
            mapEditor.setNodes(nodes);
            mapEditor.setEdges(edges);
            mapEditor.setSelectedElement({ type: null, index: null });
        },
        onFloorplanCleared: () => {
            setCurrentImageObj(null);
            mapEditor.setNodes([]);
            mapEditor.setEdges([]);
            mapEditor.setSelectedElement({ type: null, index: null });
            mapEditor.setMode('');
        },
        onUploadSuccess: () => {
            floorplanData.fetchInitialData();
        },
        fileInputRef: null
    });

    const mapEditor = useMapEditor({
        rolesList: floorplanData.rolesList,
        globalNodes: floorplanData.globalNodes,
        getWallGrid: () => floorplanData.wallGrid,
        editScaleRatio: floorplanData.editScaleRatio,
        imageObj: currentImageObj
    });

    const navigation = useNavigation({
        currentFloorplanId: floorplanData.currentFloorplanId
    });

    const notificationHub = useNotificationHub({
        navStartId: navigation.navStartId,
        navEndId: navigation.navEndId,
        navRoleId: navigation.navRoleId,
        globalNodes: floorplanData.globalNodes,
        currentFloorplanId: floorplanData.currentFloorplanId,
        setNavResult: navigation.setNavResult,
        setNavHighlight: navigation.setNavHighlight
    });

    useEffect(() => {
        floorplanData.fetchInitialData();
    }, []);

    const currentFp = floorplanData.floorplansList.find(
        f => String(f.floorplan_id) === String(floorplanData.currentFloorplanId)
    );
    const currentBuildingName = currentFp ? currentFp.building_name : '';
    const currentFloorLevel = currentFp ? currentFp.floor_level : '';

    return (
        <div className="bg-[#0B0F19] min-h-screen text-slate-100 p-2.5 font-sans flex flex-col gap-2 relative">
            {/* Inline Top Header Bar */}
            <div className="flex flex-row justify-between items-center gap-2 pb-1.5 border-b border-slate-800/60">
                <div className="flex items-center gap-2">
                    <h1 className="text-sm font-extrabold text-white tracking-tight">
                        Campus Map & Notifications
                    </h1>
                    <span className="hidden sm:inline-block text-[9px] text-slate-400 border-l border-slate-800 pl-2">
                        Interactive floorplan editor, wall detection & route testing
                    </span>
                </div>
                <div className="flex items-center gap-1.5 bg-slate-900/80 border border-slate-800 px-2 py-0.5 rounded-lg">
                    <span className="text-[8.5px] font-bold text-slate-400 tracking-wider">FLOORPLAN:</span>
                    <select 
                        onChange={floorplanData.loadFloorplanData} 
                        className="bg-slate-950 border border-slate-800 rounded px-1.5 py-0.5 text-[9.5px] text-white focus:outline-none focus:border-teal-500 cursor-pointer h-5.5 font-medium" 
                        value={floorplanData.currentFloorplanId || ""}
                    >
                        <option value="" disabled>-- Select Floorplan --</option>
                        {(floorplanData.floorplansList || []).map(fp => ( 
                            <option key={fp.floorplan_id} value={fp.floorplan_id}>
                                {fp.building_name || 'Building'} - Floor {fp.floor_level}
                            </option> 
                        ))}
                    </select>
                </div>
            </div>

            {/* Side-by-Side Flex Layout (Works at ANY iframe width, including expanded sidebar) */}
            <div className="flex flex-row gap-2.5 items-start min-w-0 w-full relative">
                {/* Left Controls Sidebar (240px width) */}
                <div className="w-[240px] shrink-0 flex flex-col gap-2">
                    <MapManagerCard
                        buildingsList={floorplanData.buildingsList}
                        selectedBuildingId={floorplanData.selectedBuildingId}
                        setSelectedBuildingId={floorplanData.setSelectedBuildingId}
                        newBuildingName={floorplanData.newBuildingName}
                        setNewBuildingName={floorplanData.setNewBuildingName}
                        handleCreateBuildingInline={floorplanData.handleCreateBuildingInline}
                        floorLevel={floorplanData.floorLevel}
                        setFloorLevel={floorplanData.setFloorLevel}
                        scaleRatio={floorplanData.scaleRatio}
                        setScaleRatio={floorplanData.setScaleRatio}
                        fileInputRef={mapEditor.fileInputRef}
                        handleImageUpload={floorplanData.handleImageUpload}
                        isUploading={floorplanData.isUploading}
                        floorplansList={floorplanData.floorplansList}
                        currentFloorplanId={floorplanData.currentFloorplanId}
                        loadFloorplanData={floorplanData.loadFloorplanData}
                        editBuildingName={floorplanData.editBuildingName}
                        setEditBuildingName={floorplanData.setEditBuildingName}
                        editFloorLevel={floorplanData.editFloorLevel}
                        setEditFloorLevel={floorplanData.setEditFloorLevel}
                        editScaleRatio={floorplanData.editScaleRatio}
                        setEditScaleRatio={floorplanData.setEditScaleRatio}
                        handleUpdateFloorplan={floorplanData.handleUpdateFloorplan}
                        handleDeleteMap={floorplanData.handleDeleteMap}
                        wallSensitivity={floorplanData.wallSensitivity}
                        setWallSensitivity={floorplanData.setWallSensitivity}
                        showWallOverlay={floorplanData.showWallOverlay}
                        setShowWallOverlay={floorplanData.setShowWallOverlay}
                        fetchWallMask={floorplanData.fetchWallMask}
                        isFetchingWallMask={floorplanData.isFetchingWallMask}
                        mode={mapEditor.mode}
                        selectTool={mapEditor.selectTool}
                        handleSaveMapData={floorplanData.handleSaveMapData}
                        nodes={mapEditor.nodes}
                        edges={mapEditor.edges}
                    />

                    {/* Quick Action Drawers */}
                    <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-2 shadow-xl flex flex-col gap-1.5">
                        <span className="text-[8.5px] font-bold text-slate-400 uppercase tracking-wider">TOOLS & TESTING</span>
                        <div className="flex gap-1">
                            <button
                                type="button"
                                onClick={() => setActiveDrawerTab(activeDrawerTab === 'route' ? 'none' : 'route')}
                                className={`flex-1 py-1 rounded-md text-[9px] font-bold transition-all cursor-pointer border flex items-center justify-center gap-1 ${
                                    activeDrawerTab === 'route'
                                        ? 'bg-teal-600 border-teal-500 text-white shadow-md'
                                        : 'bg-slate-950 border-slate-800 text-slate-300 hover:text-white'
                                }`}
                            >
                                🧭 Route
                            </button>
                            <button
                                type="button"
                                onClick={() => setActiveDrawerTab(activeDrawerTab === 'notif' ? 'none' : 'notif')}
                                className={`flex-1 py-1 rounded-md text-[9px] font-bold transition-all cursor-pointer border flex items-center justify-center gap-1 ${
                                    activeDrawerTab === 'notif'
                                        ? 'bg-indigo-600 border-indigo-500 text-white shadow-md'
                                        : 'bg-slate-950 border-slate-800 text-slate-300 hover:text-white'
                                }`}
                            >
                                🔔 Notif
                            </button>
                        </div>
                    </div>
                </div>

                {/* Right Main Column (flex-1) */}
                <div className="flex-1 min-w-0 flex flex-col gap-1">
                    <div className="w-full h-[480px] min-h-[480px] bg-[#0A0D14] border border-slate-800/80 rounded-xl overflow-hidden shadow-2xl relative" ref={mapEditor.containerRef}>
                        <KonvaCanvas
                            imageObj={currentImageObj}
                            wallOverlayImage={floorplanData.wallOverlayImage}
                            showWallOverlay={floorplanData.showWallOverlay}
                            dimensions={mapEditor.dimensions}
                            stageScale={mapEditor.stageScale}
                            stageX={mapEditor.stageX}
                            setStageX={mapEditor.setStageX}
                            stageY={mapEditor.stageY}
                            setStageY={mapEditor.setStageY}
                            stageRef={mapEditor.stageRef}
                            mode={mapEditor.mode}
                            nodes={mapEditor.nodes}
                            edges={mapEditor.edges}
                            selectedElement={mapEditor.selectedElement}
                            hoveredNodeIndex={mapEditor.hoveredNodeIndex}
                            setHoveredNodeIndex={mapEditor.setHoveredNodeIndex}
                            hoveredEdgeIndex={mapEditor.hoveredEdgeIndex}
                            setHoveredEdgeIndex={mapEditor.setHoveredEdgeIndex}
                            getClampedDragBounds={mapEditor.getClampedDragBounds}
                            handleWheel={mapEditor.handleWheel}
                            handleStageMouseDown={mapEditor.handleStageMouseDown}
                            handleMapClick={mapEditor.handleMapClick}
                            handleNodeClick={mapEditor.handleNodeClick}
                            handleEdgeClick={mapEditor.handleEdgeClick}
                            handleLineDblClick={mapEditor.handleLineDblClick}
                            handleControlPointDblClick={mapEditor.handleControlPointDblClick}
                            handleNodeDragMove={mapEditor.handleNodeDragMove}
                            handleNodeDragEnd={mapEditor.handleNodeDragEnd}
                            navHighlight={navigation.navHighlight}
                        />

                        {/* Floating Properties Overlay Panel (Appears when Node/Edge is clicked) */}
                        {mapEditor.activeObj && (
                            <div className="absolute top-3 right-3 w-[280px] z-30 shadow-2xl">
                                <PropertiesPanel
                                    mode={mapEditor.mode}
                                    selectedElement={mapEditor.selectedElement}
                                    setSelectedElement={mapEditor.setSelectedElement}
                                    activeObj={mapEditor.activeObj}
                                    isTransitionNode={mapEditor.isTransitionNode}
                                    activeNodeTab={mapEditor.activeNodeTab}
                                    setActiveNodeTab={mapEditor.setActiveNodeTab}
                                    updateProperty={mapEditor.updateProperty}
                                    handleRoleToggle={mapEditor.handleRoleToggle}
                                    rolesList={floorplanData.rolesList}
                                    edges={mapEditor.edges}
                                    nodes={mapEditor.nodes}
                                    globalNodes={floorplanData.globalNodes}
                                    currentFloorplanId={floorplanData.currentFloorplanId}
                                    transitionTargetId={mapEditor.transitionTargetId}
                                    setTransitionTargetId={mapEditor.setTransitionTargetId}
                                    transitionWeight={mapEditor.transitionWeight}
                                    setTransitionWeight={mapEditor.setTransitionWeight}
                                    transitionIsAccessible={mapEditor.transitionIsAccessible}
                                    setTransitionIsAccessible={mapEditor.setTransitionIsAccessible}
                                    transitionIsBidirectional={mapEditor.transitionIsBidirectional}
                                    setTransitionIsBidirectional={mapEditor.setTransitionIsBidirectional}
                                    currentBuildingName={currentBuildingName}
                                    currentFloorLevel={currentFloorLevel}
                                    handleUpdateTransition={mapEditor.handleUpdateTransition}
                                    handleDeleteTransition={mapEditor.handleDeleteTransition}
                                    handleCreateTransition={mapEditor.handleCreateTransition}
                                    triggerSelectedEdgeAStar={mapEditor.triggerSelectedEdgeAStar}
                                    resetSelectedEdgeToStraight={mapEditor.resetSelectedEdgeToStraight}
                                    handleDeleteSelectedElement={mapEditor.handleDeleteSelectedElement}
                                />
                            </div>
                        )}
                    </div>

                    <div className="text-center">
                        <span className="text-[9.5px] text-slate-400 font-medium bg-slate-900/60 px-2.5 py-0.5 rounded-full border border-slate-800/60 inline-block">
                            ✨ Click elements on canvas to edit properties, or drag nodes to move them.
                        </span>
                    </div>
                </div>
            </div>

            {/* Collapsible Drawer for Route Preview / Notifications */}
            {activeDrawerTab !== 'none' && (
                <div className="fixed inset-y-0 right-0 w-[340px] bg-[#111827] border-l border-slate-800 shadow-2xl p-4 z-40 overflow-y-auto flex flex-col gap-3">
                    <div className="flex justify-between items-center border-b border-slate-800 pb-2">
                        <h3 className="text-xs font-bold text-white flex items-center gap-1.5">
                            {activeDrawerTab === 'route' ? '🧭 Admin Route Preview' : '🔔 Notification Hub & Audit Log'}
                        </h3>
                        <button
                            type="button"
                            onClick={() => setActiveDrawerTab('none')}
                            className="text-[10px] text-slate-400 hover:text-white font-bold bg-slate-900 px-2 py-0.5 rounded border border-slate-700 cursor-pointer"
                        >
                            Close ✖
                        </button>
                    </div>

                    {activeDrawerTab === 'route' && (
                        <NavigationPanel
                            navPanelOpen={true}
                            navResult={navigation.navResult}
                            setNavResult={navigation.setNavResult}
                            setNavHighlight={navigation.setNavHighlight}
                            navError={navigation.navError}
                            setNavError={navigation.setNavError}
                            navStartId={navigation.navStartId}
                            setNavStartId={navigation.setNavStartId}
                            navEndId={navigation.navEndId}
                            setNavEndId={navigation.setNavEndId}
                            navRoleId={navigation.navRoleId}
                            setNavRoleId={navigation.setNavRoleId}
                            globalNodes={floorplanData.globalNodes}
                            rolesList={floorplanData.rolesList}
                            handleRunNavigation={navigation.handleRunNavigation}
                            navLoading={navigation.navLoading}
                            setNotifVisitorId={notificationHub.setNotifVisitorId}
                            setNotifVisitorEmail={notificationHub.setNotifVisitorEmail}
                            setNotifMessage={notificationHub.setNotifMessage}
                            setIsAutoMessage={notificationHub.setIsAutoMessage}
                        />
                    )}

                    {activeDrawerTab === 'notif' && (
                        <NotificationPanel
                            notifPanelOpen={true}
                            navStartId={navigation.navStartId}
                            setNavStartId={navigation.setNavStartId}
                            navEndId={navigation.navEndId}
                            setNavEndId={navigation.setNavEndId}
                            navRoleId={navigation.navRoleId}
                            setNavRoleId={navigation.setNavRoleId}
                            globalNodes={floorplanData.globalNodes}
                            rolesList={floorplanData.rolesList}
                            notifUsers={notificationHub.notifUsers}
                            notifTargetHostId={notificationHub.notifTargetHostId}
                            setNotifTargetHostId={notificationHub.setNotifTargetHostId}
                            notifVisitorId={notificationHub.notifVisitorId}
                            setNotifVisitorId={notificationHub.setNotifVisitorId}
                            notifEventType={notificationHub.notifEventType}
                            setNotifEventType={notificationHub.setNotifEventType}
                            notifMessage={notificationHub.notifMessage}
                            setNotifMessage={notificationHub.setNotifMessage}
                            setIsAutoMessage={notificationHub.setIsAutoMessage}
                            emailDeliveryMode={notificationHub.emailDeliveryMode}
                            setEmailDeliveryMode={notificationHub.setEmailDeliveryMode}
                            handleGenerateRouteAndNotify={notificationHub.handleGenerateRouteAndNotify}
                            notifTestLoading={notificationHub.notifTestLoading}
                            notifTestError={notificationHub.notifTestError}
                            notifTestResult={notificationHub.notifTestResult}
                            fetchNotifData={notificationHub.fetchNotifData}
                            notifLogLoading={notificationHub.notifLogLoading}
                            notifLog={notificationHub.notifLog}
                        />
                    )}
                </div>
            )}
        </div>
    );
}
