/**
 * @file useFloorplanData.js
 * @description Floorplan data management hook for the Campus Navigation System.
 *
 * Manages:
 *  - Floorplan list (dropdown), global nodes, and roles list fetching
 *  - Loading a floorplan from the API and converting DB data to canvas state
 *  - Uploading a new floorplan image
 *  - Updating and deleting floorplans
 *  - Saving all map data (nodes + edges) to the database
 */

import { useState, useEffect } from 'react';
import { authAxios } from '../services/api';

/**
 * Manages all floorplan I/O operations and the data state that drives the map editor.
 *
 * @param {Object} deps - Dependencies injected from App (to avoid circular state).
 * @param {Function} deps.onFloorplanLoaded   - Callback with `{ nodes, edges, floorplan }` after load.
 * @param {Function} deps.onFloorplanCleared  - Callback to clear canvas and mode state on delete/logout.
 * @param {Function} deps.onUploadSuccess     - Callback after successful upload with `{ floorplan_id, image_path, buildingName, floorLevel, scaleRatio }`.
 * @param {React.RefObject} deps.fileInputRef - Ref to the file input element (to reset after upload).
 * @returns {Object} Floorplan state and handlers.
 */
export function useFloorplanData({ onFloorplanLoaded, onFloorplanCleared, onUploadSuccess, fileInputRef }) {
    const [currentFloorplanId, setCurrentFloorplanId] = useState(null);
    const [floorplansList, setFloorplansList]         = useState([]);
    const [globalNodes, setGlobalNodes]               = useState([]);
    const [rolesList, setRolesList]                   = useState([]);
    const [isUploading, setIsUploading]               = useState(false);

    // Create Map form fields
    const [buildingName, setBuildingName] = useState('');
    const [floorLevel, setFloorLevel]     = useState('');
    const [scaleRatio, setScaleRatio]     = useState('1.0');

    // Manage Map edit fields
    const [editBuildingName, setEditBuildingName] = useState('');
    const [editFloorLevel, setEditFloorLevel]     = useState('');
    const [editScaleRatio, setEditScaleRatio]     = useState('');

    // Persistent Wall Mask overlay (Recommendation 8)
    const [wallOverlayImage, setWallOverlayImage] = useState(null);
    const [wallGrid, setWallGrid] = useState(null);
    const [isFetchingWallMask, setIsFetchingWallMask] = useState(false);
    
    // Wall overlay settings
    const [wallSensitivity, setWallSensitivity] = useState(120);
    const [showWallOverlay, setShowWallOverlay] = useState(true);

    // AI Floorplan Analysis state
    const [isAnalyzing, setIsAnalyzing] = useState(false);

    /**
     * Fetches the Wall Detection mask from the backend for the current floorplan.
     */
    const fetchWallMask = async (fpId, sensitivity = wallSensitivity) => {
        setIsFetchingWallMask(true);
        setWallOverlayImage(null);
        setWallGrid(null);
        try {
            const res = await authAxios.post('/api/wall-detection', {
                floorplan_id: fpId,
                sensitivity: sensitivity,
                canvas_width: 800,
                canvas_height: 600,
                grid_scale: 8
            });
            if (res.data.success && res.data.wallGrid) {
                setWallGrid(res.data.wallGrid.grid);
                // Dynamically import to avoid circular dependencies if any, or just import at top
                import('../utils/canvasUtils').then(({ generateWallOverlay }) => {
                    const img = generateWallOverlay(res.data.wallGrid.grid, 800, 600, 8);
                    setWallOverlayImage(img);
                });
            }
        } catch (err) {
            console.error('Failed to fetch wall mask overlay:', err);
        } finally {
            setIsFetchingWallMask(false);
        }
    };

    /**
     * Fetches initial reference data needed on login:
     * roles list, floorplans dropdown, and global nodes.
     * Called by useAuth's onLoginSuccess callback.
     */
    const fetchInitialData = () => {
        authAxios.get('/api/roles').then(res => setRolesList(res.data)).catch(console.error);
        authAxios.get('/api/floorplans').then(res => setFloorplansList(res.data)).catch(console.error);
        authAxios.get('/api/global-nodes').then(res => setGlobalNodes(res.data)).catch(console.error);
    };

    useEffect(() => {
        fetchInitialData();
    }, []);

    /**
     * Refreshes the global nodes list from the API.
     * Called after saving map data or creating transitions to keep the list current.
     */
    const refreshGlobalNodes = () => {
        authAxios.get('/api/global-nodes').then(r => setGlobalNodes(r.data)).catch(console.error);
    };

    /**
     * Loads a floorplan's complete data from the API.
     * Converts DB-format nodes and edges into the in-memory canvas state format,
     * then invokes `onFloorplanLoaded` with the converted data.
     *
     * @param {React.ChangeEvent<HTMLSelectElement>|{target:{value:string}}} e - Change event or synthetic event with the floorplan ID.
     */
    const loadFloorplanData = async (e) => {
        const fpId = e.target.value;
        if (!fpId) return;
        try {
            const res = await authAxios.get(`/api/map-data/${fpId}`);
            setCurrentFloorplanId(fpId);
            setEditBuildingName(res.data.floorplan.building_name);
            setEditFloorLevel(res.data.floorplan.floor_level);
            setEditScaleRatio(res.data.floorplan.scale_ratio);

            // Fetch the persistent wall overlay
            fetchWallMask(fpId);

            // Load the floorplan image
            const img = new window.Image();
            const baseUrl = authAxios.defaults.baseURL || '';
            img.src = `${baseUrl}${res.data.floorplan.image_path}`;

            // Build a node index map for resolving edge start/end references
            const idToIndex = {};
            const reactNodes = res.data.nodes.map((n, idx) => {
                idToIndex[n.node_id] = idx;
                return {
                    node_id:      n.node_id,
                    x:            n.coord_x,
                    y:            n.coord_y,
                    room_label:   n.room_label,
                    node_type:    n.node_type,
                    is_accessible: n.is_accessible,
                    allowed_roles: n.allowed_roles
                };
            });

            const reactEdges = res.data.edges.map(e => {
                // If destination node is not on this floorplan, it's a cross-floor edge
                const isCrossFloor = idToIndex[e.destination_node_id] === undefined;

                const customPathPoints = e.custom_path ? JSON.parse(e.custom_path) : null;
                const isCustom = !!customPathPoints;

                if (isCrossFloor) {
                    return {
                        edge_id:         e.edge_id,
                        start:           idToIndex[e.source_node_id],
                        is_cross_floor:  true,
                        target_node_id:  e.destination_node_id,
                        weight:          e.weight_distance,
                        is_bidirectional: e.is_bidirectional === 1,
                        is_accessible:   e.is_accessible,
                        allowed_roles:   e.allowed_roles,
                        isCustom:        false,
                        customPathPoints: null,
                        pathPoints:      null
                    };
                }
                return {
                    edge_id:         e.edge_id,
                    start:           idToIndex[e.source_node_id],
                    end:             idToIndex[e.destination_node_id],
                    weight:          e.weight_distance,
                    is_bidirectional: e.is_bidirectional === 1,
                    is_accessible:   e.is_accessible,
                    allowed_roles:   e.allowed_roles,
                    isCustom,
                    customPathPoints,
                    pathPoints:      customPathPoints || null // Null triggers A* recalculation
                };
            }).filter(e => e.start !== undefined && (e.is_cross_floor || e.end !== undefined));

            refreshGlobalNodes();

            img.onload = () => {
                if (onFloorplanLoaded) {
                    onFloorplanLoaded({ img, nodes: reactNodes, edges: reactEdges, floorplan: res.data.floorplan });
                }
            };
            
            img.onerror = () => {
                console.error('Failed to load image at', img.src);
                if (onFloorplanLoaded) {
                    onFloorplanLoaded({ img: null, nodes: reactNodes, edges: reactEdges, floorplan: res.data.floorplan });
                }
            };
        } catch (error) {
            console.error('Failed to load map data', error);
        }
    };

    /**
     * Handles file input change for uploading a new floorplan image.
     * Validates that building name and floor level are filled before proceeding.
     * On success, resets the create-map form and updates the floorplans list.
     *
     * @param {React.ChangeEvent<HTMLInputElement>} e - File input change event.
     */
    const handleImageUpload = async (e) => {
        const file = e.target.files[0];
        if (!file || !buildingName || !floorLevel) {
            return alert('Fill in Building Name and Floor Level first.');
        }
        setIsUploading(true);
        const formData = new FormData();
        formData.append('floorplanImage', file);
        formData.append('buildingName', buildingName);
        formData.append('floorLevel', floorLevel);
        formData.append('scaleRatio', scaleRatio);

        try {
            const response = await authAxios.post('/api/floorplans', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            alert(response.data.message);
            setCurrentFloorplanId(response.data.floorplan_id);
            setEditBuildingName(buildingName);
            setEditFloorLevel(floorLevel);
            setEditScaleRatio(scaleRatio);

            // Fetch the persistent wall overlay for the new floorplan
            fetchWallMask(response.data.floorplan_id);

            // Reset create-map form fields
            setBuildingName('');
            setFloorLevel('');
            setScaleRatio('1.0');
            if (fileInputRef && fileInputRef.current) fileInputRef.current.value = '';

            authAxios.get('/api/floorplans').then(res => setFloorplansList(res.data));

            if (onUploadSuccess) {
                onUploadSuccess({
                    floorplan_id: response.data.floorplan_id,
                    image_path:   response.data.image_path,
                    buildingName,
                    floorLevel,
                    scaleRatio
                });
            }
        } catch (error) {
            alert('Upload Failed.');
        } finally {
            setIsUploading(false);
        }
    };

    /**
     * Sends a PUT request to update the current floorplan's metadata.
     * Refreshes the floorplans dropdown list on success.
     */
    const handleUpdateFloorplan = async () => {
        if (!currentFloorplanId) return;
        try {
            const payload = {
                buildingName: editBuildingName,
                floorLevel:   editFloorLevel,
                scaleRatio:   editScaleRatio
            };
            const res = await authAxios.put(`/api/floorplans/${currentFloorplanId}`, payload);
            alert(res.data.message);
            authAxios.get('/api/floorplans').then(r => setFloorplansList(r.data));
        } catch (err) {
            alert('Failed to update floorplan details.');
        }
    };

    /**
     * Permanently deletes the current floorplan after a confirmation dialog.
     * Clears canvas state via the `onFloorplanCleared` callback on success.
     */
    const handleDeleteMap = async () => {
        if (!currentFloorplanId) return;
        if (!window.confirm('WARNING: Are you sure you want to completely delete this map? All data will be permanently lost.')) return;
        try {
            await authAxios.delete(`/api/floorplans/${currentFloorplanId}`);
            alert('Map deleted successfully.');
            setCurrentFloorplanId(null);
            setWallOverlayImage(null);
            setWallGrid(null);
            authAxios.get('/api/floorplans').then(res => setFloorplansList(res.data));
            if (onFloorplanCleared) onFloorplanCleared();
        } catch (error) {
            alert('Failed to delete map.');
        }
    };

    /**
     * Runs the Phase 1 AI floorplan analysis pipeline via the backend proxy.
     *
     * Sends the floorplan ID to POST /api/analyze-floorplan, which forwards it
     * to the Python AI service. Returns the FloorplanAnalysisResult on success,
     * or null if the request fails.
     *
     * The caller is responsible for passing the result to `importAiNodes` from
     * useMapEditor to display the AI-generated nodes on the Konva canvas.
     *
     * @param {Object} [options]                    - Optional tuning parameters.
     * @param {number} [options.sensitivity=120]    - Wall detection threshold 0–255.
     * @param {number} [options.roomGapClosePx=25]  - Door gap closing kernel (px).
     * @param {number} [options.minRoomAreaPx=2000] - Min room area (px²).
     * @returns {Promise<Object|null>} FloorplanAnalysisResult or null on error.
     */
    const analyzeFloorplan = async (options = {}) => {
        if (!currentFloorplanId) {
            alert('Please select a floorplan before running AI Analysis.');
            return null;
        }
        setIsAnalyzing(true);
        try {
            const res = await authAxios.post('/api/analyze-floorplan', {
                floorplan_id:      currentFloorplanId,
                sensitivity:       options.sensitivity       ?? 120,
                room_gap_close_px: options.roomGapClosePx    ?? 25,
                min_room_area_px:  options.minRoomAreaPx     ?? 2000,
                canvas_width:      800,
                canvas_height:     600,
                grid_scale:        8,
            });
            return res.data;
        } catch (error) {
            console.error('[useFloorplanData] analyzeFloorplan failed:', error);
            alert(`AI Analysis failed: ${error?.response?.data?.error || error.message}`);
            return null;
        } finally {
            setIsAnalyzing(false);
        }
    };

    /**
     * Saves the full map graph (nodes + edges) for the current floorplan to the database.
     * After save, reloads the floorplan data to sync persisted IDs back into local state.
     *
     * @param {Array} nodes - Current canvas node objects.
     * @param {Array} edges - Current canvas edge objects.
     */
    const handleSaveMapData = async (nodes, edges) => {
        if (!currentFloorplanId) return alert('Please select a floorplan!');
        try {
            // Serialize custom path waypoints to JSON string for the API
            const serializedEdges = edges.map(e => ({
                ...e,
                custom_path: e.pathPoints ? JSON.stringify(e.pathPoints) : null
            }));

            const res = await authAxios.post('/api/map-data', {
                floorplan_id: currentFloorplanId,
                nodes,
                edges: serializedEdges
            });
            alert(res.data.message);
            // Reload to sync fresh DB IDs back into canvas state
            loadFloorplanData({ target: { value: currentFloorplanId } });
        } catch (error) {
            const serverMsg = error.response?.data?.message || error.response?.data?.error || '';
            console.error('[Save Map] Error:', error.response?.status, error.response?.data || error.message);
            alert(`Failed to save map data.${serverMsg ? '\n\n' + serverMsg : ''}`);
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
        isAnalyzing,
        buildingName, setBuildingName,
        floorLevel, setFloorLevel,
        scaleRatio, setScaleRatio,
        editBuildingName, setEditBuildingName,
        editFloorLevel, setEditFloorLevel,
        editScaleRatio, setEditScaleRatio,
        wallOverlayImage,
        wallGrid,
        isFetchingWallMask,
        wallSensitivity, setWallSensitivity,
        showWallOverlay, setShowWallOverlay,
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
