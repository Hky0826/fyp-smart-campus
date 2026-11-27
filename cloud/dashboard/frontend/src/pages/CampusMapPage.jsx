/**
 * @file CampusMapPage.jsx
 * @description Fully integrated Campus Map Studio inside the Smart Campus Console.
 * Uses native AuthProvider, ThemeProvider, ToastProvider, ConfirmDialog, and cloudApi.
 * Preserves 100% of map editing, AI wall/room detection, RBAC, transitions, route testing,
 * and notification hub features in a full-bleed CAD/GIS workspace.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Stage, Layer, Circle, Line, Text, Rect, Group, Image as KonvaImage } from 'react-konva';
import {
  CheckCheck,
  Compass,
  Eye,
  EyeOff,
  HelpCircle,
  Link2,
  Loader2,
  MapPin,
  Maximize2,
  Minus,
  MousePointer2,
  Plus,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react';

import { useAuthSession } from '../providers/AuthProvider';
import { useTheme } from '../providers/ThemeProvider';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';

import { useFloorplanData } from '../hooks/useFloorplanData';
import { useMapEditor } from '../hooks/useMapEditor';
import { useNavigation } from '../hooks/useNavigation';
import { useNotificationHub } from '../hooks/useNotificationHub';

import { MapManagerCard } from '../components/MapManagerCard';
import { Toolbar } from '../components/Toolbar';
import { PropertiesPanel } from '../components/PropertiesPanel';
import { NavigationPanel } from '../components/NavigationPanel';
import { NotificationPanel } from '../components/NotificationPanel';

import { TRANSITION_TYPES, CANVAS_WIDTH, CANVAS_HEIGHT } from '../constants/mapConstants';

export default function CampusMapPage() {
  const { isAuthenticated } = useAuthSession();
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  const [currentImageObj, setCurrentImageObj] = useState(null);
  const [leftDrawerOpen, setLeftDrawerOpen] = useState(false);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const [wallPopoverOpen, setWallPopoverOpen] = useState(false);
  const [confirmState, setConfirmState] = useState({ open: false });

  const fileInputRef = React.useRef(null);

  const requestConfirm = useCallback((config) => {
    setConfirmState({ ...config, open: true });
  }, []);

  const closeConfirm = useCallback(() => {
    setConfirmState((prev) => ({ ...prev, open: false }));
  }, []);

  // 1. Floorplan Data Hook
  const floorplanData = useFloorplanData({
    isAuthenticated,
    requestConfirm,
    onFloorplanLoaded: ({ img, nodes, edges }) => {
      setCurrentImageObj(img);
      mapEditor.setNodes(nodes);
      mapEditor.setEdges(edges);
      mapEditor.resetHistory();
      mapEditor.setIsDirty(false);
      mapEditor.setSelectedElement({ type: null, index: null });
      mapEditor.setHoveredNodeIndex(null);
      mapEditor.setHoveredEdgeIndex(null);
      mapEditor.setMode('');
    },
    onFloorplanCleared: () => {
      setCurrentImageObj(null);
      mapEditor.setNodes([]);
      mapEditor.setEdges([]);
      mapEditor.resetHistory();
      mapEditor.setIsDirty(false);
      mapEditor.setMode('');
    },
    fileInputRef,
  });

  // 2. Map Editor Hook
  const mapEditor = useMapEditor({
    rolesList: floorplanData.rolesList,
    globalNodes: floorplanData.globalNodes,
    getWallGrid: () => floorplanData.wallGrid || [],
    editScaleRatio: floorplanData.editScaleRatio,
    imageObj: currentImageObj,
    fileInputRef,
    requestConfirm,
  });

  // 3. Navigation Tester Hook
  const navigation = useNavigation({
    currentFloorplanId: floorplanData.currentFloorplanId,
  });

  // 4. Notification Hub Hook
  const notifications = useNotificationHub({
    isAuthenticated,
    navStartId: navigation.navStartId,
    navEndId: navigation.navEndId,
    navRoleId: navigation.navRoleId,
    globalNodes: floorplanData.globalNodes,
    currentFloorplanId: floorplanData.currentFloorplanId,
    setNavResult: navigation.setNavResult,
    setNavHighlight: navigation.setNavHighlight,
  });

  // Ctrl+S shortcut to save map
  useEffect(() => {
    const onKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        if (floorplanData.currentFloorplanId && mapEditor.appMode === 'edit') {
          e.preventDefault();
          floorplanData.handleSaveMapData(mapEditor.nodes, mapEditor.edges);
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [floorplanData, mapEditor.appMode, mapEditor.nodes, mapEditor.edges]);

  const handleAiAnalyze = async () => {
    const result = await floorplanData.analyzeFloorplan();
    if (result) {
      mapEditor.importAiNodes(result);
    }
  };

  const activeFloorplanLabel = floorplanData.currentFloorplanId
    ? `${floorplanData.editBuildingName} — Floor ${floorplanData.editFloorLevel}`
    : '';

  const showRightInspector =
    Boolean(mapEditor.activeObj) || navigation.navPanelOpen || notifications.notifPanelOpen;

  const zoomPercent = Math.round(mapEditor.stageScale * 100);

  return (
    <div className="h-[calc(100vh-4rem)] w-full flex flex-col overflow-hidden bg-slate-100 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
      {/* Unified Top Command Bar */}
      <Toolbar
        appMode={mapEditor.appMode}
        setAppMode={mapEditor.setAppMode}
        currentFloorplanId={floorplanData.currentFloorplanId}
        floorplansList={floorplanData.floorplansList}
        loadFloorplanData={floorplanData.loadFloorplanData}
        setUploadModalOpen={setUploadModalOpen}
        navPanelOpen={navigation.navPanelOpen}
        setNavPanelOpen={navigation.setNavPanelOpen}
        notifPanelOpen={notifications.notifPanelOpen}
        setNotifPanelOpen={notifications.setNotifPanelOpen}
        handleSaveMapData={floorplanData.handleSaveMapData}
        isSaving={floorplanData.isSaving}
        isDirty={mapEditor.isDirty}
        nodes={mapEditor.nodes}
        edges={mapEditor.edges}
        handleAiAnalyze={handleAiAnalyze}
        isAnalyzing={floorplanData.isAnalyzing}
        leftDrawerOpen={leftDrawerOpen}
        setLeftDrawerOpen={setLeftDrawerOpen}
        showAllLabels={mapEditor.showAllLabels}
        setShowAllLabels={mapEditor.setShowAllLabels}
        canUndo={mapEditor.canUndo}
        canRedo={mapEditor.canRedo}
        onUndo={mapEditor.undo}
        onRedo={mapEditor.redo}
      />

      {/* Main Studio Body */}
      <div className="flex-1 flex min-h-0 overflow-hidden relative">
        {/* Left Collapsible Floorplans Drawer (Modal always stays mounted) */}
        <aside className={leftDrawerOpen ? 'w-[260px] shrink-0 h-full overflow-hidden z-20' : 'contents'}>
          <MapManagerCard
            {...floorplanData}
            drawerVisible={leftDrawerOpen}
            uploadModalOpen={uploadModalOpen}
            setUploadModalOpen={setUploadModalOpen}
          />
        </aside>

        {/* Center Full-Bleed Canvas Viewport */}
        <div
          ref={mapEditor.containerRef}
          className="flex-1 min-w-0 h-full relative overflow-hidden flex items-center justify-center"
          style={{
            backgroundImage: isDark
              ? 'radial-gradient(rgba(148, 163, 184, 0.14) 1px, transparent 1px)'
              : 'radial-gradient(rgba(100, 116, 139, 0.22) 1px, transparent 1px)',
            backgroundSize: '20px 20px',
          }}
        >
          {/* Empty State */}
          {!floorplanData.currentFloorplanId && (
            <div className="max-w-sm text-center p-8 rounded-2xl bg-white/90 dark:bg-slate-900/90 border border-slate-200 dark:border-slate-800 shadow-lg backdrop-blur-md z-10">
              <div className="w-12 h-12 rounded-2xl bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 flex items-center justify-center mx-auto mb-4">
                <Compass className="w-6 h-6" />
              </div>
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">
                No Floorplan Selected
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1.5 leading-relaxed">
                Choose a building floor from the left drawer to inspect or edit its routing graph,
                or upload a new architectural floorplan image.
              </p>
              <button
                type="button"
                onClick={() => setUploadModalOpen(true)}
                className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold transition-colors shadow-xs"
              >
                <Upload className="w-3.5 h-3.5" />
                Upload New Floorplan
              </button>
            </div>
          )}

          {/* Floating Left CAD Tool Rail (Edit Mode) */}
          {floorplanData.currentFloorplanId && mapEditor.appMode === 'edit' && (
            <div className="absolute left-3.5 top-3.5 z-20 flex flex-col gap-1 p-1.5 rounded-2xl bg-white/95 dark:bg-slate-900/95 border border-slate-200 dark:border-slate-800 shadow-lg backdrop-blur-md">
              {[
                { id: '', label: 'Select / Pan (V)', icon: MousePointer2, activeColor: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300' },
                { id: 'add_nodes', label: 'Add Node (N)', icon: MapPin, activeColor: 'bg-blue-50 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300' },
                { id: 'draw_paths', label: 'Draw Edge (E)', icon: Link2, activeColor: 'bg-purple-50 text-purple-600 dark:bg-purple-500/20 dark:text-purple-300' },
                { id: 'delete_element', label: 'Delete Element (D)', icon: Trash2, activeColor: 'bg-red-50 text-red-600 dark:bg-red-500/20 dark:text-red-400' },
              ].map((tool) => {
                const IconComp = tool.icon;
                const active = mapEditor.mode === tool.id;
                return (
                  <button
                    key={tool.id || 'select'}
                    type="button"
                    onClick={() =>
                      tool.id === ''
                        ? mapEditor.setMode('')
                        : mapEditor.selectTool(tool.id, floorplanData.currentFloorplanId)
                    }
                    title={tool.label}
                    className={`w-9 h-9 rounded-xl flex items-center justify-center transition-all ${
                      active
                        ? `${tool.activeColor} shadow-xs`
                        : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-100'
                    }`}
                  >
                    <IconComp className="w-4 h-4" />
                  </button>
                );
              })}

              <div className="h-px bg-slate-200 dark:bg-slate-800 my-0.5" />

              <div className="relative">
                <button
                  type="button"
                  onClick={() => setWallPopoverOpen((v) => !v)}
                  title="Wall Mask Overlay & Sensitivity"
                  className={`w-9 h-9 rounded-xl flex items-center justify-center transition-all ${
                    floorplanData.showWallOverlay
                      ? 'bg-teal-50 text-teal-600 dark:bg-teal-500/20 dark:text-teal-300'
                      : 'text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                >
                  {floorplanData.showWallOverlay ? (
                    <Eye className="w-4 h-4" />
                  ) : (
                    <EyeOff className="w-4 h-4" />
                  )}
                </button>

                {wallPopoverOpen && (
                  <div className="absolute left-12 top-0 w-56 p-3 rounded-2xl bg-white/95 dark:bg-slate-900/95 border border-slate-200 dark:border-slate-800 shadow-xl backdrop-blur-md space-y-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold text-slate-700 dark:text-slate-200">
                        Wall Mask
                      </span>
                      <button
                        type="button"
                        onClick={() => floorplanData.setShowWallOverlay((v) => !v)}
                        className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${
                          floorplanData.showWallOverlay
                            ? 'bg-teal-100 text-teal-700 dark:bg-teal-500/20 dark:text-teal-300'
                            : 'bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                        }`}
                      >
                        {floorplanData.showWallOverlay ? 'On' : 'Off'}
                      </button>
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between text-[11px] text-slate-500">
                        <span>Sensitivity</span>
                        <span className="font-mono font-bold text-slate-700 dark:text-slate-200 flex items-center gap-1">
                          {floorplanData.isFetchingWallMask && (
                            <Loader2 className="w-3 h-3 animate-spin text-indigo-500" />
                          )}
                          {floorplanData.wallSensitivity}
                        </span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="255"
                        value={floorplanData.wallSensitivity}
                        onChange={(e) =>
                          floorplanData.setWallSensitivity(parseInt(e.target.value, 10))
                        }
                        onMouseUp={() =>
                          floorplanData.fetchWallMask(
                            floorplanData.currentFloorplanId,
                            floorplanData.wallSensitivity
                          )
                        }
                        onTouchEnd={() =>
                          floorplanData.fetchWallMask(
                            floorplanData.currentFloorplanId,
                            floorplanData.wallSensitivity
                          )
                        }
                        disabled={!floorplanData.showWallOverlay || floorplanData.isFetchingWallMask}
                        className="w-full h-1.5 bg-slate-200 dark:bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-600 disabled:opacity-40"
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Floating AI Verification Bar */}
          {floorplanData.currentFloorplanId && mapEditor.pendingAiCount > 0 && (
            <div className="absolute top-3.5 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2.5 px-3.5 py-2 rounded-2xl bg-slate-900/95 dark:bg-slate-800/95 text-white border border-teal-500/40 shadow-xl backdrop-blur-md text-xs font-semibold">
              <Sparkles className="w-4 h-4 text-teal-400 shrink-0" />
              <span>
                {mapEditor.pendingAiCount} AI node{mapEditor.pendingAiCount !== 1 ? 's' : ''} ready
                to verify
              </span>
              <button
                type="button"
                onClick={mapEditor.approveAllAiNodes}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl bg-teal-500 hover:bg-teal-400 text-slate-950 text-[11px] font-extrabold transition-colors"
              >
                <CheckCheck className="w-3.5 h-3.5" />
                Approve All
              </button>
              <button
                type="button"
                onClick={mapEditor.clearAiAnalysis}
                className="px-2 py-1 rounded-xl bg-white/10 hover:bg-white/20 text-slate-200 text-[11px] font-bold transition-colors"
              >
                Discard
              </button>
            </div>
          )}

          {/* Floating Bottom-Left Legend Toggle */}
          {floorplanData.currentFloorplanId && (
            <div className="absolute bottom-3.5 left-3.5 z-20 flex flex-col items-start gap-2">
              {legendOpen && (
                <div className="p-3 rounded-2xl bg-white/95 dark:bg-slate-900/95 border border-slate-200 dark:border-slate-800 shadow-lg backdrop-blur-md text-[11px] space-y-1.5 min-w-[180px]">
                  <div className="flex items-center justify-between pb-1 border-b border-slate-100 dark:border-slate-800">
                    <span className="font-bold text-slate-700 dark:text-slate-200">Map Legend</span>
                    <button
                      type="button"
                      onClick={() => setLegendOpen(false)}
                      className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                    <span className="w-3 h-3 rounded-full bg-red-500 border border-slate-900/30" />
                    <span>Standard Node</span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                    <span className="w-3 h-3 rounded-full bg-purple-500 border border-white shadow-xs" />
                    <span>Elevator / Stairwell / Entrance</span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                    <span className="w-3 h-3 rounded-full bg-emerald-500 ring-2 ring-teal-400 ring-offset-1 ring-offset-white dark:ring-offset-slate-900" />
                    <span>AI Pending Review</span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                    <span className="w-3 h-3 rounded-full bg-slate-500" />
                    <span>Inaccessible (DENY)</span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                    <span className="w-3.5 h-1 rounded-full bg-blue-500" />
                    <span>Navigable Path</span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                    <span className="w-3.5 h-1 rounded-full bg-teal-500" />
                    <span>Active Route Overlay</span>
                  </div>
                </div>
              )}
              <button
                type="button"
                onClick={() => setLegendOpen((v) => !v)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-white/95 dark:bg-slate-900/95 border border-slate-200 dark:border-slate-800 shadow-md backdrop-blur-md text-[11px] font-semibold text-slate-600 dark:text-slate-300 hover:border-indigo-400 transition-colors"
              >
                <HelpCircle className="w-3.5 h-3.5 text-indigo-500" />
                <span>Legend</span>
              </button>
            </div>
          )}

          {/* Floating Bottom-Right Zoom Controls */}
          {floorplanData.currentFloorplanId && (
            <div className="absolute bottom-3.5 right-3.5 z-20 flex items-center gap-1 p-1 rounded-xl bg-white/95 dark:bg-slate-900/95 border border-slate-200 dark:border-slate-800 shadow-lg backdrop-blur-md">
              <button
                type="button"
                onClick={() => mapEditor.setStageScale((s) => Math.max(s / 1.2, 0.2))}
                className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                title="Zoom Out"
              >
                <Minus className="w-3.5 h-3.5" />
              </button>
              <span className="px-1.5 text-[11px] font-mono font-bold text-slate-600 dark:text-slate-300 tabular-nums min-w-[42px] text-center">
                {zoomPercent}%
              </span>
              <button
                type="button"
                onClick={() => mapEditor.setStageScale((s) => Math.min(s * 1.2, 6))}
                className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                title="Zoom In"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
              <div className="w-px h-4 bg-slate-200 dark:bg-slate-800 mx-0.5" />
              <button
                type="button"
                onClick={mapEditor.handleResetView}
                className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                title="Fit to Screen (F)"
              >
                <Maximize2 className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {/* Konva Stage */}
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
                if (e.target === e.target.getStage() && mapEditor.isDraggingStage) {
                  mapEditor.isDraggingStage.current = true;
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
              className={
                mapEditor.mode === 'add_nodes' || mapEditor.mode === 'draw_paths'
                  ? 'cursor-crosshair'
                  : mapEditor.mode === 'delete_element'
                    ? 'cursor-not-allowed'
                    : 'cursor-grab active:cursor-grabbing'
              }
            >
              <Layer>
                {/* Clean Paper Frame for Floorplan */}
                <Rect
                  x={0}
                  y={0}
                  width={CANVAS_WIDTH}
                  height={CANVAS_HEIGHT}
                  fill="#ffffff"
                  shadowColor="rgba(15, 23, 42, 0.22)"
                  shadowBlur={20}
                  shadowOffsetY={6}
                  cornerRadius={6}
                  listening={false}
                />

                {/* Floorplan Image */}
                {currentImageObj && (
                  <KonvaImage image={currentImageObj} width={CANVAS_WIDTH} height={CANVAS_HEIGHT} />
                )}

                {/* Persistent Wall Mask Layer */}
                {floorplanData.showWallOverlay && floorplanData.wallOverlayImage && (
                  <KonvaImage
                    image={floorplanData.wallOverlayImage}
                    width={CANVAS_WIDTH}
                    height={CANVAS_HEIGHT}
                    opacity={1}
                    listening={false}
                  />
                )}

                {/* Edge Preview Line */}
                {mapEditor.edgeDrawState && mapEditor.nodes[mapEditor.edgeDrawState.startNodeIndex] && (
                  <Line
                    points={[
                      mapEditor.nodes[mapEditor.edgeDrawState.startNodeIndex].x,
                      mapEditor.nodes[mapEditor.edgeDrawState.startNodeIndex].y,
                      mapEditor.edgeDrawState.currentPos.x,
                      mapEditor.edgeDrawState.currentPos.y,
                    ]}
                    stroke="#14b8a6"
                    strokeWidth={3}
                    dash={[5, 5]}
                    listening={false}
                  />
                )}

                {/* Edges */}
                {mapEditor.edges.map((edge, i) => {
                  const isSelected =
                    mapEditor.selectedElement.type === 'edge' &&
                    mapEditor.selectedElement.index === i;
                  if (edge.is_cross_floor) return null;

                  let points = [];
                  if (edge.pathPoints && edge.pathPoints.length >= 2) {
                    points = edge.pathPoints.flatMap((p) => [p.x, p.y]);
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
                            ? '#f59e0b'
                            : mapEditor.hoveredEdgeIndex === i
                              ? mapEditor.mode === 'delete_element'
                                ? '#ef4444'
                                : mapEditor.appMode === 'test'
                                  ? '#14b8a6'
                                  : '#10b981'
                              : edge.is_accessible === 'DENY'
                                ? '#64748b'
                                : '#3b82f6'
                        }
                        strokeWidth={isSelected ? 4.5 : 2.5}
                        opacity={isSelected || mapEditor.hoveredEdgeIndex === i ? 1 : 0.78}
                        hitStrokeWidth={20}
                        lineCap="round"
                        lineJoin="round"
                        onMouseEnter={() => mapEditor.setHoveredEdgeIndex(i)}
                        onMouseLeave={() => mapEditor.setHoveredEdgeIndex(null)}
                        onClick={(e) => mapEditor.handleEdgeClick(i, e)}
                        onTap={(e) => mapEditor.handleEdgeClick(i, e)}
                        onDblClick={(e) => mapEditor.handleLineDblClick(i, e)}
                      />
                      {mapEditor.hoveredEdgeIndex === i && (
                        <Text
                          x={(points[0] + points[points.length - 2]) / 2 + 8}
                          y={(points[1] + points[points.length - 1]) / 2 - 14}
                          text={`${edge.weight}m`}
                          fontSize={12}
                          fill="#f8fafc"
                          fontStyle="bold"
                          padding={5}
                          listening={false}
                        />
                      )}
                    </React.Fragment>
                  );
                })}

                {/* Draggable Control Points for Selected Edge */}
                {mapEditor.selectedElement.type === 'edge' &&
                  mapEditor.appMode === 'edit' &&
                  mapEditor.edges[mapEditor.selectedElement.index]?.pathPoints?.map(
                    (pt, ptIdx) => {
                      if (
                        ptIdx === 0 ||
                        ptIdx ===
                          mapEditor.edges[mapEditor.selectedElement.index].pathPoints.length - 1
                      )
                        return null;

                      return (
                        <Circle
                          key={`ctrl-${mapEditor.selectedElement.index}-${ptIdx}`}
                          x={pt.x}
                          y={pt.y}
                          radius={7}
                          fill="#3b82f6"
                          stroke="#ffffff"
                          strokeWidth={2}
                          draggable
                          dragBoundFunc={mapEditor.getClampedDragBounds}
                          onDragStart={(e) => {
                            e.cancelBubble = true;
                            mapEditor.pushHistory();
                            mapEditor.isDraggingControlPoint.current = true;
                          }}
                          onDragMove={(e) => {
                            e.cancelBubble = true;
                            const newPoints = [
                              ...mapEditor.edges[mapEditor.selectedElement.index].pathPoints,
                            ];
                            newPoints[ptIdx] = { x: e.target.x(), y: e.target.y() };
                            const newEdges = [...mapEditor.edges];
                            newEdges[mapEditor.selectedElement.index] = {
                              ...newEdges[mapEditor.selectedElement.index],
                              pathPoints: newPoints,
                            };
                            mapEditor.setEdges(newEdges);
                          }}
                          onDragEnd={(e) => {
                            e.cancelBubble = true;
                            mapEditor.isDraggingControlPoint.current = false;
                            const edge = mapEditor.edges[mapEditor.selectedElement.index];
                            const finalPoints = [...edge.pathPoints];
                            finalPoints[ptIdx] = { x: e.target.x(), y: e.target.y() };
                            const scale = parseFloat(floorplanData.editScaleRatio) || 1.0;
                            let pixelDistance = 0;
                            for (let idx = 1; idx < finalPoints.length; idx++) {
                              pixelDistance += Math.hypot(
                                finalPoints[idx].x - finalPoints[idx - 1].x,
                                finalPoints[idx].y - finalPoints[idx - 1].y
                              );
                            }
                            const updatedWeight = Number((pixelDistance * scale).toFixed(2));
                            const newEdges = [...mapEditor.edges];
                            newEdges[mapEditor.selectedElement.index] = {
                              ...newEdges[mapEditor.selectedElement.index],
                              weight: updatedWeight,
                              pathPoints: finalPoints,
                              customPathPoints: finalPoints,
                              isCustom: true,
                            };
                            mapEditor.setEdges(newEdges);
                            mapEditor.setIsDirty(true);
                          }}
                          onDblClick={(e) =>
                            mapEditor.handleControlPointDblClick(
                              mapEditor.selectedElement.index,
                              ptIdx,
                              e
                            )
                          }
                        />
                      );
                    }
                  )}

                {/* Nodes */}
                {mapEditor.nodes.map((node, i) => {
                  const isSelected =
                    mapEditor.selectedElement.type === 'node' &&
                    mapEditor.selectedElement.index === i;
                  const isAiPending = node.ai_generated && node.review_status === 'PENDING';

                  const isCorridor = node.node_type === 'CORRIDOR';
                  const isTransition = TRANSITION_TYPES.includes(node.node_type);
                  const isHovered = mapEditor.hoveredNodeIndex === i;

                  let fillColor;
                  if (isSelected) fillColor = '#f59e0b';
                  else if (isHovered && mapEditor.mode === 'delete_element') fillColor = '#ef4444';
                  else if (isHovered) fillColor = '#f97316';
                  else if (isAiPending) fillColor = '#10b981';
                  else if (node.is_accessible === 'DENY') fillColor = '#64748b';
                  else if (isTransition) fillColor = '#a855f7';
                  else if (isCorridor) fillColor = '#38bdf8';
                  else fillColor = '#ef4444';

                  const nodeRadius = isCorridor
                    ? isSelected || isHovered
                      ? 6
                      : 4.5
                    : isTransition
                      ? 7.5
                      : 6.5;
                  const showLabel =
                    (mapEditor.showAllLabels && !isCorridor) || isHovered || isSelected;

                  return (
                    <React.Fragment key={`node-${i}`}>
                      {isAiPending && (
                        <Circle
                          x={node.x}
                          y={node.y}
                          radius={nodeRadius + 7}
                          fill="transparent"
                          stroke="#14b8a6"
                          strokeWidth={2}
                          dash={[5, 4]}
                          listening={false}
                        />
                      )}
                      {mapEditor.drawPathStartNode?.current === i &&
                        mapEditor.mode === 'draw_paths' && (
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
                        stroke={TRANSITION_TYPES.includes(node.node_type) ? '#ffffff' : '#0f172a'}
                        strokeWidth={TRANSITION_TYPES.includes(node.node_type) ? 2.5 : 2}
                        draggable={mapEditor.appMode === 'edit'}
                        dragBoundFunc={
                          mapEditor.appMode === 'edit' ? mapEditor.getClampedDragBounds : undefined
                        }
                        onDragStart={
                          mapEditor.appMode === 'edit'
                            ? mapEditor.handleNodeDragStart
                            : undefined
                        }
                        onDragMove={
                          mapEditor.appMode === 'edit'
                            ? (e) => mapEditor.handleNodeDragMove(i, e)
                            : undefined
                        }
                        onDragEnd={
                          mapEditor.appMode === 'edit'
                            ? (e) => mapEditor.handleNodeDragEnd(i, e)
                            : undefined
                        }
                        onClick={(e) => mapEditor.handleNodeClick(i, e)}
                        onTap={(e) => mapEditor.handleNodeClick(i, e)}
                        onMouseEnter={() => mapEditor.setHoveredNodeIndex(i)}
                        onMouseLeave={() => mapEditor.setHoveredNodeIndex(null)}
                      />

                      {showLabel && node.room_label && (
                        <Group x={node.x + 12} y={node.y - 22} listening={false}>
                          <Rect
                            width={Math.max(48, node.room_label.length * 6.8 + 12)}
                            height={20}
                            fill="rgba(15, 23, 42, 0.88)"
                            cornerRadius={5}
                          />
                          <Text
                            x={6}
                            y={4}
                            text={node.room_label}
                            fontSize={11}
                            fill={isAiPending ? '#5eead4' : '#f8fafc'}
                            fontStyle="bold"
                          />
                        </Group>
                      )}

                      {/* 4-Direction Hover Connection Handles */}
                      {(mapEditor.hoveredNodeIndex === i || mapEditor.hoveredHandleNode === i) &&
                        mapEditor.appMode === 'edit' &&
                        ['top', 'right', 'bottom', 'left'].map((pos) => {
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
                        })}
                    </React.Fragment>
                  );
                })}
              </Layer>

              {/* Navigation Route Highlight Overlay Layer */}
              {navigation.navHighlight && (
                <Layer listening={false}>
                  {mapEditor.edges.map((edge, i) => {
                    if (edge.is_cross_floor || !edge.edge_id) return null;
                    if (
                      !navigation.navHighlight.edge_ids ||
                      !navigation.navHighlight.edge_ids.includes(edge.edge_id)
                    )
                      return null;
                    let points = [];
                    if (edge.pathPoints && edge.pathPoints.length >= 2) {
                      points = edge.pathPoints.flatMap((p) => [p.x, p.y]);
                    } else {
                      const sN = mapEditor.nodes[edge.start];
                      const eN = mapEditor.nodes[edge.end];
                      if (sN && eN) points = [sN.x, sN.y, eN.x, eN.y];
                    }
                    if (points.length < 4) return null;
                    return (
                      <React.Fragment key={`nav-edge-${i}`}>
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
                          stroke="#0d9488"
                          strokeWidth={5}
                          opacity={0.95}
                          lineCap="round"
                          lineJoin="round"
                          dash={[10, 4]}
                        />
                      </React.Fragment>
                    );
                  })}
                  {mapEditor.nodes.map((node, i) => {
                    if (!node.node_id) return null;
                    if (
                      !navigation.navHighlight.node_ids ||
                      !navigation.navHighlight.node_ids.includes(node.node_id)
                    )
                      return null;
                    const isStart = navigation.navHighlight.node_ids[0] === node.node_id;
                    const isEnd =
                      navigation.navHighlight.node_ids[
                        navigation.navHighlight.node_ids.length - 1
                      ] === node.node_id;
                    return (
                      <React.Fragment key={`nav-node-${i}`}>
                        <Circle x={node.x} y={node.y} radius={17} fill="#14b8a6" opacity={0.2} />
                        <Circle
                          x={node.x}
                          y={node.y}
                          radius={12}
                          fill="transparent"
                          stroke="#0d9488"
                          strokeWidth={2.5}
                          opacity={0.95}
                        />
                        {(isStart || isEnd) && (
                          <Circle
                            x={node.x}
                            y={node.y}
                            radius={6}
                            fill={isEnd ? '#f59e0b' : '#0d9488'}
                          />
                        )}
                      </React.Fragment>
                    );
                  })}
                </Layer>
              )}
            </Stage>
          )}
        </div>

        {/* Right Contextual Inspector Drawer */}
        {showRightInspector && (
          <aside className="w-[340px] xl:w-[368px] shrink-0 h-full border-l border-slate-200 dark:border-slate-800 overflow-hidden z-20">
            {mapEditor.activeObj && mapEditor.appMode === 'edit' && (
              <PropertiesPanel
                {...mapEditor}
                handleDeleteSelected={mapEditor.handleDeleteSelected}
                rolesList={floorplanData.rolesList}
                accessGroupsList={floorplanData.accessGroupsList}
                globalNodes={floorplanData.globalNodes}
                currentFloorplanId={floorplanData.currentFloorplanId}
                currentBuildingName={floorplanData.editBuildingName}
                currentFloorLevel={floorplanData.editFloorLevel}
              />
            )}

            {navigation.navPanelOpen && (
              <NavigationPanel
                {...navigation}
                rolesList={floorplanData.rolesList}
                globalNodes={floorplanData.globalNodes}
                setNotifVisitorId={notifications.setNotifVisitorId}
                setNotifVisitorEmail={notifications.setNotifVisitorEmail}
                setNotifMessage={notifications.setNotifMessage}
                setIsAutoMessage={notifications.setIsAutoMessage}
                currentFloorplanId={floorplanData.currentFloorplanId}
                onSelectFloorplan={(fpId) => floorplanData.loadFloorplanData(fpId)}
              />
            )}

            {notifications.notifPanelOpen && (
              <NotificationPanel
                {...notifications}
                navStartId={navigation.navStartId}
                setNavStartId={navigation.setNavStartId}
                navEndId={navigation.navEndId}
                setNavEndId={navigation.setNavEndId}
                navRoleId={navigation.navRoleId}
                setNavRoleId={navigation.setNavRoleId}
                globalNodes={floorplanData.globalNodes}
                rolesList={floorplanData.rolesList}
              />
            )}
          </aside>
        )}
      </div>

      {/* Shared Styled Confirmation Dialog */}
      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        message={confirmState.message}
        impactNote={confirmState.impactNote}
        confirmLabel={confirmState.confirmLabel}
        variant={confirmState.variant}
        onCancel={closeConfirm}
        onConfirm={async () => {
          const fn = confirmState.onConfirm;
          closeConfirm();
          if (fn) await fn();
        }}
      />
    </div>
  );
}
