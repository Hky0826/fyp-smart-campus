/**
 * @file NodeSelector.jsx
 * @description Reusable searchable autocomplete selector for campus nodes.
 * Supports light/dark Smart Campus Console theming, building/floor filters, and keyboard navigation.
 */

import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Check, ChevronDown, Search, X } from 'lucide-react';

function buildNodeLabel(node) {
  const name = node.room_label || `Node ${node.node_id}`;
  const base = `${node.building_name} F${node.floor_level} — ${name}`;
  const isTransition = node.node_type === 'ELEVATOR' || node.node_type === 'STAIRWELL';
  return isTransition ? `${base} (${node.node_type})` : base;
}

export function NodeSelector({
  nodes = [],
  value,
  onChange,
  placeholder = 'Search or select node...',
  id,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [buildingFilter, setBuildingFilter] = useState('');
  const [floorFilter, setFloorFilter] = useState('');
  const [highlightedIdx, setHighlightedIdx] = useState(0);

  const containerRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  const buildings = useMemo(() => {
    const set = new Set(nodes.map((n) => n.building_name).filter(Boolean));
    return Array.from(set).sort();
  }, [nodes]);

  const floors = useMemo(() => {
    const relevant = buildingFilter
      ? nodes.filter((n) => n.building_name === buildingFilter)
      : nodes;
    const set = new Set(relevant.map((n) => n.floor_level).filter((v) => v != null));
    return Array.from(set).sort((a, b) => Number(a) - Number(b));
  }, [nodes, buildingFilter]);

  const labelledNodes = useMemo(
    () => nodes.map((n) => ({ ...n, label: buildNodeLabel(n) })),
    [nodes]
  );

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return labelledNodes.filter((n) => {
      if (buildingFilter && n.building_name !== buildingFilter) return false;
      if (floorFilter && String(n.floor_level) !== String(floorFilter)) return false;
      if (!q) return true;
      return (
        n.label.toLowerCase().includes(q) ||
        (n.node_type || '').toLowerCase().includes(q)
      );
    });
  }, [labelledNodes, search, buildingFilter, floorFilter]);

  const selectedLabel = useMemo(() => {
    if (!value) return '';
    const found = labelledNodes.find((n) => String(n.node_id) === String(value));
    return found ? found.label : '';
  }, [value, labelledNodes]);

  useEffect(() => {
    setHighlightedIdx(0);
  }, [filtered]);

  useEffect(() => {
    setFloorFilter('');
  }, [buildingFilter]);

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

  useEffect(() => {
    if (!listRef.current) return;
    const item = listRef.current.children[highlightedIdx];
    if (item) item.scrollIntoView({ block: 'nearest' });
  }, [highlightedIdx]);

  const openDropdown = useCallback(() => {
    setIsOpen(true);
    setSearch('');
    setHighlightedIdx(0);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const selectNode = useCallback(
    (node) => {
      onChange(String(node.node_id));
      setIsOpen(false);
      setSearch('');
    },
    [onChange]
  );

  const clearSelection = useCallback(
    (e) => {
      e.stopPropagation();
      onChange('');
      setIsOpen(false);
      setSearch('');
    },
    [onChange]
  );

  const handleKeyDown = useCallback(
    (e) => {
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
          setHighlightedIdx((i) => Math.min(i + 1, filtered.length - 1));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setHighlightedIdx((i) => Math.max(i - 1, 0));
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
    },
    [isOpen, filtered, highlightedIdx, openDropdown, selectNode]
  );

  return (
    <div id={id} ref={containerRef} className="relative w-full" onKeyDown={handleKeyDown}>
      <button
        type="button"
        onClick={
          isOpen
            ? () => {
                setIsOpen(false);
                setSearch('');
              }
            : openDropdown
        }
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className={`flex items-center justify-between w-full px-3 py-2 rounded-xl border text-xs text-left gap-2 transition-colors ${
          isOpen
            ? 'border-indigo-500 ring-2 ring-indigo-500/15 bg-white dark:bg-slate-950'
            : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 hover:border-slate-300 dark:hover:border-slate-700'
        } ${
          selectedLabel
            ? 'text-slate-900 dark:text-slate-100 font-medium'
            : 'text-slate-400 dark:text-slate-500'
        }`}
      >
        <span className="flex-1 truncate">{selectedLabel || placeholder}</span>
        <span className="flex items-center gap-1 shrink-0">
          {value && (
            <span
              role="button"
              tabIndex={-1}
              onClick={clearSelection}
              title="Clear selection"
              className="p-0.5 rounded hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
            >
              <X className="w-3.5 h-3.5" />
            </span>
          )}
          <ChevronDown
            className={`w-3.5 h-3.5 text-slate-400 transition-transform ${
              isOpen ? 'rotate-180' : ''
            }`}
          />
        </span>
      </button>

      {isOpen && (
        <div className="absolute z-50 top-[calc(100%+6px)] left-0 right-0 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xl overflow-hidden flex flex-col">
          {buildings.length > 1 && (
            <div className="flex gap-1.5 p-2 pb-0">
              <select
                value={buildingFilter}
                onChange={(e) => setBuildingFilter(e.target.value)}
                className="flex-1 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-300 focus:outline-none focus:border-indigo-500"
              >
                <option value="">All Buildings</option>
                {buildings.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
              <select
                value={floorFilter}
                onChange={(e) => setFloorFilter(e.target.value)}
                className="w-24 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-2 py-1 text-[11px] text-slate-700 dark:text-slate-300 focus:outline-none focus:border-indigo-500"
              >
                <option value="">All Floors</option>
                {floors.map((f) => (
                  <option key={f} value={f}>
                    F{f}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="p-2 border-b border-slate-100 dark:border-slate-800">
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-2.5 py-1.5">
              <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
              <input
                ref={inputRef}
                type="text"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setHighlightedIdx(0);
                }}
                placeholder="Type to search..."
                className="flex-1 bg-transparent border-0 outline-none text-xs text-slate-900 dark:text-slate-100 placeholder:text-slate-400"
                autoComplete="off"
              />
            </div>
          </div>

          <ul
            ref={listRef}
            role="listbox"
            className="py-1 overflow-y-auto max-h-52 scrollbar-thin"
          >
            {filtered.length === 0 ? (
              <li className="px-3 py-4 text-xs text-slate-400 text-center">
                {search ? `No nodes matching "${search}"` : 'No nodes available'}
              </li>
            ) : (
              filtered.map((n, idx) => {
                const isSelected = String(n.node_id) === String(value);
                const isHighlighted = idx === highlightedIdx;
                return (
                  <li
                    key={n.node_id}
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => selectNode(n)}
                    onMouseEnter={() => setHighlightedIdx(idx)}
                    className={`px-3 py-2 cursor-pointer text-xs flex items-center justify-between gap-2 transition-colors ${
                      isSelected
                        ? 'text-indigo-600 dark:text-indigo-400 font-semibold bg-indigo-50/70 dark:bg-indigo-500/10'
                        : isHighlighted
                          ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100'
                          : 'text-slate-700 dark:text-slate-300'
                    }`}
                  >
                    <span className="truncate">{n.label}</span>
                    {isSelected && <Check className="w-3.5 h-3.5 shrink-0" />}
                  </li>
                );
              })
            )}
          </ul>

          {filtered.length > 0 && (
            <div className="px-3 py-1.5 text-[10px] font-medium text-slate-400 border-t border-slate-100 dark:border-slate-800 text-right tabular-nums">
              {filtered.length} node{filtered.length !== 1 ? 's' : ''}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
