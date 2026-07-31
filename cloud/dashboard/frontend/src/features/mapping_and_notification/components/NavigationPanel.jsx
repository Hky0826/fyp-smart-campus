import React from 'react';
import { isCorridorNode } from '../utils/nodeUtils';
import { NodeSelector } from './NodeSelector';

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
    const [directionsOpen, setDirectionsOpen] = React.useState(true);

    return (
        <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-3 shadow-xl flex flex-col gap-2.5">
            <div className="flex justify-between items-center border-b border-slate-800 pb-1.5">
                <h3 className="text-[10px] font-bold text-slate-300 uppercase tracking-wider">
                    ADMIN ROUTE PREVIEW
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
                            if (setNotifVisitorId) setNotifVisitorId('');
                            if (setNotifVisitorEmail) setNotifVisitorEmail('');
                            if (setNotifMessage) setNotifMessage('');
                            if (setIsAutoMessage) setIsAutoMessage(true);
                        }}
                        className="text-[9px] text-teal-400 hover:text-teal-300 font-bold bg-teal-950 px-1.5 py-0.5 rounded border border-teal-800 cursor-pointer"
                    >
                        Clear
                    </button>
                )}
            </div>

            <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-1">
                    <label className="text-[9px] text-slate-400 font-semibold">Start Node ID</label>
                    <NodeSelector
                        id="nav-start-select"
                        nodes={globalNodes.filter(n => !isCorridorNode(n))}
                        value={navStartId}
                        onChange={setNavStartId}
                        placeholder="Start Node ID..."
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <div className="flex justify-between items-center">
                        <label className="text-[9px] text-slate-400 font-semibold">Destination Node ID</label>
                        <button
                            id="nav-swap-btn"
                            type="button"
                            onClick={() => { const tmp = navStartId; setNavStartId(navEndId); setNavEndId(tmp); }}
                            className="text-[9px] text-teal-400 hover:underline bg-transparent border-0 cursor-pointer font-semibold"
                            title="Swap Start and Destination"
                        >
                            Swap ⇅
                        </button>
                    </div>
                    <NodeSelector
                        id="nav-end-select"
                        nodes={globalNodes.filter(n => !isCorridorNode(n))}
                        value={navEndId}
                        onChange={setNavEndId}
                        placeholder="Destination Node ID..."
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] text-slate-400 font-semibold">Role</label>
                    <select
                        id="nav-role-select"
                        value={navRoleId}
                        onChange={e => setNavRoleId(e.target.value)}
                        className="bg-slate-950 border border-slate-800 rounded-md px-2 py-1 text-[10px] text-slate-200 focus:outline-none focus:border-teal-500 w-full cursor-pointer h-7"
                    >
                        <option value="">-- Select Role --</option>
                        {rolesList.map(r => (
                            <option key={r.role_id || r.id} value={r.role_id || r.id}>{r.role_name || r.name}</option>
                        ))}
                    </select>
                </div>
            </div>

            <button
                id="nav-find-route-btn"
                onClick={handleRunNavigation}
                disabled={navLoading || !navStartId || !navEndId}
                className="w-full py-1.5 bg-teal-600 hover:bg-teal-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold rounded-md text-[10px] flex items-center justify-center gap-1.5 cursor-pointer transition-all duration-200 border-0 shadow-md shadow-teal-600/10 mt-0.5"
            >
                {navLoading ? 'Calculating...' : 'Calculate Route'}
            </button>

            {navError && (
                <div className="bg-red-950 border border-red-800 rounded-lg p-2 text-[10px] text-red-400">
                    ⚠️ {navError}
                </div>
            )}

            {navResult && navResult.route_summary && (
                <div className="bg-teal-950/50 border border-teal-800/60 rounded-lg p-2.5 flex flex-col gap-1.5">
                    <div className="flex justify-between items-start">
                        <div>
                            <p className="text-[9px] text-teal-400 font-bold uppercase tracking-wider mb-0.5">Route Found</p>
                            <p className="text-[10px] text-white font-semibold">{navResult.route_summary.start_label}</p>
                            <p className="text-[9px] text-slate-400">↓</p>
                            <p className="text-[10px] text-white font-semibold">{navResult.route_summary.destination_label}</p>
                        </div>
                    </div>
                    <div className="grid grid-cols-2 gap-1.5 border-t border-teal-800/60 pt-1.5">
                        <div className="bg-slate-950/50 rounded p-1 text-center">
                            <p className="text-[8px] text-slate-500 uppercase">Distance</p>
                            <p className="text-[11px] font-bold text-teal-400">{navResult.route_summary.total_distance_m}m</p>
                        </div>
                        <div className="bg-slate-950/50 rounded p-1 text-center">
                            <p className="text-[8px] text-slate-500 uppercase">Est. Time</p>
                            <p className="text-[11px] font-bold text-teal-400">{navResult.route_summary.estimated_time_label}</p>
                        </div>
                        {navResult.route_summary.floor_transitions > 0 && (
                            <div className={`bg-slate-950/50 rounded p-1 text-center ${navResult.route_summary.building_transitions > 0 ? '' : 'col-span-2'}`}>
                                <p className="text-[8px] text-slate-500 uppercase">Floor Transitions</p>
                                <p className="text-[11px] font-bold text-amber-400">{navResult.route_summary.floor_transitions}</p>
                            </div>
                        )}
                        {navResult.route_summary.building_transitions > 0 && (
                            <div className={`bg-slate-950/50 rounded p-1 text-center ${navResult.route_summary.floor_transitions > 0 ? '' : 'col-span-2'}`}>
                                <p className="text-[8px] text-slate-500 uppercase">Building Transitions</p>
                                <p className="text-[11px] font-bold text-indigo-400">{navResult.route_summary.building_transitions}</p>
                            </div>
                        )}
                    </div>
                    {(navResult.route_summary.floor_transitions > 0 || navResult.route_summary.building_transitions > 0) && (
                        <p className="text-[9px] text-amber-500/80 leading-normal">💡 Route crosses floors/buildings. Overlay shows active floor segment.</p>
                    )}
                </div>
            )}

            {navResult && navResult.instructions && navResult.instructions.length > 0 && (
                <div className="flex flex-col gap-1 border-t border-slate-800 pt-2">
                    <button
                        type="button"
                        onClick={() => setDirectionsOpen(!directionsOpen)}
                        className="w-full flex items-center justify-between text-[10px] font-bold text-slate-400 uppercase tracking-wider bg-transparent border-0 cursor-pointer text-left"
                    >
                        <span>📋 Turn-by-Turn Directions ({navResult.instructions.length})</span>
                        <span>{directionsOpen ? '▲' : '▼'}</span>
                    </button>
                    {directionsOpen && (
                        <div className="flex flex-col gap-1 mt-1">
                            {navResult.instructions.map((step, idx) => {
                                const icons = { start: '🟢', walk: '⬆️', turn: step.action === 'left' ? '↰' : '↱', transition: step.action === 'elevator' ? '🛗' : step.action === 'stairwell' ? '🪜' : '🚪', arrive: '🏁' };
                                const colours = { start: 'text-teal-400', walk: 'text-slate-300', turn: 'text-amber-400', transition: 'text-purple-400', arrive: 'text-yellow-400' };
                                return (
                                    <div key={idx} className="flex gap-2 items-start bg-slate-950/60 rounded-lg px-2 py-1 border border-slate-800/60">
                                        <span className="text-xs flex-shrink-0">{icons[step.type] || '•'}</span>
                                        <div className="flex flex-col min-w-0">
                                            <p className={`text-[10px] font-semibold ${colours[step.type] || 'text-white'} leading-tight`}>{step.description}</p>
                                            {step.type === 'walk' && (
                                                <p className="text-[9px] text-slate-600">{step.distance_m}m</p>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
