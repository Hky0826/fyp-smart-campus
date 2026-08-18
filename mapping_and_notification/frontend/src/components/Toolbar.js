/**
 * @file Toolbar.js
 * @description Horizontal toolbar situated above the Konva canvas.
 *
 * Manages tool selection (add nodes, draw paths, etc.), the reset view button,
 * toggling side panels (Navigation, Notifications), saving to the DB, and
 * triggering the Phase 1 AI Floorplan Analysis.
 */

import React from 'react';

export function Toolbar({
    appMode, setAppMode,
    mode, selectTool,
    currentFloorplanId,
    handleDeleteSelected,
    navPanelOpen, setNavPanelOpen,
    notifPanelOpen, setNotifPanelOpen,
    handleSaveMapData,
    nodes, edges,
    // Phase 1 AI Analysis
    handleAiAnalyze,
    isAnalyzing,
}) {
    return (
        <div className="flex flex-col gap-3">
            {/* Block 1: Mode Switch */}
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-1.5 shadow-md flex justify-center">
                <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-800">
                    <button
                        onClick={() => setAppMode('edit')}
                        className={`py-1.5 px-6 rounded-md text-xs font-bold transition-all duration-200 flex items-center gap-2 ${
                            appMode === 'edit'
                                ? 'bg-blue-600/20 text-blue-400 border border-blue-500/50 shadow-sm'
                                : 'text-slate-400 hover:text-slate-200 border border-transparent'
                        }`}
                    >
                        <span>✏️</span> Edit
                    </button>
                    <button
                        onClick={() => {
                            setAppMode('test');
                            setNavPanelOpen(false);
                            setNotifPanelOpen(false);
                        }}
                        className={`py-1.5 px-6 rounded-md text-xs font-bold transition-all duration-200 flex items-center gap-2 ${
                            appMode === 'test'
                                ? 'bg-teal-600/20 text-teal-400 border border-teal-500/50 shadow-sm'
                                : 'text-slate-400 hover:text-slate-200 border border-transparent'
                        }`}
                    >
                        <span>🧭</span> Test
                    </button>
                </div>
            </div>

            {/* Block 2: Operation Toolbar */}
            {currentFloorplanId && (
                <div className="bg-slate-900 border border-slate-800 rounded-lg p-1.5 shadow-md flex gap-2 items-center justify-between">
                    <div className="flex-1 flex flex-wrap gap-1 items-center">
                        {appMode === 'edit' ? (
                            <>
                                <button 
                                    onClick={() => selectTool('add_nodes', currentFloorplanId)} 
                                    className={`flex items-center gap-1 py-1 px-2 rounded-md text-[10px] font-bold transition-all duration-200 cursor-pointer border ${
                                        mode === 'add_nodes' 
                                            ? 'bg-blue-600/25 border-blue-500 text-blue-400 shadow-md shadow-blue-500/5' 
                                            : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                                    }`}
                                >
                                    <span>📍</span> Add Nodes
                                </button>
                                <button 
                                    onClick={() => selectTool('draw_paths', currentFloorplanId)} 
                                    className={`flex items-center gap-1 py-1 px-2 rounded-md text-[10px] font-bold transition-all duration-200 cursor-pointer border ${
                                        mode === 'draw_paths' 
                                            ? 'bg-purple-600/25 border-purple-500 text-purple-400 shadow-md shadow-purple-500/5' 
                                            : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                                    }`}
                                >
                                    <span>🔗</span> Draw Edges
                                </button>
                                <button 
                                    onClick={() => selectTool('delete_element', currentFloorplanId)} 
                                    className={`flex items-center gap-1 py-1 px-2 rounded-md text-[10px] font-bold transition-all duration-200 cursor-pointer border ${
                                        mode === 'delete_element' 
                                            ? 'bg-red-600/25 border-red-500 text-red-400 shadow-md shadow-red-500/5' 
                                            : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-red-400 hover:border-red-500/50'
                                    }`}
                                >
                                    <span>🗑️</span> Delete Element
                                </button>

                                {/* Separator */}
                                <div className="w-px h-5 bg-slate-700 mx-0.5" />

                                <button
                                    id="ai-analyze-btn"
                                    onClick={handleAiAnalyze}
                                    disabled={isAnalyzing}
                                    className={`py-1 px-3 rounded-md text-[10px] font-bold flex items-center gap-1.5 border transition-all duration-200 ${
                                        isAnalyzing
                                            ? 'bg-teal-900/30 border-teal-700 text-teal-500 cursor-not-allowed opacity-70'
                                            : 'bg-teal-600/20 border-teal-500 text-teal-300 hover:bg-teal-600/40 hover:text-white cursor-pointer shadow-md shadow-teal-900/20'
                                    }`}
                                    title="Run AI Room Detection and automatically generate room nodes"
                                >
                                    {isAnalyzing ? (
                                        <>
                                            <svg className="animate-spin h-3 w-3 text-teal-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                            </svg>
                                            Analyzing…
                                        </>
                                    ) : (
                                        <><span>🤖</span> Auto-Generate Nodes (AI)</>
                                    )}
                                </button>
                            </>
                        ) : (
                            <>
                                <button
                                    onClick={() => { setNavPanelOpen(p => !p); setNotifPanelOpen(false); }}
                                    className={`flex items-center gap-1.5 py-1 px-3 rounded-md text-[10px] font-bold transition-all duration-200 cursor-pointer border ${
                                        navPanelOpen
                                            ? 'bg-teal-600/25 border-teal-500 text-teal-400 shadow-md shadow-teal-500/10'
                                            : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                                    }`}
                                    title="Navigation Tester"
                                >
                                    <span>🧭</span> Route
                                </button>
                                <button
                                    onClick={() => { setNotifPanelOpen(p => !p); setNavPanelOpen(false); }}
                                    className={`flex items-center gap-1.5 py-1 px-3 rounded-md text-[10px] font-bold transition-all duration-200 cursor-pointer border ${
                                        notifPanelOpen
                                            ? 'bg-indigo-600/25 border-indigo-500 text-indigo-400 shadow-md shadow-indigo-500/10'
                                            : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                                    }`}
                                    title="Notification Tester"
                                >
                                    <span>🔔</span> Notification
                                </button>
                            </>
                        )}
                    </div>

                    <div className="flex-shrink-0 flex gap-2 items-center">
                        <button 
                            onClick={() => handleSaveMapData(nodes, edges)} 
                            className="py-1 px-3 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-bold rounded-md text-[10px] flex items-center gap-1.5 shadow-lg shadow-blue-600/10 cursor-pointer transition-all duration-200 border-0"
                        >
                            <span>💾</span> Save Map
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
