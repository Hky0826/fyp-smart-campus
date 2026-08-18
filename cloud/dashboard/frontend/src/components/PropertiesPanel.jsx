/**
 * @file PropertiesPanel.js
 * @description The main properties inspector shown when in 'edit_props' mode.
 *
 * Renders contextual panels for editing Node properties, Edge properties,
 * and Cross-floor transitions.
 */

import React from 'react';
import { NodeSelector } from './NodeSelector/NodeSelector';

export function PropertiesPanel({
    appMode, handleDeleteSelected,
    selectedElement,
    setSelectedElement,
    activeObj,
    isTransitionNode,
    activeNodeTab, setActiveNodeTab,
    updateProperty,
    handleRoleToggle,
    rolesList,
    edges, nodes, globalNodes, currentFloorplanId,
    transitionTargetId, setTransitionTargetId,
    transitionWeight, setTransitionWeight,
    transitionIsAccessible, setTransitionIsAccessible,
    transitionIsBidirectional, setTransitionIsBidirectional,
    currentBuildingName, currentFloorLevel,
    handleUpdateTransition,
    handleDeleteTransition,
    handleCreateTransition,
    triggerSelectedEdgeAStar,
    resetSelectedEdgeToStraight
}) {
    // We no longer support draft_node edit properties
    const currentActiveObj = activeObj;

    if (!currentActiveObj) return null;

    const handleUpdateProperty = (key, value) => {
        updateProperty(key, value);
    };

    return (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl flex flex-col gap-4 max-h-[85vh] overflow-y-auto">
            <div className="flex justify-between items-center border-b border-slate-800 pb-2.5">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                    {selectedElement.type === 'node' ? '📍 Node Properties' : '🔗 Path Properties'}
                </h3>
                <div className="flex gap-2">
                    {appMode === 'edit' && (
                        <button 
                            onClick={handleDeleteSelected} 
                            className="text-[10px] text-red-400 hover:text-red-300 font-bold bg-red-950/30 px-2 py-1 rounded-md border border-red-900/50 cursor-pointer transition-colors"
                        >
                            Delete
                        </button>
                    )}
                    <button 
                        onClick={() => setSelectedElement({ type: null, index: null })} 
                        className="text-[10px] text-slate-500 hover:text-slate-300 font-bold bg-slate-950 px-2 py-1 rounded-md border border-slate-800 cursor-pointer"
                    >
                        Close
                    </button>
                </div>
            </div>
            
            {/* --- NODE PANEL UI --- */}
            {(selectedElement.type === 'node') && (
                <div className="flex flex-col gap-4 border-none p-0 m-0">
                    {/* Segmented Control / Tabs for Transition Node types */}
                    {isTransitionNode && (
                        <div className="flex border-b border-slate-800 mb-2">
                            <button
                                type="button"
                                onClick={() => setActiveNodeTab('general')}
                                className={`flex-1 pb-2 text-[10px] font-bold uppercase tracking-wider transition-all duration-200 border-b-2 ${
                                    activeNodeTab === 'general' 
                                        ? 'border-blue-500 text-blue-400 font-extrabold' 
                                        : 'border-transparent text-slate-500 hover:text-slate-300'
                                }`}
                            >
                                General
                            </button>
                            <button
                                type="button"
                                onClick={() => setActiveNodeTab('transition')}
                                className={`flex-1 pb-2 text-[10px] font-bold uppercase tracking-wider transition-all duration-200 border-b-2 ${
                                    activeNodeTab === 'transition' 
                                        ? 'border-purple-500 text-purple-400 font-extrabold' 
                                        : 'border-transparent text-slate-500 hover:text-slate-300'
                                }`}
                            >
                                🔗 Linker
                            </button>
                        </div>
                    )}

                    {/* AI GENERATED NODE REVIEW BADGE */}
                    {currentActiveObj.ai_generated && (
                        <div className={`rounded-lg border p-3 flex flex-col gap-2 ${
                            currentActiveObj.review_status === 'PENDING'
                                ? 'bg-teal-950/50 border-teal-800/60'
                                : 'bg-cyan-950/40 border-cyan-800/60'
                        }`}>
                            <div className="flex items-center justify-between">
                                <span className={`text-[10px] font-extrabold uppercase tracking-widest flex items-center gap-1.5 ${
                                    currentActiveObj.review_status === 'PENDING' ? 'text-teal-400' : 'text-cyan-400'
                                }`}>
                                    <span>🤖</span>
                                    AI Generated
                                </span>
                                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${
                                    currentActiveObj.review_status === 'PENDING'
                                        ? 'bg-teal-700/40 text-teal-300'
                                        : 'bg-cyan-700/40 text-cyan-300'
                                }`}>
                                    {currentActiveObj.review_status || 'PENDING'}
                                </span>
                            </div>

                            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                                <div className="flex flex-col gap-0.5">
                                    <span className="text-[9px] text-slate-500 uppercase tracking-wider">Confidence</span>
                                    <div className="flex items-center gap-1.5">
                                        <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-teal-500 rounded-full transition-all"
                                                style={{ width: `${Math.round((currentActiveObj.ai_confidence || 0) * 100)}%` }}
                                            />
                                        </div>
                                        <span className="text-[10px] font-bold text-white">
                                            {Math.round((currentActiveObj.ai_confidence || 0) * 100)}%
                                        </span>
                                    </div>
                                </div>
                                <div className="flex flex-col gap-0.5">
                                    <span className="text-[9px] text-slate-500 uppercase tracking-wider">Source</span>
                                    <span className="text-[10px] text-slate-300 font-medium">
                                        {currentActiveObj.ai_source === 'room_detection+ocr'
                                            ? 'Room + OCR'
                                            : 'Room Detection'}
                                    </span>
                                </div>
                            </div>

                            <p className="text-[9px] text-slate-500 leading-relaxed">
                                {currentActiveObj.review_status === 'PENDING'
                                    ? 'Review this node. Edit the label, move it, or adjust its type. Changes will mark it as Modified.'
                                    : 'You have reviewed this node. Save the map to keep your changes.'}
                            </p>
                        </div>
                    )}

                    {/* PANEL 1: General Node Properties */}
                    {(!isTransitionNode || activeNodeTab === 'general') && (
                        <div className="flex flex-col gap-4">
                            <div className="flex flex-col gap-1.5">
                                <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Room Label</label>
                                <input type="text" value={currentActiveObj.room_label || ''} onChange={e => handleUpdateProperty('room_label', e.target.value)} className="bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-blue-500" />
                            </div>
                            
                            <div className="flex flex-col gap-1.5">
                                <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Node Type</label>
                                <select value={currentActiveObj.node_type || 'OTHER'} onChange={e => handleUpdateProperty('node_type', e.target.value)} className="bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-blue-500 cursor-pointer">
                                    {['CLASSROOM', 'CORRIDOR', 'ENTRANCE', 'STAIRWELL', 'ELEVATOR', 'FOOD', 'OFFICE', 'FACILITIES', 'HALL', 'WASHROOM', 'OUTDOOR', 'SOCIAL SPACES', 'OTHER'].map(t => <option key={t} value={t}>{t}</option>)}
                                </select>
                            </div>
                            
                            <div className="flex items-center gap-3 pt-1">
                                <input 
                                    type="checkbox" 
                                    id="node-accessible"
                                    checked={currentActiveObj.is_accessible === 'ALLOW'} 
                                    onChange={e => handleUpdateProperty('is_accessible', e.target.checked ? 'ALLOW' : 'DENY')} 
                                    className="w-4 h-4 rounded border-slate-800 bg-slate-950 text-blue-600 focus:ring-blue-500 accent-blue-500 cursor-pointer" 
                                />
                                <label htmlFor="node-accessible" className="text-xs font-bold text-slate-300 uppercase select-none cursor-pointer">Area is Accessible</label>
                            </div>

                            {/* Node RBAC */}
                            <div className="border-t border-slate-800 pt-3 flex flex-col gap-2">
                                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Allowed Campus Roles</h4>
                                <p className="text-[10px] text-slate-500 leading-normal mb-1">Select the campus roles permitted to route through this point.</p>
                                <div className="flex flex-col gap-2 bg-slate-950 p-2.5 rounded-xl border border-slate-850">
                                    {rolesList.map(role => (
                                        <label key={role.role_id} className="flex items-center gap-2 text-xs font-medium text-slate-300 cursor-pointer select-none">
                                            <input type="checkbox" checked={(currentActiveObj.allowed_roles || []).includes(role.role_id)} onChange={() => handleRoleToggle(role.role_id)} className="w-3.5 h-3.5 rounded border-slate-800 bg-slate-950 accent-blue-500" />
                                            {role.role_name}
                                        </label>
                                    ))}
                                </div>
                            </div>


                        </div>
                    )}
                    {/* PANEL 2: Transition Linker (Conditional on Tab and Type) */}
                    {isTransitionNode && activeNodeTab === 'transition' && (() => {
                        const existingTransitionIndex = edges.findIndex(e => e.start === selectedElement.index && e.is_cross_floor);
                        const hasExistingTransition = existingTransitionIndex !== -1;
                        const existingEdge = hasExistingTransition ? edges[existingTransitionIndex] : null;

                        let targetNode = null;
                        if (hasExistingTransition) {
                            targetNode = globalNodes.find(gn => gn.node_id === existingEdge.target_node_id);
                        }

                        const startNode = nodes[selectedElement.index];
                        const targetNodeId = hasExistingTransition ? existingEdge.target_node_id : transitionTargetId;
                        const startRoles = startNode?.allowed_roles || [];
                        const targetNodeObj = globalNodes.find(gn => Number(gn.node_id) === Number(targetNodeId));
                        const targetRoles = targetNodeObj 
                            ? (typeof targetNodeObj.allowed_roles === 'string' 
                                ? targetNodeObj.allowed_roles.split(',').map(Number) 
                                : targetNodeObj.allowed_roles || []) 
                            : [];
                        const derivedTransitionRoles = startRoles.filter(r => targetRoles.includes(r));

                        return (
                            <div className="flex flex-col gap-3">
                                <h4 className="text-xs font-bold text-purple-400 uppercase tracking-wider">
                                    {hasExistingTransition ? '🔗 Transition Path Properties' : '🔗 Transition Linker (Cross-Map Edge)'}
                                </h4>
                                <p className="text-[10px] text-slate-500 leading-normal mb-1">
                                    {hasExistingTransition 
                                        ? 'Modify the cross-floor navigation link attributes below.' 
                                        : 'Connect this node to another floorplan.'}
                                </p>
                                
                                {/* 1. Target Destination Node */}
                                <div className="flex flex-col gap-1.5">
                                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Target Destination Node</label>
                                    {hasExistingTransition ? (
                                        <div className="bg-slate-950 border border-slate-800 rounded-md p-2 text-[11px] text-slate-300">
                                            {targetNode ? (
                                                <span>📍 {targetNode.building_name} F{targetNode.floor_level} - {targetNode.room_label}</span>
                                            ) : (
                                                <span>📍 Target Node (ID: {existingEdge.target_node_id})</span>
                                            )}
                                        </div>
                                    ) : (
                                        <NodeSelector
                                            nodes={globalNodes.filter(gn => {
                                                const isSameType = gn.node_type === currentActiveObj.node_type;
                                                const isDiffFloorplan = gn.floorplan_id !== Number(currentFloorplanId);

                                                if (currentActiveObj.node_type === 'ELEVATOR' || currentActiveObj.node_type === 'STAIRWELL') {
                                                    const isSameBuilding = gn.building_name === currentBuildingName;
                                                    const isDiffFloor = Number(gn.floor_level) !== Number(currentFloorLevel);
                                                    return isSameType && isSameBuilding && isDiffFloor;
                                                }

                                                return isSameType && isDiffFloorplan;
                                            })}
                                            value={transitionTargetId}
                                            onChange={setTransitionTargetId}
                                            placeholder="Search destination node..."
                                        />
                                    )}
                                </div>

                                {/* 2. Real-World Distance */}
                                <div className="flex flex-col gap-1.5">
                                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Real-World Distance (meters)</label>
                                    <input type="number" value={transitionWeight} onChange={e => setTransitionWeight(e.target.value)} className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-white focus:outline-none focus:border-purple-500" />
                                </div>

                                {/* 3. Settings & Edge RBAC Panel */}
                                <div className="grid grid-cols-2 gap-3 p-2 bg-slate-950 border border-slate-850 rounded-lg">
                                    <div className="flex flex-col gap-1.5">
                                        <h5 className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Settings</h5>
                                        <label className="flex items-center gap-1.5 text-[10px] text-slate-300 cursor-pointer">
                                            <input type="checkbox" checked={transitionIsAccessible} onChange={e => setTransitionIsAccessible(e.target.checked)} className="w-3 h-3 rounded border-slate-800 bg-slate-900 accent-purple-500" /> Accessible
                                        </label>
                                        <label className="flex items-center gap-1.5 text-[10px] text-slate-300 cursor-pointer">
                                            <input type="checkbox" checked={transitionIsBidirectional} onChange={e => setTransitionIsBidirectional(e.target.checked)} className="w-3 h-3 rounded border-slate-800 bg-slate-900 accent-purple-500" /> Bidirectional
                                        </label>
                                    </div>
                                    <div className="flex flex-col gap-1.5">
                                        <h5 className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Edge RBAC</h5>
                                        {rolesList.map(role => (
                                            <label key={role.role_id} className="flex items-center gap-1.5 text-[9px] text-slate-400 select-none">
                                                <input type="checkbox" checked={derivedTransitionRoles.includes(role.role_id)} disabled className="w-3 h-3 rounded border-slate-800 bg-slate-900 accent-purple-500 opacity-60" /> {role.role_name}
                                            </label>
                                        ))}
                                    </div>
                                </div>

                                {/* 4. Action Button(s) */}
                                {appMode === 'edit' && (
                                    hasExistingTransition ? (
                                        <div className="flex flex-col gap-2 mt-1">
                                            <button 
                                                onClick={() => handleUpdateTransition(existingTransitionIndex)} 
                                                className="w-full py-1.5 bg-purple-600 hover:bg-purple-500 text-white font-bold rounded text-[11px] cursor-pointer border-0 transition-all duration-200"
                                            >
                                                Update Transition Link
                                            </button>
                                            <button 
                                                onClick={() => handleDeleteTransition(existingTransitionIndex)} 
                                                className="w-full py-1.5 bg-red-950 hover:bg-red-900 border border-red-800 text-red-400 font-bold rounded text-[11px] cursor-pointer transition-all duration-200"
                                            >
                                                Delete Transition Link
                                            </button>
                                        </div>
                                    ) : (
                                        <button 
                                            onClick={handleCreateTransition} 
                                            className="w-full py-1.5 bg-purple-600 hover:bg-purple-500 text-white font-bold rounded text-[11px] cursor-pointer border-0 transition-all duration-200 mt-1"
                                        >
                                            Create Transition Link
                                        </button>
                                    )
                                )}
                            </div>
                        );
                    })()}
                </div>
            )}

            {/* --- EDGE PANEL UI --- */}
            {(selectedElement.type === 'edge') && (
                <div className="flex flex-col gap-4 border-none p-0 m-0">
                    <div className="flex flex-col gap-1.5 p-2 bg-slate-950 border border-slate-850 rounded-lg">
                        <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Path Metadata</span>
                        <div className="flex justify-between items-center text-[11px]">
                            <span className="text-slate-400">Total Distance:</span>
                            <span className="font-bold text-white font-mono">{activeObj.weight} meters</span>
                        </div>
                        <div className="flex justify-between items-center text-[11px] mt-0.5">
                            <span className="text-slate-400">Path Routing:</span>
                            <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${
                                activeObj.isCustom 
                                    ? 'bg-amber-600/20 text-amber-400 border border-amber-500/20' 
                                    : 'bg-emerald-600/20 text-emerald-400 border border-emerald-500/20'
                            }`}>
                                {activeObj.isCustom ? 'Manual / Custom' : 'AI Routed'}
                            </span>
                        </div>
                    </div>

                    {/* AI pathfinding reset tools */}
                    {!activeObj.is_cross_floor && appMode === 'edit' && (
                        <div className="flex flex-col gap-1.5 pt-1">
                            <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">AI Path Controls</span>
                            <button 
                                onClick={triggerSelectedEdgeAStar}
                                className="w-full py-1.5 bg-emerald-600/15 hover:bg-emerald-600/25 border border-emerald-500/30 text-emerald-400 font-bold rounded text-[10px] cursor-pointer transition-all duration-200"
                            >
                                ⚡ Re-Route with AI
                            </button>
                            <button 
                                onClick={resetSelectedEdgeToStraight}
                                className="w-full py-1.5 bg-slate-950 hover:bg-slate-850 border border-slate-800 text-slate-300 font-semibold rounded text-[10px] cursor-pointer transition-all duration-200"
                            >
                                Straight Line Fallback
                            </button>
                            <p className="text-[8px] text-slate-500 leading-normal">Double-click on path segment to manually add control points; double-click control points to delete them.</p>
                        </div>
                    )}

                    {activeObj.is_cross_floor && (
                        <div className="flex flex-col gap-1">
                            <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Edit Manual Distance (meters)</label>
                            <input type="number" value={activeObj.weight} onChange={e => updateProperty('weight', e.target.value)} className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-white focus:outline-none focus:border-blue-500" />
                        </div>
                    )}

                    <div className="flex flex-col gap-1.5 pt-1.5">
                        <label className="flex items-center gap-2 text-[11px] font-bold text-slate-300 uppercase cursor-pointer select-none">
                            <input type="checkbox" checked={activeObj.is_bidirectional} onChange={e => updateProperty('is_bidirectional', e.target.checked)} className="w-3.5 h-3.5 rounded border-slate-800 bg-slate-950 text-blue-600 accent-blue-500 cursor-pointer" />
                            Bidirectional Path
                        </label>
                        <label className="flex items-center gap-2 text-[11px] font-bold text-slate-300 uppercase cursor-pointer select-none">
                            <input type="checkbox" checked={activeObj.is_accessible === 'ALLOW'} onChange={e => updateProperty('is_accessible', e.target.checked ? 'ALLOW' : 'DENY')} className="w-3.5 h-3.5 rounded border-slate-800 bg-slate-950 text-blue-600 accent-blue-500 cursor-pointer" />
                            Path is Accessible
                        </label>
                    </div>
                    
                    {/* Edge RBAC */}
                    <div className="border-t border-slate-800 pt-3 flex flex-col gap-2">
                        <div className="flex justify-between items-center">
                            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Allowed Campus Roles</h4>
                            <span className="text-[8px] bg-indigo-950 text-indigo-400 border border-indigo-800 px-1 py-0.5 rounded font-bold uppercase tracking-wide">Read-Only</span>
                        </div>
                        <p className="text-[10px] text-slate-500 leading-normal mb-1">Campus roles permitted to traverse this path (derived automatically from intersection of connected nodes).</p>
                        <div className="flex flex-col gap-2 bg-slate-950 p-2.5 rounded-lg border border-slate-855">
                            {rolesList.map(role => (
                                <label key={role.role_id} className="flex items-center gap-2 text-[11px] font-medium text-slate-400 select-none">
                                    <input type="checkbox" checked={(activeObj.allowed_roles || []).includes(role.role_id)} disabled className="w-3 h-3 rounded border-slate-800 bg-slate-950 accent-blue-500 opacity-60" />
                                    {role.role_name}
                                </label>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
