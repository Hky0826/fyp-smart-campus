/**
 * @file useFloorplanData.js
 * @description Floorplan data management hook integrated with cloudApi and ToastProvider.
 */

import { useState, useEffect, useCallback } from 'react';
import { cloudApi } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { MAPPING_API_BASE } from '../constants/mapConstants';

export function useFloorplanData({
  isAuthenticated,
  onFloorplanLoaded,
  onFloorplanCleared,
  onUploadSuccess,
  fileInputRef,
  requestConfirm,
}) {
  const toast = useToast();

  const [currentFloorplanId, setCurrentFloorplanId] = useState(null);
  const [floorplansList, setFloorplansList] = useState([]);
  const [globalNodes, setGlobalNodes] = useState([]);
  const [rolesList, setRolesList] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingFloorplan, setIsLoadingFloorplan] = useState(false);

  // Create Map form fields
  const [buildingName, setBuildingName] = useState('');
  const [floorLevel, setFloorLevel] = useState('');
  const [scaleRatio, setScaleRatio] = useState('1.0');

  // Manage Map edit fields
  const [editBuildingName, setEditBuildingName] = useState('');
  const [editFloorLevel, setEditFloorLevel] = useState('');
  const [editScaleRatio, setEditScaleRatio] = useState('');

  // Persistent Wall Mask overlay
  const [wallOverlayImage, setWallOverlayImage] = useState(null);
  const [wallGrid, setWallGrid] = useState(null);
  const [isFetchingWallMask, setIsFetchingWallMask] = useState(false);

  // Wall overlay settings
  const [wallSensitivity, setWallSensitivity] = useState(120);
  const [showWallOverlay, setShowWallOverlay] = useState(true);

  // AI Floorplan Analysis state
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const fetchWallMask = useCallback(
    async (fpId, sensitivity = wallSensitivity) => {
      if (!fpId) return;
      setIsFetchingWallMask(true);
      setWallOverlayImage(null);
      setWallGrid(null);
      try {
        const data = await cloudApi.post(`${MAPPING_API_BASE}/api/wall-detection`, {
          floorplan_id: fpId,
          sensitivity,
          canvas_width: 800,
          canvas_height: 600,
          grid_scale: 8,
        });
        if (data?.success && data?.wallGrid) {
          setWallGrid(data.wallGrid.grid);
          const { generateWallOverlay } = await import('../utils/canvasUtils');
          const img = generateWallOverlay(data.wallGrid.grid, 800, 600, 8);
          setWallOverlayImage(img);
        }
      } catch (err) {
        console.error('Failed to fetch wall mask overlay:', err);
      } finally {
        setIsFetchingWallMask(false);
      }
    },
    [wallSensitivity]
  );

  const fetchInitialData = useCallback(() => {
    cloudApi
      .get(`${MAPPING_API_BASE}/api/roles`)
      .then((data) => setRolesList(Array.isArray(data) ? data : []))
      .catch((err) => console.error('Failed to fetch roles:', err));
    cloudApi
      .get(`${MAPPING_API_BASE}/api/floorplans`)
      .then((data) => setFloorplansList(Array.isArray(data) ? data : []))
      .catch((err) => console.error('Failed to fetch floorplans:', err));
    cloudApi
      .get(`${MAPPING_API_BASE}/api/global-nodes`)
      .then((data) => setGlobalNodes(Array.isArray(data) ? data : []))
      .catch((err) => console.error('Failed to fetch global nodes:', err));
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      fetchInitialData();
    }
  }, [isAuthenticated, fetchInitialData]);

  const refreshGlobalNodes = useCallback(() => {
    cloudApi
      .get(`${MAPPING_API_BASE}/api/global-nodes`)
      .then((data) => setGlobalNodes(Array.isArray(data) ? data : []))
      .catch(console.error);
  }, []);

  const loadFloorplanData = useCallback(
    async (fpIdOrEvent) => {
      const fpId =
        typeof fpIdOrEvent === 'object' && fpIdOrEvent?.target
          ? fpIdOrEvent.target.value
          : fpIdOrEvent;
      if (!fpId) return;
      setIsLoadingFloorplan(true);
      try {
        const data = await cloudApi.get(`${MAPPING_API_BASE}/api/map-data/${fpId}`);
        setCurrentFloorplanId(String(fpId));
        setEditBuildingName(data.floorplan.building_name);
        setEditFloorLevel(String(data.floorplan.floor_level));
        setEditScaleRatio(String(data.floorplan.scale_ratio ?? 1.0));

        // Fetch persistent wall overlay
        fetchWallMask(fpId);

        // Load floorplan image
        const img = new window.Image();
        const rawPath = data.floorplan.image_path || '';
        img.src = rawPath.startsWith('http') ? rawPath : `${MAPPING_API_BASE}${rawPath}`;

        const idToIndex = {};
        const reactNodes = (data.nodes || []).map((n, idx) => {
          idToIndex[n.node_id] = idx;
          return {
            node_id: n.node_id,
            x: n.coord_x,
            y: n.coord_y,
            room_label: n.room_label,
            node_type: n.node_type,
            is_accessible: n.is_accessible,
            allowed_roles: n.allowed_roles || [],
          };
        });

        const reactEdges = (data.edges || [])
          .map((e) => {
            const isCrossFloor = idToIndex[e.destination_node_id] === undefined;
            let customPathPoints = null;
            if (e.custom_path) {
              try {
                customPathPoints = JSON.parse(e.custom_path);
              } catch {
                customPathPoints = null;
              }
            }
            const isCustom = Boolean(customPathPoints);

            if (isCrossFloor) {
              return {
                edge_id: e.edge_id,
                start: idToIndex[e.source_node_id],
                is_cross_floor: true,
                target_node_id: e.destination_node_id,
                weight: e.weight_distance,
                is_bidirectional: e.is_bidirectional === 1 || e.is_bidirectional === true,
                is_accessible: e.is_accessible,
                allowed_roles: e.allowed_roles || [],
                isCustom: false,
                customPathPoints: null,
                pathPoints: null,
              };
            }
            return {
              edge_id: e.edge_id,
              start: idToIndex[e.source_node_id],
              end: idToIndex[e.destination_node_id],
              weight: e.weight_distance,
              is_bidirectional: e.is_bidirectional === 1 || e.is_bidirectional === true,
              is_accessible: e.is_accessible,
              allowed_roles: e.allowed_roles || [],
              isCustom,
              customPathPoints,
              pathPoints: customPathPoints || null,
            };
          })
          .filter((e) => e.start !== undefined && (e.is_cross_floor || e.end !== undefined));

        refreshGlobalNodes();

        img.onload = () => {
          onFloorplanLoaded?.({ img, nodes: reactNodes, edges: reactEdges, floorplan: data.floorplan });
        };
        img.onerror = () => {
          console.error('Failed to load image at', img.src);
          onFloorplanLoaded?.({ img: null, nodes: reactNodes, edges: reactEdges, floorplan: data.floorplan });
        };
      } catch (error) {
        console.error('Failed to load map data', error);
        toast.error(error?.message || 'Failed to load floorplan data.');
      } finally {
        setIsLoadingFloorplan(false);
      }
    },
    [fetchWallMask, onFloorplanLoaded, refreshGlobalNodes, toast]
  );

  const handleImageUpload = async (fileOrEvent) => {
    const file =
      fileOrEvent instanceof File
        ? fileOrEvent
        : fileOrEvent?.target?.files?.[0];
    if (!file || !buildingName.trim() || floorLevel === '') {
      toast.error('Please enter Building Name, Floor Level, and select a floorplan image.');
      return false;
    }
    setIsUploading(true);
    const formData = new FormData();
    formData.append('floorplanImage', file);
    formData.append('buildingName', buildingName.trim());
    formData.append('floorLevel', floorLevel);
    formData.append('scaleRatio', scaleRatio || '1.0');

    try {
      const response = await cloudApi.post(`${MAPPING_API_BASE}/api/floorplans`, formData);
      toast.success(response?.message || 'Floorplan uploaded successfully.');
      const newFpId = String(response.floorplan_id);
      setBuildingName('');
      setFloorLevel('');
      setScaleRatio('1.0');
      if (fileInputRef?.current) fileInputRef.current.value = '';

      const updatedList = await cloudApi.get(`${MAPPING_API_BASE}/api/floorplans`);
      setFloorplansList(Array.isArray(updatedList) ? updatedList : []);

      await loadFloorplanData(newFpId);

      onUploadSuccess?.({
        floorplan_id: response.floorplan_id,
        image_path: response.image_path,
        buildingName,
        floorLevel,
        scaleRatio,
      });
      return true;
    } catch (err) {
      toast.error(err?.data?.message || err?.data?.error || err?.message || 'Floorplan upload failed.');
      return false;
    } finally {
      setIsUploading(false);
    }
  };

  const handleUpdateFloorplan = async () => {
    if (!currentFloorplanId) return;
    if (!editBuildingName.trim() || editFloorLevel === '') {
      toast.error('Building Name and Floor Level are required.');
      return;
    }
    try {
      const payload = {
        buildingName: editBuildingName.trim(),
        floorLevel: editFloorLevel,
        scaleRatio: editScaleRatio || '1.0',
      };
      const res = await cloudApi.put(`${MAPPING_API_BASE}/api/floorplans/${currentFloorplanId}`, payload);
      toast.success(res?.message || 'Floorplan metadata updated.');
      const updated = await cloudApi.get(`${MAPPING_API_BASE}/api/floorplans`);
      setFloorplansList(Array.isArray(updated) ? updated : []);
      refreshGlobalNodes();
    } catch (err) {
      toast.error(err?.data?.message || err?.message || 'Failed to update floorplan details.');
    }
  };

  const handleDeleteMap = async () => {
    if (!currentFloorplanId) return;
    const executeDelete = async () => {
      try {
        await cloudApi.delete(`${MAPPING_API_BASE}/api/floorplans/${currentFloorplanId}`);
        toast.success('Floorplan deleted successfully.');
        setCurrentFloorplanId(null);
        setWallOverlayImage(null);
        setWallGrid(null);
        const updated = await cloudApi.get(`${MAPPING_API_BASE}/api/floorplans`);
        setFloorplansList(Array.isArray(updated) ? updated : []);
        refreshGlobalNodes();
        onFloorplanCleared?.();
      } catch (err) {
        toast.error(err?.data?.message || err?.message || 'Failed to delete floorplan.');
      }
    };

    if (requestConfirm) {
      requestConfirm({
        title: 'Delete Floorplan Permanently?',
        message: `Are you sure you want to delete "${editBuildingName} — Floor ${editFloorLevel}"?`,
        impactNote: 'All nodes, paths, RBAC rules, and cross-floor links on this floorplan will be permanently removed.',
        confirmLabel: 'Delete Floorplan',
        variant: 'danger',
        onConfirm: executeDelete,
      });
    } else if (window.confirm('Delete this floorplan permanently?')) {
      await executeDelete();
    }
  };

  const analyzeFloorplan = async (options = {}) => {
    if (!currentFloorplanId) {
      toast.info('Select a floorplan before running AI Analysis.');
      return null;
    }
    setIsAnalyzing(true);
    try {
      const data = await cloudApi.post(`${MAPPING_API_BASE}/api/analyze-floorplan`, {
        floorplan_id: currentFloorplanId,
        sensitivity: options.sensitivity ?? wallSensitivity ?? 120,
        room_gap_close_px: options.roomGapClosePx ?? 25,
        min_room_area_px: options.minRoomAreaPx ?? 2000,
        canvas_width: 800,
        canvas_height: 600,
        grid_scale: 8,
      });
      const count = data?.nodes?.length || 0;
      const edgeCount = data?.edges?.length || 0;
      const summary = data?.summary;
      if (count > 0) {
        if (data?.engine === 'opencv_fallback') {
          toast.info(
            `Gemini Vision was temporarily busy; OpenCV fallback detected ${count} nodes. Click AI Auto-Map again to retry Gemini.`
          );
        } else if (summary?.rooms_detected != null) {
          toast.success(
            `AI Auto-Map ready: ${summary.rooms_detected} rooms, ${summary.corridors_generated || 0} corridors, ${edgeCount} paths. Review & approve!`
          );
        } else {
          toast.success(`AI detected ${count} nodes and ${edgeCount} paths. Review and approve when ready.`);
        }
      } else {
        toast.info('AI analysis completed with 0 new nodes detected.');
      }
      return data;
    } catch (error) {
      console.error('[useFloorplanData] analyzeFloorplan failed:', error);
      toast.error(`AI Analysis failed: ${error?.data?.error || error?.message || 'Unknown error'}`);
      return null;
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleSaveMapData = async (nodes, edges) => {
    if (!currentFloorplanId) {
      toast.info('Please select a floorplan first.');
      return false;
    }
    setIsSaving(true);
    try {
      const serializedEdges = edges.map((e) => ({
        ...e,
        custom_path: e.pathPoints ? JSON.stringify(e.pathPoints) : null,
      }));

      const res = await cloudApi.post(`${MAPPING_API_BASE}/api/map-data`, {
        floorplan_id: currentFloorplanId,
        nodes,
        edges: serializedEdges,
      });
      toast.success(res?.message || 'Map data saved successfully.');
      await loadFloorplanData(currentFloorplanId);
      return true;
    } catch (error) {
      const serverMsg = error?.data?.message || error?.data?.error || error?.message || '';
      console.error('[Save Map] Error:', error);
      toast.error(`Failed to save map data.${serverMsg ? ` ${serverMsg}` : ''}`);
      return false;
    } finally {
      setIsSaving(false);
    }
  };

  return {
    currentFloorplanId,
    setCurrentFloorplanId,
    floorplansList,
    globalNodes,
    setGlobalNodes,
    rolesList,
    isUploading,
    isSaving,
    isLoadingFloorplan,
    isAnalyzing,
    buildingName,
    setBuildingName,
    floorLevel,
    setFloorLevel,
    scaleRatio,
    setScaleRatio,
    editBuildingName,
    setEditBuildingName,
    editFloorLevel,
    setEditFloorLevel,
    editScaleRatio,
    setEditScaleRatio,
    wallOverlayImage,
    wallGrid,
    isFetchingWallMask,
    wallSensitivity,
    setWallSensitivity,
    showWallOverlay,
    setShowWallOverlay,
    fetchInitialData,
    refreshGlobalNodes,
    loadFloorplanData,
    fetchWallMask,
    handleImageUpload,
    handleUpdateFloorplan,
    handleDeleteMap,
    handleSaveMapData,
    analyzeFloorplan,
  };
}
