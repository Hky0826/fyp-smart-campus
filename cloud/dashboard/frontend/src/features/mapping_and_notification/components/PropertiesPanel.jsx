import React from 'react';
import { NodeSelector } from './NodeSelector';

export function PropertiesPanel({
    mode,
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
    const [rolesOpen, setRolesOpen] = React.useState(false);
    const currentActiveObj = activeObj;

    if (mode !== 'edit_props' || !currentActiveObj) return null;

    const handleUpdateProperty = (key, value) => {
        updateProperty(key, value);
    };

    return (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 shadow-xl flex flex-col gap-3 max-h-[85vh] overflow-y-auto">
            <div className="flex justify-between items-center border-b border-slate-800 pb-2">
                <h3 className="text-xs font-bold text-white flex items-center gap-1.5">
                    {selectedElement.type === 'node' ? '📍 Node Properties' : '🔗 Path Properties'}
                </h3>
                <button 
                    onClick={() => setSelectedElement({ type: null, index: null })} 
                    className="text-[10px] text-slate-500 hover:text-slate-300 font-bold bg-slate-950 px-2 py-0.5 rounded border border-slate-800 cursor-pointer"
                >
                    Close
                </button>
            </div>
            
            {/* --- NODE PANEL UI --- */}
            {(selectedElement.type === 'node') && (
                <div className="flex flex-col gap-3">
                    {isTransitionNode && (
                        <div className="flex border-b border-slate-800 mb-1">
                            <button
                                type="button"
                                onClick={() => setActiveNodeTab('general')}
                                className={`flex-1 pb-1.5 text-[10px] font-bold uppercase tracking-wider transition-all duration-200 border-b-2 ${
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
                                className={`flex-1 pb-1.5 text-[10px] font-bold uppercase tracking-wider transition-all duration-200 border-b-2 ${
                                    activeNodeTab === 'transition' 
                                        ? 'border-purple-500 text-purple-400 font-extrabold' 
                                        : 'border-transparent text-slate-500 hover:text-slate-300'
                                }`}
                            >
                                🔗 Linker
                            </button>
                        </div>
                    )}

                    {(!isTransitionNode || activeNodeTab === 'general') && (
                        <div className="flex flex-col gap-3">
                            <div className="flex flex-col gap-1">
                                <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Room Label</label>
                                <input type="text" value={currentActiveObj.room_label || ''} onChange={e => handleUpdateProperty('room_label', e.target.value)} className="bg-slate-950 border border-slate-800 rounded-lg p-1.5 text-[11px] text-white focus:outline-none focus:border-blue-500" />
                            </div>
                            
                            <div className="flex flex-col gap-1">
                                <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Node Type</label>
                                <select value={currentActiveObj.node_type || 'OTHER'} onChange={e => handleUpdateProperty('node_type', e.target.value)} className="bg-slate-950 border border-slate-800 rounded-lg p-1.5 text-[11px] text-white focus:outline-none focus:border-blue-500 cursor-pointer">
                                    {['CLASSROOM', 'CORRIDOR', 'ENTRANCE', 'STAIRWELL', 'ELEVATOR', 'FOOD', 'OFFICE', 'FACILITIES', 'HALL', 'WASHROOM', 'OUTDOOR', 'SOCIAL SPACES', 'OTHER'].map(t => <option key={t} value={t}>{t}</option>)}
                                </select>
                            </div>
                            
                            <div className="flex items-center gap-2 pt-0.5">
                                <input 
                                    type="checkbox" 
                                    id="node-accessible"
                                    checked={currentActiveObj.is_accessible === 'ALLOW'} 
                                    onChange={e => handleUpdateProperty('is_accessible', e.target.checked ? 'ALLOW' : 'DENY')} 
                                    className="w-3.5 h-3.5 rounded border-slate-800 bg-slate-950 text-blue-600 focus:ring-blue-500 accent-blue-500 cursor-pointer" 
                                />
                                <label htmlFor="node-accessible" className="text-[11px] font-bold text-slate-300 select-none cursor-pointer">Area is Accessible</label>
                            </div>

                            <div className="border-t border-slate-800 pt-2 flex flex-col gap-1.5">
                                <button
                                    type="button"
                                    onClick={() => setRolesOpen(!rolesOpen)}
                                    className="w-full flex items-center justify-between text-[10px] font-bold text-slate-400 uppercase tracking-wider bg-transparent border-0 cursor-pointer text-left"
                                >
                                    <span>Allowed Roles ({(currentActiveObj.allowed_roles || []).length})</span>
                                    <span>{rolesOpen ? '▲' : '▼'}</span>
                                </button>
                                {rolesOpen && (
                                    <div className="flex flex-col gap-1.5 bg-slate-950 p-2 rounded-lg border border-slate-850">
                                        {rolesList.map(role => (
                                            <label key={role.role_id || role.id} className="flex items-center gap-2 text-[11px] font-medium text-slate-300 cursor-pointer select-none">
                                                <input type="checkbox" checked={(currentActiveObj.allowed_roles || []).includes(role.role_id || role.id)} onChange={() => handleRoleToggle(role.role_id || role.id)} className="w-3.5 h-3.5 rounded border-slate-800 bg-slate-950 accent-blue-500" />
                                                {role.role_name || role.name}
                                            </label>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

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
                            <div className="flex flex-col gap-2.5">
                                <h4 className="text-[11px] font-bold text-purple-400 uppercase tracking-wider">
                                    {hasExistingTransition ? '🔗 Transition Path Properties' : '🔗 Transition Linker (Cross-Map Edge)'}
                                </h4>
                                
                                <div className="flex flex-col gap-1">
                                    <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Target Destination Node</label>
                                    {hasExistingTransition ? (
                                        <div className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-300">
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

                                <div className="flex flex-col gap-1">
                                    <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Real-World Distance (meters)</label>
                                    <input type="number" value={transitionWeight} onChange={e => setTransitionWeight(e.target.value)} className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-white focus:outline-none focus:border-purple-500" />
                                </div>

                                <div className="grid grid-cols-2 gap-2 p-2 bg-slate-950 border border-slate-850 rounded-lg">
                                    <div className="flex flex-col gap-1">
                                        <h5 className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Settings</h5>
                                        <label className="flex items-center gap-1.5 text-[10px] text-slate-300 cursor-pointer">
                                            <input type="checkbox" checked={transitionIsAccessible} onChange={e => setTransitionIsAccessible(e.target.checked)} className="w-3 h-3 rounded border-slate-800 bg-slate-900 accent-purple-500" /> Accessible
                                        </label>
                                        <label className="flex items-center gap-1.5 text-[10px] text-slate-300 cursor-pointer">
                                            <input type="checkbox" checked={transitionIsBidirectional} onChange={e => setTransitionIsBidirectional(e.target.checked)} className="w-3 h-3 rounded border-slate-800 bg-slate-900 accent-purple-500" /> Bidirectional
                                        </label>
                                    </div>
                                    <div className="flex flex-col gap-1">
                                        <h5 className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Edge RBAC</h5>
                                        <div className="flex flex-wrap gap-1">
                                            {rolesList.map(role => {
                                                const allowed = derivedTransitionRoles.includes(role.role_id || role.id);
                                                return (
                                                    <span key={role.role_id || role.id} className={`px-1 py-0.5 rounded text-[8px] font-bold ${allowed ? 'bg-purple-950 text-purple-300 border border-purple-800' : 'bg-slate-900 text-slate-600 line-through'}`}>
                                                        {role.role_name || role.name}
                                                    </span>
                                                );
                                            })}
                                        </div>
                                    </div>
                                </div>

                                {hasExistingTransition ? (
                                    <div className="flex flex-col gap-1.5 mt-0.5">
                                        <button 
                                            onClick={() => handleUpdateTransition(existingTransitionIndex)} 
                                            className="w-full py-1 bg-purple-600 hover:bg-purple-500 text-white font-bold rounded text-[10px] cursor-pointer border-0 transition-all duration-200"
                                        >
                                            Update Transition Link
                                        </button>
                                        <button 
                                            onClick={() => handleDeleteTransition(existingTransitionIndex)} 
                                            className="w-full py-1 bg-red-950 hover:bg-red-900 border border-red-800 text-red-400 font-bold rounded text-[10px] cursor-pointer transition-all duration-200"
                                        >
                                            Delete Transition Link
                                        </button>
                                    </div>
                                ) : (
                                    <button 
                                        onClick={handleCreateTransition} 
                                        className="w-full py-1 bg-purple-600 hover:bg-purple-500 text-white font-bold rounded text-[10px] cursor-pointer border-0 transition-all duration-200 mt-0.5"
                                    >
                                        Create Transition Link
                                    </button>
                                )}
                            </div>
                        );
                    })()}
                </div>
            )}

            {/* --- EDGE PANEL UI --- */}
            {selectedElement.type === 'edge' && (
                <div className="flex flex-col gap-2.5">
                    <div className="flex flex-col gap-1 p-2 bg-slate-950 border border-slate-850 rounded-lg">
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

                    {!activeObj.is_cross_floor && (
                        <div className="flex flex-col gap-1">
                            <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">AI Path Controls</span>
                            <div className="grid grid-cols-2 gap-1.5">
                                <button 
                                    onClick={triggerSelectedEdgeAStar}
                                    className="py-1 bg-emerald-600/15 hover:bg-emerald-600/25 border border-emerald-500/30 text-emerald-400 font-bold rounded text-[10px] cursor-pointer transition-all duration-200"
                                >
                                    ⚡ AI Re-Route
                                </button>
                                <button 
                                    onClick={resetSelectedEdgeToStraight}
                                    className="py-1 bg-slate-950 hover:bg-slate-850 border border-slate-800 text-slate-300 font-semibold rounded text-[10px] cursor-pointer transition-all duration-200"
                                >
                                    Straight Fallback
                                </button>
                            </div>
                        </div>
                    )}

                    {activeObj.is_cross_floor && (
                        <div className="flex flex-col gap-1">
                            <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Edit Distance (m)</label>
                            <input type="number" value={activeObj.weight} onChange={e => updateProperty('weight', e.target.value)} className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-white focus:outline-none focus:border-blue-500" />
                        </div>
                    )}

                    <div className="flex flex-col gap-1 pt-0.5">
                        <label className="flex items-center gap-2 text-[11px] font-bold text-slate-300 cursor-pointer select-none">
                            <input type="checkbox" checked={activeObj.is_bidirectional} onChange={e => updateProperty('is_bidirectional', e.target.checked)} className="w-3.5 h-3.5 rounded border-slate-800 bg-slate-950 text-blue-600 accent-blue-500 cursor-pointer" />
                            Bidirectional Path
                        </label>
                        <label className="flex items-center gap-2 text-[11px] font-bold text-slate-300 cursor-pointer select-none">
                            <input type="checkbox" checked={activeObj.is_accessible === 'ALLOW'} onChange={e => updateProperty('is_accessible', e.target.checked ? 'ALLOW' : 'DENY')} className="w-3.5 h-3.5 rounded border-slate-800 bg-slate-950 text-blue-600 accent-blue-500 cursor-pointer" />
                            Path is Accessible
                        </label>
                    </div>
                    
                    <div className="border-t border-slate-800 pt-2 flex flex-col gap-1.5">
                        <div className="flex justify-between items-center">
                            <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Derived Roles</h4>
                            <span className="text-[8px] bg-indigo-950 text-indigo-400 border border-indigo-800 px-1 py-0.5 rounded font-bold uppercase">Auto</span>
                        </div>
                        <div className="flex flex-wrap gap-1 bg-slate-950 p-2 rounded-lg border border-slate-855">
                            {rolesList.map(role => {
                                const allowed = (activeObj.allowed_roles || []).includes(role.role_id || role.id);
                                return (
                                    <span key={role.role_id || role.id} className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${allowed ? 'bg-blue-950 text-blue-300 border border-blue-800' : 'bg-slate-900 text-slate-600 line-through'}`}>
                                        {role.role_name || role.name}
                                    </span>
                                );
                            })}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
