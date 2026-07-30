import React from 'react';

export function Toolbar({
    mode, selectTool,
    currentFloorplanId,
    handleResetView,
    navPanelOpen, setNavPanelOpen,
    notifPanelOpen, setNotifPanelOpen,
    handleSaveMapData,
    nodes, edges
}) {
    return (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-1.5 shadow-md flex gap-2 items-center justify-between">
            <div className="flex-1 flex items-center gap-1.5">
                <button 
                  onClick={() => selectTool('add_nodes', currentFloorplanId)} 
                  title="Add Nodes (📍)"
                  className={`flex items-center gap-1 py-1 px-2 rounded-md text-xs font-bold transition-all duration-200 cursor-pointer border ${
                    mode === 'add_nodes' 
                      ? 'bg-blue-600/25 border-blue-500 text-blue-400 shadow-md shadow-blue-500/5' 
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span>📍</span> <span className="hidden sm:inline text-[10px]">Add Nodes</span>
                </button>
                <button 
                  onClick={() => selectTool('draw_paths', currentFloorplanId)} 
                  title="Draw Paths (🔗)"
                  className={`flex items-center gap-1 py-1 px-2 rounded-md text-xs font-bold transition-all duration-200 cursor-pointer border ${
                    mode === 'draw_paths' 
                      ? 'bg-purple-600/25 border-purple-500 text-purple-400 shadow-md shadow-purple-500/5' 
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span>🔗</span> <span className="hidden sm:inline text-[10px]">Draw Paths</span>
                </button>
                <button 
                  onClick={() => selectTool('edit_props', currentFloorplanId)} 
                  title="Edit Properties (✏️)"
                  className={`flex items-center gap-1 py-1 px-2 rounded-md text-xs font-bold transition-all duration-200 cursor-pointer border ${
                    mode === 'edit_props' 
                      ? 'bg-amber-600/25 border-amber-500 text-amber-400 shadow-md shadow-amber-500/5' 
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span>✏️</span> <span className="hidden sm:inline text-[10px]">Edit Props</span>
                </button>
                <button 
                  onClick={() => selectTool('delete_element', currentFloorplanId)} 
                  title="Delete Element (🗑️)"
                  className={`flex items-center gap-1 py-1 px-2 rounded-md text-xs font-bold transition-all duration-200 cursor-pointer border ${
                    mode === 'delete_element' 
                      ? 'bg-red-600/25 border-red-500 text-red-400 shadow-md shadow-red-500/5' 
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span>🗑️</span> <span className="hidden sm:inline text-[10px]">Delete</span>
                </button>

                {currentFloorplanId && (
                  <button 
                    onClick={handleResetView} 
                    className="py-1 px-2 bg-slate-950 hover:bg-slate-850 border border-slate-800 text-slate-300 font-bold rounded-md text-xs flex items-center gap-1 cursor-pointer transition-all duration-200"
                    title="Fit Floor Plan to Workspace (🔄)"
                  >
                    <span>🔄</span> <span className="hidden md:inline text-[10px]">Reset</span>
                  </button>
                )}

                {currentFloorplanId && <div className="w-px h-4 bg-slate-800 mx-0.5" />}

                {currentFloorplanId && (
                  <button
                    onClick={() => { setNavPanelOpen(p => !p); setNotifPanelOpen(false); }}
                    className={`flex items-center gap-1 py-1 px-2 rounded-md text-xs font-bold transition-all duration-200 cursor-pointer border ${
                      navPanelOpen
                        ? 'bg-teal-600/25 border-teal-500 text-teal-400 shadow-md shadow-teal-500/10'
                        : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                    title="Navigation Tester (🧭)"
                  >
                    <span>🧭</span> <span className="hidden md:inline text-[10px]">Navigate</span>
                  </button>
                )}
                {currentFloorplanId && (
                  <button
                    onClick={() => { setNotifPanelOpen(p => !p); setNavPanelOpen(false); }}
                    className={`flex items-center gap-1 py-1 px-2 rounded-md text-xs font-bold transition-all duration-200 cursor-pointer border ${
                      notifPanelOpen
                        ? 'bg-indigo-600/25 border-indigo-500 text-indigo-400 shadow-md shadow-indigo-500/10'
                        : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                    title="Notification Hub (🔔)"
                  >
                    <span>🔔</span> <span className="hidden md:inline text-[10px]">Notifications</span>
                  </button>
                )}
            </div>
            
            <div className="flex-shrink-0 flex gap-2">
                <button 
                  onClick={() => handleSaveMapData(nodes, edges)} 
                  title="Save Map Data (💾)"
                  className="py-1 px-2 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-bold rounded-md text-[10px] flex items-center gap-1 shadow-lg shadow-blue-600/10 cursor-pointer transition-all duration-200 border-0"
                >
                  <span>💾</span> <span className="hidden sm:inline">Save Map</span>
                </button>
            </div>
        </div>
    );
}
