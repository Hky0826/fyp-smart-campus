import React from 'react';

export function MapManagerCard({
    // Form fields
    buildingName, setBuildingName,
    floorLevel, setFloorLevel,
    scaleRatio, setScaleRatio,
    fileInputRef,
    handleImageUpload,
    isUploading,
    
    // Manage maps
    floorplansList,
    currentFloorplanId,
    loadFloorplanData,
    editBuildingName, setEditBuildingName,
    editFloorLevel, setEditFloorLevel,
    editScaleRatio, setEditScaleRatio,
    handleUpdateFloorplan,
    handleDeleteMap,
    
    // Wall Overlay Settings
    wallSensitivity, setWallSensitivity,
    showWallOverlay, setShowWallOverlay,
    fetchWallMask,
    isFetchingWallMask,
    // Nodes for committing draft
    nodes, setNodes
}) {
    return (
        <>
            {/* Create Map Card */}
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 shadow-xl">
                <h3 className="text-xs font-bold text-white mb-2 border-b border-slate-800 pb-1.5 flex items-center gap-1.5">
                    <svg className="w-3.5 h-3.5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" /></svg>
                    Create New Map
                </h3>
                <div className="flex flex-col gap-2.5">
                    <div className="flex flex-col gap-1">
                        <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Building Name</label>
                        <input type="text" placeholder="e.g. TTS, ASB" value={buildingName} onChange={e => setBuildingName(e.target.value)} className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-white focus:outline-none focus:border-blue-500 placeholder-slate-700" />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                        <div className="flex flex-col gap-1">
                            <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Floor Level</label>
                            <input type="number" placeholder="e.g. 1" value={floorLevel} onChange={e => setFloorLevel(e.target.value)} className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-white focus:outline-none focus:border-blue-500 placeholder-slate-700" />
                        </div>
                        <div className="flex flex-col gap-1">
                            <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Scale (px to m)</label>
                            <input type="number" step="0.1" value={scaleRatio} onChange={e => setScaleRatio(e.target.value)} className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-white focus:outline-none focus:border-blue-500" />
                        </div>
                    </div>
                    <div className="mt-0.5">
                        <label className="block text-[9px] font-bold text-slate-400 uppercase tracking-wider mb-1">Select Map Image</label>
                        <input type="file" ref={fileInputRef} accept="image/png, image/jpeg" onChange={handleImageUpload} disabled={isUploading} className="block w-full text-[9px] text-slate-500 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-[9px] file:font-bold file:bg-blue-600 file:text-white hover:file:bg-blue-500 file:cursor-pointer" />
                    </div>
                </div>
            </div>

            {/* Manage Maps Card */}
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 shadow-xl">
                <h3 className="text-xs font-bold text-white mb-2 border-b border-slate-800 pb-1.5 flex items-center gap-1.5">
                    <svg className="w-3.5 h-3.5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>
                    Manage Existing Maps
                </h3>
                <select onChange={loadFloorplanData} className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-blue-500 w-full mb-2.5 cursor-pointer" value={currentFloorplanId || ""}>
                    <option value="" disabled>-- Select a Floorplan --</option>
                    {floorplansList.map(fp => ( <option key={fp.floorplan_id} value={fp.floorplan_id}>{fp.building_name} - Floor {fp.floor_level} (ID: {fp.floorplan_id})</option> ))}
                </select>
                {currentFloorplanId && (
                    <div className="flex flex-col gap-2.5 bg-slate-950 p-2.5 border border-slate-850 rounded-lg">
                        <div className="flex flex-col gap-0.5"><label className="text-[8px] font-bold text-slate-500 uppercase tracking-wider">Edit Building Name</label><input type="text" value={editBuildingName} onChange={e => setEditBuildingName(e.target.value)} className="bg-slate-900 border border-slate-800 rounded-md p-1 text-[11px] text-white focus:outline-none focus:border-blue-500" /></div>
                        <div className="grid grid-cols-2 gap-2">
                            <div className="flex flex-col gap-0.5"><label className="text-[8px] font-bold text-slate-500 uppercase tracking-wider">Edit Floor</label><input type="number" value={editFloorLevel} onChange={e => setEditFloorLevel(e.target.value)} className="bg-slate-900 border border-slate-800 rounded-md p-1 text-[11px] text-white focus:outline-none focus:border-blue-500" /></div>
                            <div className="flex flex-col gap-0.5"><label className="text-[8px] font-bold text-slate-500 uppercase tracking-wider">Edit Scale</label><input type="number" step="0.1" value={editScaleRatio} onChange={e => setEditScaleRatio(e.target.value)} className="bg-slate-900 border border-slate-800 rounded-md p-1 text-[11px] text-white focus:outline-none focus:border-blue-500" /></div>
                        </div>
                        <div className="flex gap-2 mt-0.5">
                            <button onClick={handleUpdateFloorplan} className="flex-1 py-1 bg-blue-600 hover:bg-blue-500 text-white border-0 text-[11px] font-bold rounded cursor-pointer transition-all duration-200">Update</button>
                            <button onClick={handleDeleteMap} className="py-1 px-2 bg-red-950 border border-red-800 text-red-400 hover:bg-red-900 text-[11px] font-bold rounded cursor-pointer transition-all duration-200">Delete</button>
                        </div>
                    </div>
                )}
            </div>

            {/* Wall Detection Settings panel */}
            {currentFloorplanId && (
                <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 shadow-xl flex flex-col gap-2.5 mt-4">
                    <h3 className="text-xs font-bold text-white mb-0.5 border-b border-slate-800 pb-1.5 flex items-center gap-1.5">
                        <svg className="w-3.5 h-3.5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" /></svg>
                        Wall Overlay Settings
                    </h3>
                    <div className="flex flex-col gap-2 mt-1">
                        <label className="flex items-center gap-2 cursor-pointer">
                            <input 
                                type="checkbox" 
                                checked={showWallOverlay} 
                                onChange={(e) => setShowWallOverlay(e.target.checked)}
                                className="w-3 h-3 text-blue-600 bg-slate-800 border-slate-600 rounded focus:ring-blue-500"
                            />
                            <span className="text-[11px] text-slate-300 font-medium">Show Wall Mask Overlay</span>
                        </label>
                        
                        <div className="flex flex-col gap-1.5 pt-1 border-t border-slate-800">
                            <div className="flex justify-between items-center text-[10px] text-slate-400">
                                <span>Wall Sensitivity</span>
                                <span>{wallSensitivity}</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="255"
                                value={wallSensitivity}
                                onChange={(e) => setWallSensitivity(parseInt(e.target.value))}
                                onMouseUp={() => fetchWallMask(currentFloorplanId, wallSensitivity)}
                                onTouchEnd={() => fetchWallMask(currentFloorplanId, wallSensitivity)}
                                disabled={!showWallOverlay || isFetchingWallMask}
                                className="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer disabled:opacity-50"
                            />
                        </div>
                    </div>
                </div>
            )}


        </>
    );
}
