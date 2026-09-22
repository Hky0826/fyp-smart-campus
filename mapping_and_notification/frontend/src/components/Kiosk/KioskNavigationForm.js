import React, { useState, useRef, useEffect } from 'react';

function SearchableSelect({ value, onChange, options, placeholder }) {
    const [isOpen, setIsOpen] = useState(false);
    const [search, setSearch] = useState('');
    const wrapperRef = useRef(null);

    const selectedOption = options.find(opt => opt.value === value || String(opt.value) === String(value));

    useEffect(() => {
        function handleClickOutside(event) {
            if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        }
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const filteredOptions = options.filter(opt => 
        opt.label.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div ref={wrapperRef} className="relative w-full">
            <div 
                className="w-full h-10 bg-slate-800/90 border border-slate-700 rounded-lg flex items-center px-3 cursor-pointer hover:border-slate-500 transition-colors shadow-inner"
                onClick={() => setIsOpen(!isOpen)}
            >
                <span className={`text-sm truncate ${value ? 'text-white font-medium' : 'text-slate-400'}`}>
                    {selectedOption ? selectedOption.label : placeholder}
                </span>
                <span className="ml-auto text-slate-400 text-xs pl-2">▼</span>
            </div>

            {isOpen && (
                <div className="absolute top-full left-0 w-full mt-1.5 bg-slate-800 border border-slate-700 rounded-lg shadow-2xl overflow-hidden z-50 flex flex-col max-h-64">
                    <div className="p-2 border-b border-slate-700 shrink-0 bg-slate-850">
                        <input
                            type="text"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Type to filter..."
                            className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-teal-500"
                            onClick={(e) => e.stopPropagation()}
                            autoFocus
                        />
                    </div>
                    <div className="overflow-y-auto scrollbar-thin scrollbar-thumb-slate-600">
                        {filteredOptions.length > 0 ? (
                            filteredOptions.map((opt) => (
                                <div
                                    key={opt.value}
                                    className="px-3 py-2 hover:bg-teal-900/40 cursor-pointer text-xs text-slate-200 border-b border-slate-700/40 last:border-0 truncate"
                                    onClick={() => {
                                        onChange(opt.value);
                                        setIsOpen(false);
                                        setSearch('');
                                    }}
                                >
                                    {opt.label}
                                </div>
                            ))
                        ) : (
                            <div className="px-3 py-2 text-xs text-slate-500">No locations found.</div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

export function KioskNavigationForm({
    startId, setStartId,
    endId, setEndId,
    roleId, setRoleId,
    handleNavigate, clearRoute,
    loading, error,
    globalNodes, rolesList,
    hasResult
}) {
    // Filter out corridors and map to options format
    const nodeOptions = globalNodes
        .filter(n => {
            if (n.node_type === 'CORRIDOR') return false;
            if (n.room_label && n.room_label.toLowerCase().includes('corridor')) return false;
            return true;
        })
        .map(n => ({
            value: n.node_id,
            label: `${n.building_name} F${n.floor_level} — ${n.room_label}`
        }))
        .sort((a, b) => a.label.localeCompare(b.label));

    return (
        <div className="px-4 py-2 bg-slate-900 border-b border-slate-800 shadow-sm shrink-0 z-30 relative">
            {error && (
                <div className="mb-2 bg-red-950/70 border border-red-800/80 rounded-md py-1 px-3 text-xs text-red-300 font-medium flex items-center justify-between">
                    <span>⚠️ {error}</span>
                </div>
            )}
            
            <div className="flex flex-wrap lg:flex-nowrap gap-2.5 items-center">
                {/* From Field */}
                <div className="flex-1 min-w-[200px]">
                    <div className="flex items-center gap-1.5 mb-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-teal-400"></span>
                        <label className="text-[10px] font-bold text-teal-400 uppercase tracking-wider">Start Location</label>
                    </div>
                    <SearchableSelect 
                        value={startId}
                        onChange={setStartId}
                        options={nodeOptions}
                        placeholder="Choose starting point..."
                    />
                </div>

                {/* Swap Button */}
                <div className="shrink-0 pt-4">
                    <button 
                        onClick={() => {
                            const temp = startId;
                            setStartId(endId);
                            setEndId(temp);
                        }}
                        className="w-8 h-8 rounded-full bg-slate-800 hover:bg-slate-700 border border-slate-700 flex items-center justify-center text-slate-400 hover:text-white transition-colors shadow-sm cursor-pointer"
                        title="Swap locations"
                    >
                        ⇄
                    </button>
                </div>

                {/* To Field */}
                <div className="flex-1 min-w-[200px]">
                    <div className="flex items-center gap-1.5 mb-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                        <label className="text-[10px] font-bold text-amber-400 uppercase tracking-wider">Destination</label>
                    </div>
                    <SearchableSelect 
                        value={endId}
                        onChange={setEndId}
                        options={nodeOptions}
                        placeholder="Choose destination..."
                    />
                </div>

                {/* Role / Access Selector */}
                <div className="w-36 lg:w-44 shrink-0">
                    <div className="flex items-center gap-1.5 mb-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                        <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Access Level</label>
                    </div>
                    <select
                        value={
                            rolesList.find(r => 
                                String(r.role_id) === String(roleId) || 
                                r.role_name.toLowerCase() === String(roleId).toLowerCase()
                            )?.role_id || (typeof roleId === 'number' ? roleId : 4)
                        }
                        onChange={(e) => setRoleId(Number(e.target.value) || e.target.value)}
                        className="w-full h-10 bg-slate-800/90 border border-slate-700 rounded-lg px-3 text-xs text-white focus:outline-none focus:border-teal-500 appearance-none cursor-pointer"
                    >
                        {rolesList.map(r => (
                            <option key={r.role_id} value={r.role_id}>{r.role_name}</option>
                        ))}
                    </select>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-1.5 shrink-0 pt-4">
                    {hasResult && (
                        <button
                            onClick={() => clearRoute()}
                            className="h-10 px-3.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-xs font-semibold rounded-lg transition-colors border border-slate-700 cursor-pointer"
                        >
                            Clear
                        </button>
                    )}
                    <button
                        onClick={() => handleNavigate()}
                        disabled={loading || !startId || !endId}
                        className="h-10 px-5 bg-teal-600 hover:bg-teal-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-lg text-sm flex items-center justify-center gap-1.5 transition-colors shadow-md border-b-2 border-teal-700 active:border-b-0 active:translate-y-px cursor-pointer"
                    >
                        {loading ? '⌛ Routing...' : '🧭 Navigate'}
                    </button>
                </div>
            </div>
        </div>
    );
}
