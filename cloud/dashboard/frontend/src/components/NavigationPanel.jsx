/**
 * @file NavigationPanel.js
 * @description The Navigation Tester panel used to invoke the A* routing engine manually.
 */

import React from 'react';
import { isCorridorNode } from '../utils/nodeUtils';
import { NodeSelector } from './NodeSelector/NodeSelector';


export function NavigationPanel({
    navPanelOpen,
    navResult, setNavResult, setNavHighlight,
    navError, setNavError,
    navStartId, setNavStartId,
    navEndId, setNavEndId,
    navRoleId, setNavRoleId,
    globalNodes, rolesList,
    handleRunNavigation,
    navLoading,
    setNotifVisitorId, setNotifVisitorEmail, setNotifMessage, setIsAutoMessage
}) {
    if (!navPanelOpen) return null;

    return (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl flex flex-col gap-3 max-h-[85vh] overflow-y-auto">
            <div className="flex justify-between items-center border-b border-slate-800 pb-2.5">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <span>🧭</span> Navigation Tester
                </h3>
                {navResult && (
                    <button
                        onClick={() => {
                            setNavResult(null);
                            setNavHighlight(null);
                            setNavError('');
                            setNavStartId('');
                            setNavEndId('');
                            setNavRoleId('');
                            setNotifVisitorId('');
                            setNotifVisitorEmail('');
                            setNotifMessage('');
                            setIsAutoMessage(true);
                        }}
                        className="text-[10px] text-teal-400 hover:text-teal-300 font-bold bg-teal-950 px-2 py-1 rounded-md border border-teal-800 cursor-pointer"
                    >
                        Clear Route
                    </button>
                )}
            </div>

            {/* Start and End node selectors */}
            <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">🟢 Start Node</label>
                    <NodeSelector
                        id="nav-start-select"
                        nodes={globalNodes.filter(n => !isCorridorNode(n))}
                        value={navStartId}
                        onChange={setNavStartId}
                        placeholder="Search or select start node..."
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">🔴 Destination Node</label>
                    <NodeSelector
                        id="nav-end-select"
                        nodes={globalNodes.filter(n => !isCorridorNode(n))}
                        value={navEndId}
                        onChange={setNavEndId}
                        placeholder="Search or select destination node..."
                    />
                </div>

                {/* Swap button */}
                <button
                    id="nav-swap-btn"
                    onClick={() => { const tmp = navStartId; setNavStartId(navEndId); setNavEndId(tmp); }}
                    className="self-center py-0.5 px-3 bg-slate-950 border border-slate-700 text-slate-400 hover:text-teal-400 hover:border-teal-600 text-[10px] font-bold rounded-md cursor-pointer transition-all duration-200"
                    title="Swap Start and Destination"
                >
                    ⇅ Swap Start ↔ Destination
                </button>

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">🎭 User Role</label>
                    <select
                        id="nav-role-select"
                        value={navRoleId}
                        onChange={e => setNavRoleId(e.target.value)}
                        className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-teal-500 w-full cursor-pointer"
                    >
                        <option value="">-- Select role --</option>
                        {rolesList.map(r => (
                            <option key={r.role_id} value={r.role_id}>{r.role_name}</option>
                        ))}
                    </select>
                </div>
            </div>

            <button
                id="nav-find-route-btn"
                onClick={handleRunNavigation}
                disabled={navLoading || !navStartId || !navEndId || !navRoleId}
                className="w-full py-1.5 bg-teal-600 hover:bg-teal-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold rounded-md text-[11px] flex items-center justify-center gap-1.5 cursor-pointer transition-all duration-200 border-0"
            >
                {navLoading ? '⏳ Calculating...' : '🧭 Find Route'}
            </button>

            {/* Error message */}
            {navError && (
                <div className="bg-red-950 border border-red-800 rounded-lg p-2.5 text-[10px] text-red-400">
                    ⚠️ {navError}
                </div>
            )}

            {/* Route Summary */}
            {navResult && navResult.route_summary && (
                <div className="bg-teal-950/50 border border-teal-800/60 rounded-lg p-3 flex flex-col gap-2">
                    <div className="flex justify-between items-start">
                        <div>
                            <p className="text-[9px] text-teal-400 font-bold uppercase tracking-wider mb-0.5">Route Found</p>
                            <p className="text-[10px] text-white font-semibold">{navResult.route_summary.start_label}</p>
                            <p className="text-[9px] text-slate-400">↓</p>
                            <p className="text-[10px] text-white font-semibold">{navResult.route_summary.destination_label}</p>
                        </div>
                    </div>
                    <div className="grid grid-cols-2 gap-1.5 border-t border-teal-800/60 pt-2">
                        <div className="bg-slate-950/50 rounded p-1.5 text-center">
                            <p className="text-[9px] text-slate-500 uppercase tracking-wide">Distance</p>
                            <p className="text-[12px] font-bold text-teal-400">{navResult.route_summary.total_distance_m}m</p>
                        </div>
                        <div className="bg-slate-950/50 rounded p-1.5 text-center">
                            <p className="text-[9px] text-slate-500 uppercase tracking-wide">Est. Time</p>
                            <p className="text-[12px] font-bold text-teal-400">{navResult.route_summary.estimated_time_label}</p>
                        </div>
                        {navResult.route_summary.floor_transitions > 0 && (
                            <div className={`bg-slate-950/50 rounded p-1.5 text-center ${navResult.route_summary.building_transitions > 0 ? '' : 'col-span-2'}`}>
                                <p className="text-[9px] text-slate-500 uppercase tracking-wide">Floor Transitions</p>
                                <p className="text-[12px] font-bold text-amber-400">{navResult.route_summary.floor_transitions}</p>
                            </div>
                        )}
                        {navResult.route_summary.building_transitions > 0 && (
                            <div className={`bg-slate-950/50 rounded p-1.5 text-center ${navResult.route_summary.floor_transitions > 0 ? '' : 'col-span-2'}`}>
                                <p className="text-[9px] text-slate-500 uppercase tracking-wide">Building Transitions</p>
                                <p className="text-[12px] font-bold text-indigo-400">{navResult.route_summary.building_transitions}</p>
                            </div>
                        )}
                    </div>
                    {(navResult.route_summary.floor_transitions > 0 || navResult.route_summary.building_transitions > 0) && (
                        <p className="text-[9px] text-amber-500/80 leading-normal">💡 Route crosses floors/buildings. The overlay highlights the segment on the currently loaded floor plan.</p>
                    )}
                </div>
            )}

            {/* Step-by-Step Instructions */}
            {navResult && navResult.instructions && navResult.instructions.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Turn-by-Turn Directions</h4>
                    <div className="flex flex-col gap-1">
                        {navResult.instructions.map((step, idx) => {
                            const icons = { start: '🟢', walk: '⬆️', turn: step.action === 'left' ? '↰' : '↱', transition: step.action === 'elevator' ? '🛗' : step.action === 'stairwell' ? '🪜' : '🚪', arrive: '🏁' };
                            const colours = { start: 'text-teal-400', walk: 'text-slate-300', turn: 'text-amber-400', transition: 'text-purple-400', arrive: 'text-yellow-400' };
                            return (
                                <div key={idx} className="flex gap-2 items-start bg-slate-950/60 rounded-lg px-2.5 py-1.5 border border-slate-800/60">
                                    <span className="text-[13px] mt-0.5 flex-shrink-0">{icons[step.type] || '•'}</span>
                                    <div className="flex flex-col min-w-0">
                                        <p className={`text-[10px] font-semibold ${colours[step.type] || 'text-white'} leading-tight`}>{step.description}</p>
                                        {step.type === 'walk' && (
                                            <p className="text-[9px] text-slate-600 mt-0.5">{step.distance_m}m</p>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
