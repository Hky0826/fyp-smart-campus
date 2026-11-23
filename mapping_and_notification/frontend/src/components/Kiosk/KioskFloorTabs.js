import React from 'react';

export function KioskFloorTabs({ floorplanOrder, activeFloorplanId, setActiveFloorplanId, mapContext }) {
    if (!floorplanOrder || floorplanOrder.length <= 1) return null;

    return (
        <div className="bg-slate-900/90 border-b border-slate-800 px-3 py-1.5 flex gap-2 overflow-x-auto shadow-sm z-10 shrink-0 scrollbar-none">
            {floorplanOrder.map((fpId, index) => {
                const isActive = fpId === activeFloorplanId;
                const context = mapContext?.[fpId] || {};
                const name = context.building_name || `Building`;
                const level = context.floor_level != null ? context.floor_level : '?';

                return (
                    <button
                        key={`${fpId}-${index}`}
                        onClick={() => setActiveFloorplanId(fpId)}
                        className={`
                            whitespace-nowrap px-3 py-1 rounded-md text-xs font-bold transition-all duration-150 border cursor-pointer
                            ${isActive 
                                ? 'bg-teal-600 text-white border-teal-500 shadow-[0_0_10px_rgba(20,184,166,0.3)]' 
                                : 'bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700 hover:text-slate-200'
                            }
                        `}
                    >
                        <div className="flex items-center gap-1.5">
                            <span className="text-[9px] uppercase tracking-wider opacity-75">Step {index + 1}:</span>
                            <span>{name} F{level}</span>
                        </div>
                    </button>
                );
            })}
        </div>
    );
}
