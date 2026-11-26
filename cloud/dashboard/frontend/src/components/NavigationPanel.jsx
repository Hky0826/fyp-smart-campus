/**
 * @file NavigationPanel.jsx
 * @description Route Tester drawer panel with searchable NodeSelectors, KPI summary cards,
 * and clickable turn-by-turn directions that switch the active floorplan automatically.
 */

import {
  AlertTriangle,
  ArrowDownUp,
  ArrowUp,
  Building2,
  Clock,
  Compass,
  CornerUpLeft,
  CornerUpRight,
  Flag,
  Layers,
  Loader2,
  MapPin,
  Navigation,
  RotateCcw,
} from 'lucide-react';
import { isCorridorNode } from '../utils/nodeUtils';
import { NodeSelector } from './NodeSelector/NodeSelector';

export function NavigationPanel({
  navPanelOpen,
  navResult,
  setNavResult,
  setNavHighlight,
  navError,
  setNavError,
  navStartId,
  setNavStartId,
  navEndId,
  setNavEndId,
  navRoleId,
  setNavRoleId,
  globalNodes,
  rolesList,
  handleRunNavigation,
  navLoading,
  setNotifVisitorId,
  setNotifVisitorEmail,
  setNotifMessage,
  setIsAutoMessage,
  currentFloorplanId,
  onSelectFloorplan,
}) {
  if (!navPanelOpen) return null;

  const destinationNodes = globalNodes.filter((n) => !isCorridorNode(n));

  const renderStepIcon = (step) => {
    switch (step.type) {
      case 'start':
        return <MapPin className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400" />;
      case 'arrive':
        return <Flag className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />;
      case 'turn':
        return step.action === 'left' ? (
          <CornerUpLeft className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
        ) : (
          <CornerUpRight className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
        );
      case 'transition':
        return <Layers className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />;
      default:
        return <ArrowUp className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />;
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-teal-50 dark:bg-teal-500/15 text-teal-600 dark:text-teal-400 flex items-center justify-center">
            <Compass className="w-4 h-4" />
          </div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
            Route Tester
          </h3>
        </div>
        {navResult && (
          <button
            type="button"
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
            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-bold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            Clear
          </button>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
        {/* Form Inputs */}
        <div className="space-y-3">
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
              Start Location
            </label>
            <NodeSelector
              id="nav-start-select"
              nodes={destinationNodes}
              value={navStartId}
              onChange={setNavStartId}
              placeholder="Search start location..."
            />
          </div>

          <div className="flex justify-center -my-1">
            <button
              id="nav-swap-btn"
              type="button"
              onClick={() => {
                const tmp = navStartId;
                setNavStartId(navEndId);
                setNavEndId(tmp);
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-[11px] font-semibold text-slate-500 hover:text-teal-600 dark:hover:text-teal-400 hover:border-teal-300 dark:hover:border-teal-500/40 transition-colors"
              title="Swap Start and Destination"
            >
              <ArrowDownUp className="w-3 h-3" />
              Swap
            </button>
          </div>

          <div>
            <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
              Destination
            </label>
            <NodeSelector
              id="nav-end-select"
              nodes={destinationNodes}
              value={navEndId}
              onChange={setNavEndId}
              placeholder="Search destination..."
            />
          </div>

          <div>
            <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
              Simulate User Role (RBAC)
            </label>
            <select
              id="nav-role-select"
              value={navRoleId}
              onChange={(e) => setNavRoleId(e.target.value)}
              className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:border-teal-500 cursor-pointer"
            >
              <option value="">-- Select campus role --</option>
              {rolesList.map((r) => (
                <option key={r.role_id} value={r.role_id}>
                  {r.role_name}
                </option>
              ))}
            </select>
          </div>

          <button
            id="nav-find-route-btn"
            type="button"
            onClick={handleRunNavigation}
            disabled={navLoading || !navStartId || !navEndId || !navRoleId}
            className="w-full py-2.5 rounded-xl bg-teal-600 hover:bg-teal-700 disabled:opacity-40 text-white text-xs font-bold flex items-center justify-center gap-2 transition-colors shadow-xs"
          >
            {navLoading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Calculating Route...</span>
              </>
            ) : (
              <>
                <Navigation className="w-3.5 h-3.5" />
                <span>Find Route</span>
              </>
            )}
          </button>
        </div>

        {/* Error */}
        {navError && (
          <div className="rounded-xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/40 p-3 flex items-start gap-2.5 text-xs text-red-700 dark:text-red-400">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{navError}</span>
          </div>
        )}

        {/* Route Summary */}
        {navResult?.route_summary && (
          <div className="rounded-xl border border-teal-200 dark:border-teal-500/30 bg-teal-50/60 dark:bg-teal-950/30 p-3.5 space-y-3">
            <div>
              <span className="text-[10px] font-extrabold uppercase tracking-wider text-teal-700 dark:text-teal-400">
                Active Route
              </span>
              <div className="mt-1 text-xs font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                <span className="truncate">{navResult.route_summary.start_label}</span>
                <span className="text-slate-400">→</span>
                <span className="truncate">{navResult.route_summary.destination_label}</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 p-2 text-center">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block">
                  Distance
                </span>
                <span className="text-sm font-extrabold text-teal-600 dark:text-teal-400 tabular-nums">
                  {navResult.route_summary.total_distance_m}m
                </span>
              </div>
              <div className="rounded-lg bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 p-2 text-center">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-center gap-1">
                  <Clock className="w-2.5 h-2.5" />
                  Est. Time
                </span>
                <span className="text-sm font-extrabold text-teal-600 dark:text-teal-400 tabular-nums">
                  {navResult.route_summary.estimated_time_label}
                </span>
              </div>
              {navResult.route_summary.floor_transitions > 0 && (
                <div
                  className={`rounded-lg bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 p-2 text-center ${
                    navResult.route_summary.building_transitions > 0 ? '' : 'col-span-2'
                  }`}
                >
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block">
                    Floor Changes
                  </span>
                  <span className="text-sm font-extrabold text-amber-600 dark:text-amber-400 tabular-nums">
                    {navResult.route_summary.floor_transitions}
                  </span>
                </div>
              )}
              {navResult.route_summary.building_transitions > 0 && (
                <div
                  className={`rounded-lg bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 p-2 text-center ${
                    navResult.route_summary.floor_transitions > 0 ? '' : 'col-span-2'
                  }`}
                >
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block">
                    Building Crossings
                  </span>
                  <span className="text-sm font-extrabold text-indigo-600 dark:text-indigo-400 tabular-nums">
                    {navResult.route_summary.building_transitions}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Turn-by-Turn Instructions */}
        {navResult?.instructions?.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                Turn-by-Turn Directions
              </h4>
              <span className="text-[10px] text-slate-400">Click step to jump floor</span>
            </div>
            <div className="space-y-1.5">
              {navResult.instructions.map((step, idx) => {
                const isOnCurrentFloor =
                  step.floorplan_id && String(step.floorplan_id) === String(currentFloorplanId);
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      if (step.floorplan_id && onSelectFloorplan) {
                        onSelectFloorplan(String(step.floorplan_id));
                      }
                    }}
                    className={`w-full text-left flex items-start gap-2.5 p-2.5 rounded-xl border transition-colors ${
                      isOnCurrentFloor
                        ? 'bg-teal-50/50 dark:bg-teal-500/10 border-teal-200 dark:border-teal-500/30'
                        : 'bg-slate-50/70 dark:bg-slate-950/60 border-slate-200/80 dark:border-slate-800 hover:border-indigo-300 dark:hover:border-indigo-500/40'
                    }`}
                  >
                    <div className="mt-0.5 shrink-0">{renderStepIcon(step)}</div>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-slate-800 dark:text-slate-200 leading-snug">
                        {step.description}
                      </p>
                      <div className="flex items-center gap-2 mt-1 text-[10px] text-slate-500">
                        {step.building_name && (
                          <span className="inline-flex items-center gap-1">
                            <Building2 className="w-2.5 h-2.5" />
                            {step.building_name} F{step.floor_level}
                          </span>
                        )}
                        {step.type === 'walk' && step.distance_m != null && (
                          <span className="font-mono font-semibold tabular-nums">
                            {step.distance_m}m
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
