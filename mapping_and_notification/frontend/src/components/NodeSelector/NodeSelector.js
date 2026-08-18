/**
 * @file NodeSelector.js
 * @description A reusable searchable autocomplete component for selecting campus nodes.
 *
 * Replaces native <select> dropdowns with a searchable, keyboard-navigable
 * autocomplete selector that formats nodes as:
 *   "{BUILDING} F{FLOOR} - {NODE NAME}"
 *
 * Business rules (e.g., transition node filtering) are applied by the PARENT
 * before passing nodes to this component. NodeSelector itself is generic.
 */

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';

/**
 * Builds a human-readable label for a node.
 * Format: "{BUILDING} F{FLOOR} - {NODE NAME}"
 * For transition nodes (ELEVATOR/STAIRWELL), appends "(TYPE)".
 *
 * @param {object} node - The node object from global nodes.
 * @returns {string}
 */
function buildNodeLabel(node) {
    const name = node.room_label || `Node ${node.node_id}`;
    const base = `${node.building_name} F${node.floor_level} - ${name}`;
    const isTransition = node.node_type === 'ELEVATOR' || node.node_type === 'STAIRWELL';
    return isTransition ? `${base} (${node.node_type})` : base;
}

/**
 * NodeSelector — Searchable node autocomplete component.
 *
 * @param {object[]} nodes        - Array of node objects to select from (pre-filtered by parent).
 * @param {string|number} value   - Currently selected node_id.
 * @param {Function} onChange     - Callback called with the selected node_id string.
 * @param {string} [placeholder]  - Placeholder text for the search input.
 * @param {string} [id]           - Optional id for the root element.
 */
export function NodeSelector({ nodes = [], value, onChange, placeholder = 'Search or select node...', id }) {
    const [isOpen, setIsOpen]               = useState(false);
    const [search, setSearch]               = useState('');
    const [buildingFilter, setBuildingFilter] = useState('');
    const [floorFilter, setFloorFilter]     = useState('');
    const [highlightedIdx, setHighlightedIdx] = useState(0);

    const containerRef  = useRef(null);
    const inputRef      = useRef(null);
    const listRef       = useRef(null);

    // ─── Derive buildings / floors from the supplied nodes ──────────────────────
    const buildings = useMemo(() => {
        const set = new Set(nodes.map(n => n.building_name).filter(Boolean));
        return Array.from(set).sort();
    }, [nodes]);

    const floors = useMemo(() => {
        const relevant = buildingFilter
            ? nodes.filter(n => n.building_name === buildingFilter)
            : nodes;
        const set = new Set(relevant.map(n => n.floor_level).filter(v => v != null));
        return Array.from(set).sort((a, b) => Number(a) - Number(b));
    }, [nodes, buildingFilter]);

    // ─── Labelled node list ──────────────────────────────────────────────────────
    const labelledNodes = useMemo(() =>
        nodes.map(n => ({ ...n, label: buildNodeLabel(n) })),
    [nodes]);

    // ─── Filtered results ────────────────────────────────────────────────────────
    const filtered = useMemo(() => {
        const q = search.toLowerCase().trim();
        return labelledNodes.filter(n => {
            if (buildingFilter && n.building_name !== buildingFilter) return false;
            if (floorFilter && String(n.floor_level) !== String(floorFilter)) return false;
            if (!q) return true;
            return (
                n.label.toLowerCase().includes(q) ||
                (n.node_type || '').toLowerCase().includes(q)
            );
        });
    }, [labelledNodes, search, buildingFilter, floorFilter]);

    // ─── Resolve the display label for the currently selected value ─────────────
    const selectedLabel = useMemo(() => {
        if (!value) return '';
        const found = labelledNodes.find(n => String(n.node_id) === String(value));
        return found ? found.label : '';
    }, [value, labelledNodes]);

    // ─── Reset highlighted index when results change ─────────────────────────────
    useEffect(() => { setHighlightedIdx(0); }, [filtered]);

    // ─── Reset building/floor filters when building changes ──────────────────────
    useEffect(() => { setFloorFilter(''); }, [buildingFilter]);

    // ─── Close on outside click ───────────────────────────────────────────────────
    useEffect(() => {
        function handleOutside(e) {
            if (containerRef.current && !containerRef.current.contains(e.target)) {
                setIsOpen(false);
                setSearch('');
            }
        }
        document.addEventListener('mousedown', handleOutside);
        return () => document.removeEventListener('mousedown', handleOutside);
    }, []);

    // ─── Scroll highlighted item into view ───────────────────────────────────────
    useEffect(() => {
        if (!listRef.current) return;
        const item = listRef.current.children[highlightedIdx];
        if (item) item.scrollIntoView({ block: 'nearest' });
    }, [highlightedIdx]);

    // ─── Handlers ────────────────────────────────────────────────────────────────
    const openDropdown = useCallback(() => {
        setIsOpen(true);
        setSearch('');
        setHighlightedIdx(0);
        setTimeout(() => inputRef.current?.focus(), 0);
    }, []);

    const selectNode = useCallback((node) => {
        onChange(String(node.node_id));
        setIsOpen(false);
        setSearch('');
    }, [onChange]);

    const clearSelection = useCallback((e) => {
        e.stopPropagation();
        onChange('');
        setIsOpen(false);
        setSearch('');
    }, [onChange]);

    const handleKeyDown = useCallback((e) => {
        if (!isOpen) {
            if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
                e.preventDefault();
                openDropdown();
            }
            return;
        }
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                setHighlightedIdx(i => Math.min(i + 1, filtered.length - 1));
                break;
            case 'ArrowUp':
                e.preventDefault();
                setHighlightedIdx(i => Math.max(i - 1, 0));
                break;
            case 'Enter':
                e.preventDefault();
                if (filtered[highlightedIdx]) selectNode(filtered[highlightedIdx]);
                break;
            case 'Escape':
                setIsOpen(false);
                setSearch('');
                break;
            default:
                break;
        }
    }, [isOpen, filtered, highlightedIdx, openDropdown, selectNode]);

    // ─── Render ───────────────────────────────────────────────────────────────────
    return (
        <div
            id={id}
            ref={containerRef}
            style={{ position: 'relative', width: '100%' }}
            onKeyDown={handleKeyDown}
        >
            {/* ── Trigger Button ── */}
            <button
                type="button"
                onClick={isOpen ? () => { setIsOpen(false); setSearch(''); } : openDropdown}
                style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    width: '100%', padding: '6px 8px',
                    background: '#020617', border: '1px solid #1e293b',
                    borderRadius: '6px', cursor: 'pointer',
                    fontSize: '11px', color: selectedLabel ? '#e2e8f0' : '#64748b',
                    textAlign: 'left', gap: '4px', lineHeight: '1.4',
                }}
                aria-haspopup="listbox"
                aria-expanded={isOpen}
            >
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {selectedLabel || placeholder}
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '2px', flexShrink: 0 }}>
                    {value && (
                        <span
                            onClick={clearSelection}
                            title="Clear selection"
                            style={{
                                fontSize: '12px', color: '#64748b', lineHeight: 1,
                                padding: '0 2px', cursor: 'pointer',
                            }}
                        >
                            ✕
                        </span>
                    )}
                    <span style={{ color: '#475569', fontSize: '10px' }}>{isOpen ? '▲' : '▼'}</span>
                </span>
            </button>

            {/* ── Dropdown ── */}
            {isOpen && (
                <div style={{
                    position: 'absolute', zIndex: 9999, top: 'calc(100% + 4px)', left: 0, right: 0,
                    background: '#0f172a', border: '1px solid #1e293b',
                    borderRadius: '8px', boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
                    display: 'flex', flexDirection: 'column', overflow: 'hidden',
                }}>
                    {/* Building / Floor filters (shown when multiple buildings exist) */}
                    {buildings.length > 1 && (
                        <div style={{
                            display: 'flex', gap: '4px', padding: '6px 6px 0',
                        }}>
                            <select
                                value={buildingFilter}
                                onChange={e => setBuildingFilter(e.target.value)}
                                style={{
                                    flex: 1, background: '#020617', border: '1px solid #334155',
                                    borderRadius: '4px', color: '#94a3b8', fontSize: '10px', padding: '3px 4px',
                                    cursor: 'pointer',
                                }}
                            >
                                <option value="">All Buildings</option>
                                {buildings.map(b => <option key={b} value={b}>{b}</option>)}
                            </select>
                            <select
                                value={floorFilter}
                                onChange={e => setFloorFilter(e.target.value)}
                                style={{
                                    flex: 1, background: '#020617', border: '1px solid #334155',
                                    borderRadius: '4px', color: '#94a3b8', fontSize: '10px', padding: '3px 4px',
                                    cursor: 'pointer',
                                }}
                            >
                                <option value="">All Floors</option>
                                {floors.map(f => <option key={f} value={f}>F{f}</option>)}
                            </select>
                        </div>
                    )}

                    {/* Search input */}
                    <div style={{ padding: '6px', borderBottom: '1px solid #1e293b' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px',
                                      background: '#020617', border: '1px solid #334155',
                                      borderRadius: '5px', padding: '4px 8px' }}>
                            <span style={{ color: '#475569', fontSize: '11px' }}>🔍</span>
                            <input
                                ref={inputRef}
                                type="text"
                                value={search}
                                onChange={e => { setSearch(e.target.value); setHighlightedIdx(0); }}
                                placeholder="Type to search..."
                                style={{
                                    flex: 1, background: 'transparent', border: 'none',
                                    outline: 'none', color: '#e2e8f0', fontSize: '11px',
                                    caretColor: '#6366f1',
                                }}
                                autoComplete="off"
                            />
                        </div>
                    </div>

                    {/* Result list */}
                    <ul
                        ref={listRef}
                        role="listbox"
                        style={{
                            margin: 0, padding: '4px 0', listStyle: 'none',
                            overflowY: 'auto', maxHeight: '200px',
                        }}
                    >
                        {filtered.length === 0 ? (
                            <li style={{
                                padding: '10px 12px', fontSize: '11px',
                                color: '#475569', textAlign: 'center',
                            }}>
                                {search
                                    ? `No nodes found matching "${search}"`
                                    : 'No nodes available'}
                            </li>
                        ) : (
                            filtered.map((n, idx) => (
                                <li
                                    key={n.node_id}
                                    role="option"
                                    aria-selected={String(n.node_id) === String(value)}
                                    onClick={() => selectNode(n)}
                                    onMouseEnter={() => setHighlightedIdx(idx)}
                                    style={{
                                        padding: '6px 12px', cursor: 'pointer',
                                        fontSize: '11px', lineHeight: '1.4',
                                        color: String(n.node_id) === String(value) ? '#6366f1' : '#cbd5e1',
                                        background: idx === highlightedIdx
                                            ? '#1e293b'
                                            : String(n.node_id) === String(value)
                                                ? '#1a1a2e'
                                                : 'transparent',
                                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                        transition: 'background 0.1s',
                                    }}
                                >
                                    <span>{n.label}</span>
                                    {String(n.node_id) === String(value) && (
                                        <span style={{ color: '#6366f1', fontSize: '10px' }}>✓</span>
                                    )}
                                </li>
                            ))
                        )}
                    </ul>

                    {/* Result count footer */}
                    {filtered.length > 0 && (
                        <div style={{
                            padding: '4px 12px', fontSize: '9px', color: '#334155',
                            borderTop: '1px solid #1e293b', textAlign: 'right',
                        }}>
                            {filtered.length} node{filtered.length !== 1 ? 's' : ''} found
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
