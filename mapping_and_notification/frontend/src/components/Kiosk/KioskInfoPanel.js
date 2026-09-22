import React from 'react';

export function KioskInfoPanel({ navResult, activeFloorplanId, mapContext, qrSession }) {
    const [showQrModal, setShowQrModal] = React.useState(false);

    if (!navResult || !navResult.route_summary) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center p-6 text-center text-slate-500">
                <span className="text-3xl mb-3 opacity-40">🧭</span>
                <p className="text-sm font-medium">Select a start and destination above to view step-by-step route directions.</p>
            </div>
        );
    }

    const { route_summary, instructions } = navResult;

    const icons = { 
        start: '🟢', 
        walk: '⬆️', 
        turn: (action) => action === 'left' ? '↰' : '↱', 
        transition: (action) => action === 'elevator' ? '🛗' : action === 'stairwell' ? '🪜' : '🚪', 
        arrive: '🏁' 
    };
    
    const colors = { 
        start: 'text-teal-400', 
        walk: 'text-slate-200', 
        turn: 'text-amber-400', 
        transition: 'text-purple-400', 
        arrive: 'text-yellow-400' 
    };

    return (
        <div className="flex-1 flex flex-col h-full min-h-0 overflow-hidden relative bg-white">
            {/* Summary Card */}
            <div className="bg-white border-b border-slate-200 p-3.5 flex flex-col gap-2.5 shadow-xs z-10 shrink-0">
                <div className="flex items-center justify-between">
                    <h3 className="text-[10px] font-bold text-indigo-700 uppercase tracking-widest">Route Summary</h3>
                    <span className="text-[10px] font-bold text-slate-600 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-full">
                        {instructions?.length || 0} Steps
                    </span>
                </div>

                <div className="bg-slate-50 rounded-lg p-2 border border-slate-200 flex flex-col gap-1">
                    <div className="flex items-center gap-2 text-xs">
                        <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-200 text-[10px] font-bold uppercase tracking-wider shrink-0">Start</span>
                        <span className="font-semibold text-slate-900 truncate">{route_summary.start_label}</span>
                    </div>
                    <div className="text-slate-400 text-[10px] pl-2 leading-none">↓</div>
                    <div className="flex items-center gap-2 text-xs">
                        <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200 text-[10px] font-bold uppercase tracking-wider shrink-0">Destination</span>
                        <span className="font-semibold text-slate-900 truncate">{route_summary.destination_label}</span>
                    </div>
                </div>

                {/* Metrics Grid */}
                <div className="grid grid-cols-3 gap-1.5">
                    <div className="bg-slate-50 rounded-md p-1.5 text-center border border-slate-200">
                        <p className="text-[9px] text-slate-500 uppercase tracking-wider">Distance</p>
                        <p className="text-sm font-bold text-emerald-700">{route_summary.total_distance_m}m</p>
                    </div>
                    <div className="bg-slate-50 rounded-md p-1.5 text-center border border-slate-200">
                        <p className="text-[9px] text-slate-500 uppercase tracking-wider">Est. Time</p>
                        <p className="text-sm font-bold text-indigo-700">{route_summary.estimated_time_label}</p>
                    </div>
                    <div className="bg-slate-50 rounded-md p-1.5 text-center border border-slate-200">
                        <p className="text-[9px] text-slate-500 uppercase tracking-wider">Transitions</p>
                        <p className="text-sm font-bold text-amber-700">
                            {(route_summary.floor_transitions || 0) + (route_summary.building_transitions || 0)}
                        </p>
                    </div>
                </div>
            </div>

            {/* Turn-by-Turn Directions List */}
            <div className="flex-1 min-h-0 overflow-y-auto p-3 bg-slate-50/50 scrollbar-thin scrollbar-thumb-slate-300 scrollbar-track-transparent flex flex-col gap-2">
                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider px-1">Turn-by-Turn Steps</div>
                {instructions?.map((step, idx) => {
                    const icon = step.type === 'turn' || step.type === 'transition' ? icons[step.type](step.action) : icons[step.type];
                    const isActiveFloor = step.floorplan_id === activeFloorplanId;

                    return (
                        <div 
                            key={idx} 
                            className={`flex gap-3 items-start p-2.5 rounded-lg border transition-colors ${
                                isActiveFloor 
                                    ? 'bg-white border-indigo-400 shadow-sm ring-1 ring-indigo-200' 
                                    : 'bg-white/80 border-slate-200 opacity-80'
                            }`}
                        >
                            <span className="text-lg mt-0.5 w-6 text-center shrink-0">{icon || '•'}</span>
                            <div className="flex flex-col min-w-0 flex-1">
                                <p className="text-xs font-semibold text-slate-800 leading-snug">{step.description}</p>
                                <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-500">
                                    {step.distance_m ? <span>{step.distance_m}m</span> : null}
                                    {step.building_name && step.floor_level != null ? (
                                        <span className="text-indigo-600 font-medium">{step.building_name} F{step.floor_level}</span>
                                    ) : null}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Mobile Route QR Code Card (Pinned at bottom of info panel) */}
            {qrSession && qrSession.qr_code_data_url && (
                <div className="bg-white border-t border-slate-200 p-3 shrink-0 flex flex-col gap-1.5 shadow-sm z-20">
                    <div className="flex items-center gap-3">
                        <div 
                            onClick={() => setShowQrModal(true)}
                            className="w-16 h-16 bg-white p-1 rounded-xl shrink-0 flex items-center justify-center cursor-pointer border border-slate-200 shadow-sm hover:ring-2 hover:ring-indigo-400 hover:scale-105 transition-all group"
                            title="Click to expand QR Code"
                        >
                            <img 
                                src={qrSession.qr_code_data_url} 
                                alt="Mobile Route QR Code" 
                                className="w-full h-full object-contain" 
                            />
                        </div>
                        <div className="flex flex-col min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                                <span className="text-indigo-600 text-xs">📱</span>
                                <span className="text-xs font-bold text-slate-900 tracking-wide">Mobile Navigation</span>
                            </div>
                            <p className="text-[11px] text-slate-600 font-medium leading-tight mt-0.5">
                                Scan to view this route on your phone
                            </p>
                            <div className="flex items-center gap-2 mt-1.5">
                                <span className="text-[9px] text-indigo-700 font-mono bg-indigo-50 px-1.5 py-0.5 rounded border border-indigo-200">
                                    ⏱️ {qrSession.expires_in_minutes || 15}m session
                                </span>
                                <a 
                                    href={qrSession.mobile_url} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="text-[10px] text-indigo-600 hover:text-indigo-700 underline font-semibold flex items-center gap-0.5 cursor-pointer"
                                    title="Open mobile route view in a new browser tab"
                                >
                                    Open link ↗
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Expand QR Modal */}
            {showQrModal && qrSession && (
                <div 
                    className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4"
                    onClick={() => setShowQrModal(false)}
                >
                    <div 
                        className="bg-white border border-slate-200 rounded-2xl p-6 max-w-sm w-full flex flex-col items-center text-center shadow-2xl relative"
                        onClick={e => e.stopPropagation()}
                    >
                        <button 
                            onClick={() => setShowQrModal(false)}
                            className="absolute top-3 right-3 text-slate-400 hover:text-slate-700 text-lg w-8 h-8 rounded-lg flex items-center justify-center hover:bg-slate-100 cursor-pointer"
                        >
                            ✕
                        </button>
                        <div className="w-10 h-10 rounded-xl bg-indigo-50 text-indigo-600 border border-indigo-200 flex items-center justify-center text-xl mb-3">
                            📱
                        </div>
                        <h3 className="text-lg font-bold text-slate-900 mb-1">Mobile Route Companion</h3>
                        <p className="text-xs text-slate-500 mb-4 max-w-xs">
                            Scan to view this route on your phone
                        </p>
                        
                        <div className="bg-slate-50 p-3 rounded-2xl border border-slate-200 shadow-inner mb-4">
                            <img 
                                src={qrSession.qr_code_data_url} 
                                alt="QR Code" 
                                className="w-56 h-56 object-contain" 
                            />
                        </div>

                        <div className="flex items-center gap-2">
                            <span className="text-xs text-indigo-700 font-mono bg-indigo-50 px-2.5 py-1 rounded-md border border-indigo-200 font-semibold">
                                ⏱️ Expires in {qrSession.expires_in_minutes || 15} minutes
                            </span>
                        </div>
                        <a 
                            href={qrSession.mobile_url} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="w-full py-2 px-4 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer mt-3"
                        >
                            <span>Open Route Directly</span>
                            <span>↗</span>
                        </a>
                    </div>
                </div>
            )}
        </div>
    );
}
