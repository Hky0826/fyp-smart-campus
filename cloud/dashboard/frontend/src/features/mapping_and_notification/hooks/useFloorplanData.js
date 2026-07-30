import { useState } from 'react';
import {
    getFloorplans,
    getGraph,
    saveGraph,
    getRoles,
    getGlobalNodes,
    uploadFloorplan,
    patchFloorplan,
    deleteFloorplan,
    detectWalls,
    getFloorplanImageUrl,
    getBuildings,
    createBuilding
} from '../services/api';

export function useFloorplanData({ onFloorplanLoaded, onFloorplanCleared, onUploadSuccess, fileInputRef }) {
    const [currentFloorplanId, setCurrentFloorplanId] = useState(null);
    const [floorplansList, setFloorplansList]         = useState([]);
    const [buildingsList, setBuildingsList]           = useState([]);
    const [globalNodes, setGlobalNodes]               = useState([]);
    const [rolesList, setRolesList]                   = useState([]);
    const [isUploading, setIsUploading]               = useState(false);
    const [graphVersion, setGraphVersion]             = useState(1);

    // Create Map form fields
    const [selectedBuildingId, setSelectedBuildingId] = useState('');
    const [newBuildingName, setNewBuildingName]         = useState('');
    const [floorLevel, setFloorLevel]                 = useState('');
    const [scaleRatio, setScaleRatio]                 = useState('1.0');

    // Manage Map edit fields
    const [editBuildingName, setEditBuildingName] = useState('');
    const [editFloorLevel, setEditFloorLevel]     = useState('');
    const [editScaleRatio, setEditScaleRatio]     = useState('');

    // Wall Mask overlay
    const [wallOverlayImage, setWallOverlayImage] = useState(null);
    const [wallGrid, setWallGrid]                 = useState(null);
    const [isFetchingWallMask, setIsFetchingWallMask] = useState(false);
    const [wallSensitivity, setWallSensitivity]   = useState(120);
    const [showWallOverlay, setShowWallOverlay]   = useState(true);

    const fetchWallMask = async (fpId, sensitivity = wallSensitivity) => {
        if (!fpId) return;
        setIsFetchingWallMask(true);
        setWallOverlayImage(null);
        setWallGrid(null);
        try {
            const res = await detectWalls(fpId, {
                sensitivity: sensitivity,
                canvas_width: 800,
                canvas_height: 600,
                grid_scale: 8
            });
            if (res.wallGrid) {
                setWallGrid(res.wallGrid.grid || res.wallGrid);
                import('../utils/canvasUtils').then(({ generateWallOverlay }) => {
                    const gridData = res.wallGrid.grid || res.wallGrid;
                    const img = generateWallOverlay(gridData, 800, 600, 8);
                    setWallOverlayImage(img);
                });
            }
        } catch (err) {
            console.error('Failed to fetch wall mask overlay:', err);
        } finally {
            setIsFetchingWallMask(false);
        }
    };

    const fetchInitialData = async () => {
        try {
            const [roles, floorplans, nodes, buildings] = await Promise.all([
                getRoles().catch(() => []),
                getFloorplans().catch(() => []),
                getGlobalNodes().catch(() => []),
                getBuildings().catch(() => [])
            ]);
            setRolesList(roles);
            setFloorplansList(floorplans);
            setGlobalNodes(nodes);
            setBuildingsList(buildings);
        } catch (err) {
            console.error('Error loading initial mapping data:', err);
        }
    };

    const refreshGlobalNodes = async () => {
        try {
            const nodes = await getGlobalNodes();
            setGlobalNodes(nodes);
        } catch (err) {
            console.error('Failed to refresh global nodes:', err);
        }
    };

    const refreshBuildings = async () => {
        try {
            const b = await getBuildings();
            setBuildingsList(b);
        } catch (err) {
            console.error('Failed to refresh buildings:', err);
        }
    };

    const loadFloorplanData = async (e) => {
        const fpId = typeof e === 'object' && e?.target ? e.target.value : e;
        if (!fpId) return;
        try {
            const graphData = await getGraph(fpId);
            setCurrentFloorplanId(fpId);
            setGraphVersion(graphData.graph_version || 1);

            const currentFp = floorplansList.find(f => String(f.floorplan_id) === String(fpId));
            if (currentFp) {
                setEditBuildingName(currentFp.building_name || '');
                setEditFloorLevel(currentFp.floor_level || '');
                setEditScaleRatio(currentFp.scale_ratio || '1.0');
            }

            fetchWallMask(fpId);

            const img = new window.Image();
            img.src = getFloorplanImageUrl(fpId);

            const idToIndex = {};
            const reactNodes = (graphData.nodes || []).map((n, idx) => {
                idToIndex[n.node_id] = idx;
                return {
                    node_id:       n.node_id,
                    x:             n.coord_x,
                    y:             n.coord_y,
                    room_label:    n.room_label,
                    node_type:     n.node_type,
                    is_accessible: n.is_accessible || 'ALLOW',
                    allowed_roles: n.role_ids || n.allowed_roles || []
                };
            });

            const reactEdges = (graphData.edges || []).map(e => {
                const isCrossFloor = idToIndex[e.destination_node_id] === undefined;
                let customPathPoints = null;
                if (e.custom_path) {
                    try {
                        customPathPoints = typeof e.custom_path === 'string' ? JSON.parse(e.custom_path) : e.custom_path;
                    } catch (_) {
                        customPathPoints = null;
                    }
                }
                const isCustom = !!(customPathPoints && customPathPoints.length >= 2);

                if (isCrossFloor) {
                    return {
                        edge_id:          e.edge_id,
                        start:            idToIndex[e.source_node_id],
                        is_cross_floor:   true,
                        target_node_id:   e.destination_node_id,
                        weight:           parseFloat(e.weight_distance) || 1.0,
                        is_bidirectional: e.is_bidirectional !== false,
                        is_accessible:    e.is_accessible || 'ALLOW',
                        allowed_roles:    e.role_ids || e.allowed_roles || [],
                        isCustom:         false,
                        customPathPoints: null,
                        pathPoints:       null
                    };
                }
                return {
                    edge_id:          e.edge_id,
                    start:            idToIndex[e.source_node_id],
                    end:              idToIndex[e.destination_node_id],
                    weight:           parseFloat(e.weight_distance) || 1.0,
                    is_bidirectional: e.is_bidirectional !== false,
                    is_accessible:    e.is_accessible || 'ALLOW',
                    allowed_roles:    e.role_ids || e.allowed_roles || [],
                    isCustom,
                    customPathPoints,
                    pathPoints:       customPathPoints || null
                };
            }).filter(e => e.start !== undefined && (e.is_cross_floor || e.end !== undefined));

            refreshGlobalNodes();

            img.onload = () => {
                if (onFloorplanLoaded) {
                    onFloorplanLoaded({ img, nodes: reactNodes, edges: reactEdges, floorplan: currentFp });
                }
            };

            img.onerror = () => {
                if (onFloorplanLoaded) {
                    onFloorplanLoaded({ img: null, nodes: reactNodes, edges: reactEdges, floorplan: currentFp });
                }
            };
        } catch (error) {
            console.error('Failed to load map data', error);
        }
    };

    const handleCreateBuildingInline = async () => {
        if (!newBuildingName.trim()) return alert('Enter a building name.');
        try {
            const b = await createBuilding({ building_name: newBuildingName.trim() });
            alert(`Building "${b.building_name}" created.`);
            setNewBuildingName('');
            await refreshBuildings();
            setSelectedBuildingId(String(b.building_id));
        } catch (err) {
            alert('Failed to create building.');
        }
    };

    const handleImageUpload = async (e) => {
        const file = e.target.files[0];
        if (!file || !selectedBuildingId || !floorLevel) {
            return alert('Select Building and enter Floor Level first.');
        }
        setIsUploading(true);
        try {
            const res = await uploadFloorplan({
                buildingId: selectedBuildingId,
                floorLevel: parseInt(floorLevel, 10),
                scaleRatio: parseFloat(scaleRatio) || 1.0,
                file
            });
            alert('Floorplan uploaded successfully.');
            const newFpId = res.floorplan_id;
            setCurrentFloorplanId(newFpId);

            fetchWallMask(newFpId);

            setFloorLevel('');
            setScaleRatio('1.0');
            if (fileInputRef && fileInputRef.current) fileInputRef.current.value = '';

            const floorplans = await getFloorplans();
            setFloorplansList(floorplans);

            if (onUploadSuccess) {
                onUploadSuccess({ floorplan_id: newFpId });
            }
        } catch (error) {
            alert(error.message || 'Upload Failed.');
        } finally {
            setIsUploading(false);
        }
    };

    const handleUpdateFloorplan = async () => {
        if (!currentFloorplanId) return;
        try {
            await patchFloorplan(currentFloorplanId, {
                floor_level: parseInt(editFloorLevel, 10),
                scale_ratio: parseFloat(editScaleRatio)
            });
            alert('Floorplan updated successfully.');
            const floorplans = await getFloorplans();
            setFloorplansList(floorplans);
        } catch (err) {
            alert('Failed to update floorplan details.');
        }
    };

    const handleDeleteMap = async () => {
        if (!currentFloorplanId) return;
        if (!window.confirm('WARNING: Delete this floorplan permanently? All nodes and edges will be lost.')) return;
        try {
            await deleteFloorplan(currentFloorplanId);
            alert('Map deleted successfully.');
            setCurrentFloorplanId(null);
            setWallOverlayImage(null);
            setWallGrid(null);
            const floorplans = await getFloorplans();
            setFloorplansList(floorplans);
            if (onFloorplanCleared) onFloorplanCleared();
        } catch (error) {
            alert(error.message || 'Failed to delete map.');
        }
    };

    const handleSaveMapData = async (nodes, edges) => {
        if (!currentFloorplanId) return alert('Please select a floorplan!');
        try {
            const apiNodes = nodes.map(n => ({
                node_id:       n.node_id || null,
                coord_x:       n.x,
                coord_y:       n.y,
                room_label:    n.room_label || 'Node',
                node_type:     n.node_type || 'CORRIDOR',
                is_accessible: n.is_accessible || 'ALLOW',
                role_ids:      n.allowed_roles || []
            }));

            const apiEdges = edges.map(e => {
                const sourceNodeId = nodes[e.start]?.node_id;
                const destNodeId   = e.is_cross_floor ? e.target_node_id : nodes[e.end]?.node_id;

                let customPathStr = null;
                if (e.isCustom && e.pathPoints && e.pathPoints.length >= 2) {
                    customPathStr = JSON.stringify(e.pathPoints);
                }

                return {
                    edge_id:             e.edge_id || null,
                    source_node_id:      sourceNodeId,
                    destination_node_id: destNodeId,
                    weight_distance:     parseFloat(e.weight) || 1.0,
                    is_accessible:      e.is_accessible || 'ALLOW',
                    is_bidirectional:   e.is_bidirectional !== false,
                    custom_path:        customPathStr,
                    role_ids:           e.allowed_roles || []
                };
            }).filter(e => e.source_node_id && e.destination_node_id);

            const payload = {
                graph_version: graphVersion,
                nodes: apiNodes,
                edges: apiEdges
            };

            const res = await saveGraph(currentFloorplanId, payload);
            setGraphVersion(res.graph_version);
            alert('Map saved successfully!');
            await loadFloorplanData(currentFloorplanId);
        } catch (error) {
            alert(error.message || 'Failed to save map data.');
        }
    };

    return {
        currentFloorplanId,
        setCurrentFloorplanId,
        floorplansList,
        buildingsList,
        globalNodes,
        setGlobalNodes,
        rolesList,
        isUploading,
        selectedBuildingId, setSelectedBuildingId,
        newBuildingName, setNewBuildingName,
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
        refreshBuildings,
        loadFloorplanData,
        fetchWallMask,
        handleCreateBuildingInline,
        handleImageUpload,
        handleUpdateFloorplan,
        handleDeleteMap,
        handleSaveMapData
    };
}
