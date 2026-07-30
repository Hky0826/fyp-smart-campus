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
        <div className="bg-slate-950 text-slate-100 p-2.5 font-sans">
            <div className="grid grid-cols-1 xl:grid-cols-4 gap-2.5">
                {/* Column 1: Floorplan Management */}
                <div className="xl:col-span-1 flex flex-col gap-2.5">
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
                        nodes={mapEditor.nodes}
                        setNodes={mapEditor.setNodes}
                    />
                </div>

                {/* Column 2 & 3: Toolbar + Konva Canvas */}
                <div className="xl:col-span-2 flex flex-col gap-2 min-h-[420px]">
                    <Toolbar
                        mode={mapEditor.mode}
                        selectTool={mapEditor.selectTool}
                        currentFloorplanId={floorplanData.currentFloorplanId}
                        handleResetView={mapEditor.handleResetView}
                        navPanelOpen={navigation.navPanelOpen}
                        setNavPanelOpen={navigation.setNavPanelOpen}
                        notifPanelOpen={notificationHub.notifPanelOpen}
                        setNotifPanelOpen={notificationHub.setNotifPanelOpen}
                        handleSaveMapData={floorplanData.handleSaveMapData}
                        nodes={mapEditor.nodes}
                        edges={mapEditor.edges}
                    />

                    <div className="w-full h-[440px] min-h-[440px]" ref={mapEditor.containerRef}>
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
                    </div>
                </div>

                {/* Column 4: Side Panels */}
                <div className="xl:col-span-1 flex flex-col gap-3">
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
                    />

                    <NavigationPanel
                        navPanelOpen={navigation.navPanelOpen}
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

                    <NotificationPanel
                        notifPanelOpen={notificationHub.notifPanelOpen}
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

                    {!mapEditor.activeObj && !navigation.navPanelOpen && !notificationHub.notifPanelOpen && (
                        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 shadow-xl flex flex-col items-center justify-center text-center text-slate-500 py-8">
                            <span className="text-2xl mb-1">💡</span>
                            <p className="text-xs font-semibold text-slate-400 mb-0.5">Properties & Tools Panel</p>
                            <p className="text-[10px] text-slate-500 max-w-xs leading-normal">
                                Click <strong className="text-slate-300">Edit Properties</strong> in the toolbar and select a node or path to edit its attributes, or open <strong className="text-slate-300">Navigate</strong> / <strong className="text-slate-300">Notification Hub</strong>.
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
