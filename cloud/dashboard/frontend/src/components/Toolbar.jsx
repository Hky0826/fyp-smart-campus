/**
 * @file Toolbar.jsx
 * @description Clean, spacious Top Command Bar for the Campus Map Studio.
 * Includes inline Floorplan Quick-Switcher + Upload trigger so the left drawer
 * stays collapsed by default, maximizing canvas breathing room.
 */

import {
  Bell,
  Compass,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Redo2,
  Save,
  Sparkles,
  Tag,
  Undo2,
} from 'lucide-react';

export function Toolbar({
  appMode,
  setAppMode,
  currentFloorplanId,
  floorplansList,
  loadFloorplanData,
  setUploadModalOpen,
  navPanelOpen,
  setNavPanelOpen,
  notifPanelOpen,
  setNotifPanelOpen,
  handleSaveMapData,
  isSaving,
  isDirty,
  nodes,
  edges,
  handleAiAnalyze,
  isAnalyzing,
  leftDrawerOpen,
  setLeftDrawerOpen,
  showAllLabels,
  setShowAllLabels,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
}) {
  return (
    <div className="h-14 shrink-0 px-3 sm:px-4 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
      {/* Left: Drawer Toggle + Inline Floorplan Switcher + Upload */}
      <div className="flex items-center gap-2 min-w-0">
        <button
          type="button"
          onClick={() => setLeftDrawerOpen((v) => !v)}
          className={`p-2 rounded-xl border transition-colors shrink-0 ${
            leftDrawerOpen
              ? 'border-indigo-300 dark:border-indigo-500/40 bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400'
              : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-600 dark:text-slate-300 hover:border-indigo-400'
          }`}
          title={leftDrawerOpen ? 'Hide Floorplan Manager' : 'Open Floorplan Manager & Settings'}
        >
          {leftDrawerOpen ? (
            <PanelLeftClose className="w-4 h-4" />
          ) : (
            <PanelLeftOpen className="w-4 h-4" />
          )}
        </button>

        <select
          value={currentFloorplanId || ''}
          onChange={(e) => loadFloorplanData(e.target.value)}
          className="max-w-[200px] sm:max-w-[240px] rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-bold text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500 cursor-pointer truncate"
          aria-label="Select floorplan"
        >
          <option value="" disabled>
            Select a floorplan...
          </option>
          {floorplansList.map((fp) => (
            <option key={fp.floorplan_id} value={fp.floorplan_id}>
              {fp.building_name} — Floor {fp.floor_level}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={() => setUploadModalOpen(true)}
          className="p-2 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-600 dark:text-slate-300 hover:border-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors shrink-0"
          title="Upload New Floorplan"
        >
          <Plus className="w-4 h-4" />
        </button>

        {currentFloorplanId && (
          <div className="hidden lg:flex items-center gap-2 pl-1">
            <span className="text-[11px] font-medium text-slate-400 dark:text-slate-500 tabular-nums">
              {nodes.length}n · {edges.length}e
            </span>
            {isDirty && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-50 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-500/30">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                Unsaved
              </span>
            )}
          </div>
        )}
      </div>

      {/* Center: Mode Switch (Edit vs Test) */}
      <div className="flex items-center p-1 rounded-xl bg-slate-100 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 shrink-0">
        <button
          type="button"
          onClick={() => {
            setAppMode('edit');
            setNavPanelOpen(false);
            setNotifPanelOpen(false);
          }}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
            appMode === 'edit'
              ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
              : 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
          }`}
        >
          <Pencil className="w-3.5 h-3.5" />
          <span>Edit</span>
        </button>
        <button
          type="button"
          onClick={() => {
            setAppMode('test');
            if (!navPanelOpen && !notifPanelOpen) {
              setNavPanelOpen(true);
            }
          }}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
            appMode === 'test'
              ? 'bg-white dark:bg-slate-800 text-teal-600 dark:text-teal-400 shadow-xs'
              : 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
          }`}
        >
          <Compass className="w-3.5 h-3.5" />
          <span>Test</span>
        </button>
      </div>

      {/* Right: Contextual Actions */}
      <div className="flex items-center gap-2 shrink-0">
        {currentFloorplanId && (
          <button
            type="button"
            onClick={() => setShowAllLabels((v) => !v)}
            className={`hidden md:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-semibold border transition-colors ${
              showAllLabels
                ? 'bg-indigo-50 dark:bg-indigo-500/15 border-indigo-200 dark:border-indigo-500/30 text-indigo-700 dark:text-indigo-300'
                : 'bg-slate-50 dark:bg-slate-950 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100'
            }`}
            title="Show room labels on canvas"
          >
            <Tag className="w-3.5 h-3.5" />
            <span>Labels</span>
          </button>
        )}

        {appMode === 'edit' && currentFloorplanId && (
          <>
            <div className="inline-flex items-center rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 p-0.5">
              <button
                type="button"
                onClick={onUndo}
                disabled={!canUndo}
                className="p-1.5 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white disabled:opacity-35 disabled:pointer-events-none transition-colors"
                title="Undo unsaved change (Ctrl+Z)"
                aria-label="Undo"
              >
                <Undo2 className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={onRedo}
                disabled={!canRedo}
                className="p-1.5 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white disabled:opacity-35 disabled:pointer-events-none transition-colors"
                title="Redo (Ctrl+Y)"
                aria-label="Redo"
              >
                <Redo2 className="w-3.5 h-3.5" />
              </button>
            </div>

            <button
              id="ai-analyze-btn"
              type="button"
              onClick={handleAiAnalyze}
              disabled={isAnalyzing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border border-teal-200 dark:border-teal-500/30 bg-teal-50 dark:bg-teal-500/15 text-teal-700 dark:text-teal-300 hover:bg-teal-100 dark:hover:bg-teal-500/25 disabled:opacity-50 transition-colors"
              title="Auto-generate all rooms, corridors, wall-avoiding paths, RBAC roles, and floor links"
            >
              {isAnalyzing ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span className="hidden sm:inline">Mapping...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">AI Auto-Map</span>
                </>
              )}
            </button>

            <button
              type="button"
              onClick={() => handleSaveMapData(nodes, edges)}
              disabled={isSaving}
              className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold text-white transition-all shadow-xs disabled:opacity-50 ${
                isDirty
                  ? 'bg-indigo-600 hover:bg-indigo-700 ring-2 ring-indigo-500/25'
                  : 'bg-indigo-600 hover:bg-indigo-700'
              }`}
              title="Save map graph to database (Ctrl+S)"
            >
              {isSaving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Save className="w-3.5 h-3.5" />
              )}
              <span>{isSaving ? 'Saving...' : 'Save'}</span>
            </button>
          </>
        )}

        {appMode === 'test' && (
          <>
            <button
              type="button"
              onClick={() => {
                setNavPanelOpen(true);
                setNotifPanelOpen(false);
              }}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border transition-colors ${
                navPanelOpen
                  ? 'bg-teal-50 dark:bg-teal-500/15 border-teal-200 dark:border-teal-500/30 text-teal-700 dark:text-teal-300'
                  : 'bg-slate-50 dark:bg-slate-950 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300'
              }`}
            >
              <Compass className="w-3.5 h-3.5" />
              <span>Route</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setNotifPanelOpen(true);
                setNavPanelOpen(false);
              }}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border transition-colors ${
                notifPanelOpen
                  ? 'bg-indigo-50 dark:bg-indigo-500/15 border-indigo-200 dark:border-indigo-500/30 text-indigo-700 dark:text-indigo-300'
                  : 'bg-slate-50 dark:bg-slate-950 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300'
              }`}
            >
              <Bell className="w-3.5 h-3.5" />
              <span>Notify</span>
            </button>
          </>
        )}
      </div>
    </div>
  );
}
