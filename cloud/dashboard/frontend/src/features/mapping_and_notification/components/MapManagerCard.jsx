import React from 'react';

export function MapManagerCard({
    buildingsList,
    selectedBuildingId, setSelectedBuildingId,
    newBuildingName, setNewBuildingName,
    handleCreateBuildingInline,
    floorLevel, setFloorLevel,
    scaleRatio, setScaleRatio,
    fileInputRef,
    handleImageUpload,
    isUploading,
    
    floorplansList,
    currentFloorplanId,
    loadFloorplanData,
    editBuildingName, setEditBuildingName,
    editFloorLevel, setEditFloorLevel,
    editScaleRatio, setEditScaleRatio,
    handleUpdateFloorplan,
    handleDeleteMap,
    
    wallSensitivity, setWallSensitivity,
    showWallOverlay, setShowWallOverlay,
    fetchWallMask,
    isFetchingWallMask,
    mode, selectTool,
    handleSaveMapData,
    nodes, edges
}) {
    const [showNewBuildingForm, setShowNewBuildingForm] = React.useState(false);

    return (
        <div className="flex flex-col gap-3">
            {/* CARD 1: UPLOAD FLOORPLAN */}
            <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-3 shadow-xl flex flex-col gap-2.5">
                <h3 className="text-[10px] font-bold text-slate-300 uppercase tracking-wider">
                    UPLOAD FLOORPLAN
                </h3>
                
                <div className="flex flex-col gap-1.5">
                    <div className="flex justify-between items-center">
                        <label className="text-[9px] text-slate-400 font-semibold">Building</label>
                        <button
                            type="button"
                            onClick={() => setShowNewBuildingForm(!showNewBuildingForm)}
                            className="text-[9px] text-teal-400 hover:underline bg-transparent border-0 cursor-pointer font-semibold"
                        >
                            {showNewBuildingForm ? 'Select Existing' : '+ New Building'}
                        </button>
                    </div>
                    {showNewBuildingForm ? (
                        <div className="flex gap-1">
                            <input
                                type="text"
                                placeholder="New building name..."
                                value={newBuildingName}
                                onChange={e => setNewBuildingName(e.target.value)}
                                className="bg-slate-950 border border-slate-800 rounded-md px-2 py-1 text-[10px] text-white focus:outline-none focus:border-teal-500 placeholder-slate-600 flex-1 h-7"
                            />
                            <button
                                type="button"
                                onClick={handleCreateBuildingInline}
                                className="py-1 px-2.5 bg-teal-600 hover:bg-teal-500 text-white font-bold rounded text-[10px] cursor-pointer border-0"
                            >
                                Add
                            </button>
                        </div>
                    ) : (
                        <select
                            value={selectedBuildingId}
                            onChange={e => setSelectedBuildingId(e.target.value)}
                            className="bg-slate-950 border border-slate-800 rounded-md px-2 py-1 text-[10px] text-slate-200 focus:outline-none focus:border-teal-500 cursor-pointer h-7 w-full"
                        >
                            <option value="">Building ID / Name</option>
                            {(buildingsList || []).map(b => (
                                <option key={b.building_id} value={b.building_id}>
                                    {b.building_name} (ID: {b.building_id})
                                </option>
                            ))}
                        </select>
                    )}
                </div>

                <div className="grid grid-cols-2 gap-2">
                    <div className="flex flex-col gap-1">
                        <label className="text-[9px] text-slate-400 font-semibold">Floor Level</label>
                        <input 
                            type="number" 
                            placeholder="Floor Level (e.g. 1)" 
                            value={floorLevel} 
                            onChange={e => setFloorLevel(e.target.value)} 
                            className="bg-slate-950 border border-slate-800 rounded-md px-2 py-1 text-[10px] text-white focus:outline-none focus:border-teal-500 placeholder-slate-600 h-7" 
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[9px] text-slate-400 font-semibold">Scale (px to m)</label>
                        <input 
                            type="number" 
                            step="0.1" 
                            value={scaleRatio} 
                            onChange={e => setScaleRatio(e.target.value)} 
                            className="bg-slate-950 border border-slate-800 rounded-md px-2 py-1 text-[10px] text-white focus:outline-none focus:border-teal-500 h-7" 
                        />
                    </div>
                </div>

                <div className="flex flex-col gap-1 mt-0.5">
                    <input 
                        type="file" 
                        ref={fileInputRef} 
                        accept="image/png, image/jpeg" 
                        onChange={handleImageUpload} 
                        disabled={isUploading} 
                        className="hidden" 
                        id="floorplan-file-input"
                    />
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => fileInputRef.current && fileInputRef.current.click()}
                            className="py-1 px-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold rounded text-[9px] cursor-pointer border border-slate-700"
                        >
                            Choose File
                        </button>
                        <span className="text-[9px] text-slate-500 truncate max-w-[120px]">
                            {fileInputRef.current && fileInputRef.current.files?.[0]?.name || 'No file chosen'}
                        </span>
                    </div>
                </div>

                <button
                    type="button"
                    onClick={handleImageUpload}
                    disabled={isUploading}
                    className="w-full py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-bold rounded-md text-[10px] transition-all cursor-pointer border-0 shadow-md shadow-emerald-600/10 mt-1"
                >
                    {isUploading ? 'Uploading...' : 'Upload Image'}
                </button>

                {currentFloorplanId && (
                    <button
                        type="button"
                        onClick={handleDeleteMap}
                        className="w-full py-1.5 bg-rose-950/80 hover:bg-rose-900 border border-rose-800/80 text-rose-300 font-bold rounded-md text-[10px] transition-all cursor-pointer"
                    >
                        Delete Floorplan
                    </button>
                )}
            </div>

            {/* CARD 2: EDITOR CONTROLS */}
            <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-3 shadow-xl flex flex-col gap-2.5">
                <h3 className="text-[10px] font-bold text-slate-300 uppercase tracking-wider">
                    EDITOR CONTROLS
                </h3>

                {/* Mode Pills */}
                <div className="grid grid-cols-2 gap-1.5">
                    <button
                        type="button"
                        onClick={() => selectTool && selectTool('edit_props', currentFloorplanId)}
                        className={`py-1 px-1.5 rounded-md text-[10px] font-bold transition-all cursor-pointer border text-center ${
                            mode === 'edit_props'
                                ? 'bg-indigo-600 border-indigo-500 text-white shadow-md'
                                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                        }`}
                    >
                        Select
                    </button>
                    <button
                        type="button"
                        onClick={() => selectTool && selectTool('add_nodes', currentFloorplanId)}
                        className={`py-1 px-1.5 rounded-md text-[10px] font-bold transition-all cursor-pointer border text-center ${
                            mode === 'add_nodes'
                                ? 'bg-blue-600 border-blue-500 text-white shadow-md'
                                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                        }`}
                    >
                        + Node
                    </button>
                    <button
                        type="button"
                        onClick={() => selectTool && selectTool('draw_paths', currentFloorplanId)}
                        className={`py-1 px-1.5 rounded-md text-[10px] font-bold transition-all cursor-pointer border text-center ${
                            mode === 'draw_paths'
                                ? 'bg-purple-600 border-purple-500 text-white shadow-md'
                                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                        }`}
                    >
                        + Edge
                    </button>
                    <button
                        type="button"
                        onClick={() => selectTool && selectTool('delete_element', currentFloorplanId)}
                        className={`py-1 px-1.5 rounded-md text-[10px] font-bold transition-all cursor-pointer border text-center ${
                            mode === 'delete_element'
                                ? 'bg-rose-600 border-rose-500 text-white shadow-md'
                                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                        }`}
                    >
                        Delete
                    </button>
                </div>

                <button
                    type="button"
                    onClick={() => handleSaveMapData && handleSaveMapData(nodes, edges)}
                    className="w-full py-1.5 bg-sky-600 hover:bg-sky-500 text-white font-bold rounded-md text-[10px] transition-all cursor-pointer border-0 shadow-md shadow-sky-600/10"
                >
                    Save Graph v1
                </button>

                <button
                    type="button"
                    onClick={() => {
                        const newOverlay = !showWallOverlay;
                        setShowWallOverlay(newOverlay);
                        if (newOverlay && fetchWallMask && currentFloorplanId) {
                            fetchWallMask(currentFloorplanId, wallSensitivity);
                        }
                    }}
                    className={`w-full py-1.5 font-bold rounded-md text-[10px] transition-all cursor-pointer border-0 shadow-md ${
                        showWallOverlay
                            ? 'bg-amber-500 hover:bg-amber-400 text-slate-950 shadow-amber-500/20'
                            : 'bg-amber-600 hover:bg-amber-500 text-white shadow-amber-600/10'
                    }`}
                >
                    Wall Grid Overlay
                </button>

                {showWallOverlay && currentFloorplanId && (
                    <div className="flex flex-col gap-1 pt-1.5 border-t border-slate-800">
                        <div className="flex justify-between items-center text-[9px] text-slate-400">
                            <span>Sensitivity</span>
                            <span>{wallSensitivity}</span>
                        </div>
                        <input
                            type="range"
                            min="0"
                            max="255"
                            value={wallSensitivity}
                            onChange={(e) => setWallSensitivity(parseInt(e.target.value, 10))}
                            onMouseUp={() => fetchWallMask && fetchWallMask(currentFloorplanId, wallSensitivity)}
                            onTouchEnd={() => fetchWallMask && fetchWallMask(currentFloorplanId, wallSensitivity)}
                            disabled={isFetchingWallMask}
                            className="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                        />
                    </div>
                )}
            </div>
        </div>
    );
}
