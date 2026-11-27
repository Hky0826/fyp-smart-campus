/**
 * @file PropertiesPanel.jsx
 * @description Contextual inspector for editing Node properties, Cross-Floor Transitions,
 * and Edge/Path properties with full Light/Dark Smart Campus Console theming.
 */

import {
  ArrowLeftRight,
  GitBranch,
  Layers,
  Link2,
  MapPin,
  Minus,
  Shield,
  Sparkles,
  Trash2,
  X,
  Zap,
} from 'lucide-react';
import { NODE_TYPES } from '../constants/mapConstants';
import { NodeSelector } from './NodeSelector/NodeSelector';

export function PropertiesPanel({
  appMode,
  handleDeleteSelected,
  selectedElement,
  setSelectedElement,
  activeObj,
  isTransitionNode,
  activeNodeTab,
  setActiveNodeTab,
  updateProperty,
  handleRoleToggle,
  handleGroupToggle,
  rolesList,
  accessGroupsList = [],
  edges,
  nodes,
  globalNodes,
  currentFloorplanId,
  transitionTargetId,
  setTransitionTargetId,
  transitionWeight,
  setTransitionWeight,
  transitionIsAccessible,
  setTransitionIsAccessible,
  transitionIsBidirectional,
  setTransitionIsBidirectional,
  currentBuildingName,
  currentFloorLevel,
  handleUpdateTransition,
  handleDeleteTransition,
  handleCreateTransition,
  triggerSelectedEdgeAStar,
  resetSelectedEdgeToStraight,
}) {
  if (!activeObj) return null;

  const isNode = selectedElement.type === 'node';

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
              isNode
                ? 'bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400'
                : 'bg-teal-50 dark:bg-teal-500/15 text-teal-600 dark:text-teal-400'
            }`}
          >
            {isNode ? <MapPin className="w-4 h-4" /> : <Link2 className="w-4 h-4" />}
          </div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 truncate">
            {isNode ? 'Node Properties' : 'Path Properties'}
          </h3>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {appMode === 'edit' && (
            <button
              type="button"
              onClick={handleDeleteSelected}
              className="p-1.5 rounded-lg text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors"
              title="Delete selected element"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
          <button
            type="button"
            onClick={() => setSelectedElement({ type: null, index: null })}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title="Close inspector"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Scrollable Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
        {isNode && (
          <>
            {/* Segmented Tab for Transition Nodes */}
            {isTransitionNode && (
              <div className="grid grid-cols-2 p-1 rounded-xl bg-slate-100 dark:bg-slate-950 border border-slate-200 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setActiveNodeTab('general')}
                  className={`py-1.5 rounded-lg text-xs font-bold transition-all ${
                    activeNodeTab === 'general'
                      ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
                      : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                  }`}
                >
                  General
                </button>
                <button
                  type="button"
                  onClick={() => setActiveNodeTab('transition')}
                  className={`py-1.5 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1 ${
                    activeNodeTab === 'transition'
                      ? 'bg-white dark:bg-slate-800 text-purple-600 dark:text-purple-400 shadow-xs'
                      : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                  }`}
                >
                  <GitBranch className="w-3.5 h-3.5" />
                  <span>Floor Linker</span>
                </button>
              </div>
            )}

            {/* AI Generated Node Review Badge */}
            {activeObj.ai_generated && (
              <div
                className={`rounded-xl border p-3 space-y-2 ${
                  activeObj.review_status === 'PENDING'
                    ? 'bg-teal-50/70 dark:bg-teal-950/40 border-teal-200 dark:border-teal-800/60'
                    : 'bg-sky-50/70 dark:bg-sky-950/40 border-sky-200 dark:border-sky-800/60'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span
                    className={`text-[10px] font-extrabold uppercase tracking-wider flex items-center gap-1.5 ${
                      activeObj.review_status === 'PENDING'
                        ? 'text-teal-700 dark:text-teal-400'
                        : 'text-sky-700 dark:text-sky-400'
                    }`}
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    AI Generated
                  </span>
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      activeObj.review_status === 'PENDING'
                        ? 'bg-teal-100 dark:bg-teal-500/20 text-teal-700 dark:text-teal-300'
                        : 'bg-sky-100 dark:bg-sky-500/20 text-sky-700 dark:text-sky-300'
                    }`}
                  >
                    {activeObj.review_status || 'PENDING'}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-0.5">
                      Confidence
                    </span>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-teal-500 rounded-full"
                          style={{ width: `${Math.round((activeObj.ai_confidence || 0) * 100)}%` }}
                        />
                      </div>
                      <span className="text-xs font-bold text-slate-900 dark:text-white tabular-nums">
                        {Math.round((activeObj.ai_confidence || 0) * 100)}%
                      </span>
                    </div>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-0.5">
                      Source
                    </span>
                    <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                      {activeObj.ai_source === 'gemini_vision'
                        ? 'Gemini Vision'
                        : activeObj.ai_source === 'room_detection+ocr'
                          ? 'Room + OCR'
                          : 'Room Detection'}
                    </span>
                  </div>
                </div>

                <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
                  {activeObj.review_status === 'PENDING'
                    ? 'Edit the label, type, or position to mark this node as reviewed.'
                    : 'Reviewed. Save the map to persist your changes.'}
                </p>
              </div>
            )}

            {/* General Tab */}
            {(!isTransitionNode || activeNodeTab === 'general') && (
              <div className="space-y-4">
                <div>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1.5">
                    Room Label
                  </label>
                  <input
                    type="text"
                    value={activeObj.room_label || ''}
                    onChange={(e) => updateProperty('room_label', e.target.value)}
                    className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500 focus:bg-white dark:focus:bg-slate-950"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1.5">
                    Node Type
                  </label>
                  <select
                    value={activeObj.node_type || 'OTHER'}
                    onChange={(e) => updateProperty('node_type', e.target.value)}
                    className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    {NODE_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>

                <label className="flex items-center justify-between p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60 cursor-pointer">
                  <div>
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200 block">
                      Area is Accessible
                    </span>
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">
                      Allow routing through this node
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    checked={activeObj.is_accessible === 'ALLOW'}
                    onChange={(e) =>
                      updateProperty('is_accessible', e.target.checked ? 'ALLOW' : 'DENY')
                    }
                    className="w-4 h-4 rounded accent-indigo-600 cursor-pointer"
                  />
                </label>

                {/* Node Access Groups */}
                <div className="pt-3 border-t border-slate-200 dark:border-slate-800 space-y-2">
                  <div className="flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-indigo-500" />
                    <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">
                      Access Groups
                    </h4>
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    Assign reusable access groups to grant multiple roles or users at once.
                  </p>
                  <div className="space-y-1.5 p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60">
                    {accessGroupsList.length === 0 ? (
                      <p className="text-[11px] text-slate-400">No access groups created yet.</p>
                    ) : (
                      accessGroupsList.map((grp) => {
                        const checked = (activeObj.assigned_group_ids || []).includes(grp.group_id);
                        return (
                          <label
                            key={grp.group_id}
                            className="flex items-start gap-2.5 text-xs font-medium text-slate-700 dark:text-slate-300 cursor-pointer select-none py-0.5"
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => handleGroupToggle && handleGroupToggle(grp.group_id)}
                              className="w-3.5 h-3.5 mt-0.5 rounded accent-indigo-600 cursor-pointer"
                            />
                            <div className="min-w-0">
                              <div className="font-semibold text-slate-800 dark:text-slate-200 truncate">
                                {grp.group_name}
                              </div>
                              <div className="text-[10px] text-slate-400">
                                {(grp.roles || []).length} role{(grp.roles || []).length === 1 ? '' : 's'} · {(grp.users || []).length} user{(grp.users || []).length === 1 ? '' : 's'}
                              </div>
                            </div>
                          </label>
                        );
                      })
                    )}
                  </div>
                </div>

                {/* Node RBAC (Individual Roles) */}
                <div className="pt-3 border-t border-slate-200 dark:border-slate-800 space-y-2">
                  <div className="flex items-center gap-1.5">
                    <Shield className="w-3.5 h-3.5 text-indigo-500" />
                    <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">
                      Individual Campus Roles
                    </h4>
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    Direct role permissions (in addition to any assigned groups).
                  </p>
                  <div className="space-y-1.5 p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60">
                    {rolesList.map((role) => {
                      const checked = (activeObj.allowed_roles || []).includes(role.role_id);
                      const viaGroup = !checked && accessGroupsList.some(
                        (g) =>
                          (activeObj.assigned_group_ids || []).includes(g.group_id) &&
                          (g.roles || []).some((r) => r.role_id === role.role_id)
                      );
                      return (
                        <label
                          key={role.role_id}
                          className="flex items-center justify-between gap-2 text-xs font-medium text-slate-700 dark:text-slate-300 cursor-pointer select-none py-0.5"
                        >
                          <span className="flex items-center gap-2.5">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => handleRoleToggle(role.role_id)}
                              className="w-3.5 h-3.5 rounded accent-indigo-600 cursor-pointer"
                            />
                            <span>{role.role_name}</span>
                          </span>
                          {viaGroup && (
                            <span className="text-[10px] font-semibold text-indigo-600 dark:text-indigo-400">
                              via group
                            </span>
                          )}
                        </label>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* Transition Linker Tab */}
            {isTransitionNode &&
              activeNodeTab === 'transition' &&
              (() => {
                const existingTransitionIndex = edges.findIndex(
                  (e) => e.start === selectedElement.index && e.is_cross_floor
                );
                const hasExistingTransition = existingTransitionIndex !== -1;
                const existingEdge = hasExistingTransition
                  ? edges[existingTransitionIndex]
                  : null;

                const targetNode = hasExistingTransition
                  ? globalNodes.find((gn) => gn.node_id === existingEdge.target_node_id)
                  : null;

                const startNode = nodes[selectedElement.index];
                const targetNodeId = hasExistingTransition
                  ? existingEdge.target_node_id
                  : transitionTargetId;
                const startRoles = startNode?.allowed_roles || [];
                const targetNodeObj = globalNodes.find(
                  (gn) => Number(gn.node_id) === Number(targetNodeId)
                );
                const targetRoles = targetNodeObj
                  ? typeof targetNodeObj.allowed_roles === 'string'
                    ? targetNodeObj.allowed_roles.split(',').map(Number)
                    : targetNodeObj.allowed_roles || []
                  : [];
                const derivedTransitionRoles = startRoles.filter((r) => targetRoles.includes(r));

                return (
                  <div className="space-y-3.5">
                    <div className="p-3 rounded-xl bg-purple-50 dark:bg-purple-500/10 border border-purple-200 dark:border-purple-500/20">
                      <h4 className="text-xs font-bold text-purple-700 dark:text-purple-300">
                        {hasExistingTransition
                          ? 'Active Cross-Floor Link'
                          : 'Create Cross-Floor Link'}
                      </h4>
                      <p className="text-[11px] text-purple-600/80 dark:text-purple-300/70 mt-0.5">
                        {hasExistingTransition
                          ? 'Modify distance or accessibility for this transition.'
                          : 'Connect this elevator, stairwell, or entrance to another floorplan.'}
                      </p>
                    </div>

                    <div>
                      <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                        Target Destination Node
                      </label>
                      {hasExistingTransition ? (
                        <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-800 dark:text-slate-200">
                          {targetNode
                            ? `${targetNode.building_name} F${targetNode.floor_level} — ${targetNode.room_label}`
                            : `Target Node (ID: ${existingEdge.target_node_id})`}
                        </div>
                      ) : (
                        <NodeSelector
                          nodes={globalNodes.filter((gn) => {
                            const isSameType = gn.node_type === activeObj.node_type;
                            const isDiffFloorplan =
                              gn.floorplan_id !== Number(currentFloorplanId);
                            if (
                              activeObj.node_type === 'ELEVATOR' ||
                              activeObj.node_type === 'STAIRWELL'
                            ) {
                              const isSameBuilding = gn.building_name === currentBuildingName;
                              const isDiffFloor =
                                Number(gn.floor_level) !== Number(currentFloorLevel);
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

                    <div>
                      <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                        Real-World Distance (meters)
                      </label>
                      <input
                        type="number"
                        value={transitionWeight}
                        onChange={(e) => setTransitionWeight(e.target.value)}
                        className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs font-mono font-semibold text-slate-900 dark:text-slate-100 focus:outline-none focus:border-purple-500"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-3 p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60">
                      <div className="space-y-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 block">
                          Settings
                        </span>
                        <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={transitionIsAccessible}
                            onChange={(e) => setTransitionIsAccessible(e.target.checked)}
                            className="w-3.5 h-3.5 rounded accent-purple-600"
                          />
                          Accessible
                        </label>
                        <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={transitionIsBidirectional}
                            onChange={(e) => setTransitionIsBidirectional(e.target.checked)}
                            className="w-3.5 h-3.5 rounded accent-purple-600"
                          />
                          Bidirectional
                        </label>
                      </div>
                      <div className="space-y-1.5">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 block">
                          Derived RBAC
                        </span>
                        {rolesList.map((role) => (
                          <label
                            key={role.role_id}
                            className="flex items-center gap-1.5 text-[11px] text-slate-500 select-none"
                          >
                            <input
                              type="checkbox"
                              checked={derivedTransitionRoles.includes(role.role_id)}
                              disabled
                              className="w-3 h-3 rounded accent-purple-600 opacity-60"
                            />
                            {role.role_name}
                          </label>
                        ))}
                      </div>
                    </div>

                    {appMode === 'edit' &&
                      (hasExistingTransition ? (
                        <div className="space-y-2 pt-1">
                          <button
                            type="button"
                            onClick={() => handleUpdateTransition(existingTransitionIndex)}
                            className="w-full py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-bold transition-colors"
                          >
                            Update Transition Link
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteTransition(existingTransitionIndex)}
                            className="w-full py-2 rounded-xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/50 text-xs font-bold transition-colors"
                          >
                            Delete Transition Link
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={handleCreateTransition}
                          className="w-full py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-bold transition-colors"
                        >
                          Create Transition Link
                        </button>
                      ))}
                  </div>
                );
              })()}
          </>
        )}

        {/* EDGE PANEL UI */}
        {!isNode && (
          <div className="space-y-4">
            <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60 space-y-2">
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-500">Total Distance</span>
                <span className="font-mono font-bold text-slate-900 dark:text-white tabular-nums">
                  {activeObj.weight} m
                </span>
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-500">Path Routing</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                    activeObj.isCustom
                      ? 'bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300'
                      : 'bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300'
                  }`}
                >
                  {activeObj.isCustom ? 'Manual / Custom' : 'AI Routed'}
                </span>
              </div>
            </div>

            {!activeObj.is_cross_floor && appMode === 'edit' && (
              <div className="space-y-2">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 block">
                  Path Geometry
                </span>
                <button
                  type="button"
                  onClick={triggerSelectedEdgeAStar}
                  className="w-full py-2 px-3 rounded-xl border border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-500/25 text-xs font-bold flex items-center justify-center gap-1.5 transition-colors"
                >
                  <Zap className="w-3.5 h-3.5" />
                  <span>Re-Route with AI (Wall-Avoiding)</span>
                </button>
                <button
                  type="button"
                  onClick={resetSelectedEdgeToStraight}
                  className="w-full py-2 px-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
                >
                  <Minus className="w-3.5 h-3.5" />
                  <span>Straight Line Fallback</span>
                </button>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Tip: Double-click on a path segment to insert a waypoint; double-click a waypoint
                  to delete it.
                </p>
              </div>
            )}

            {activeObj.is_cross_floor && (
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                  Manual Distance (meters)
                </label>
                <input
                  type="number"
                  value={activeObj.weight}
                  onChange={(e) => updateProperty('weight', e.target.value)}
                  className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs font-mono font-semibold text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500"
                />
              </div>
            )}

            <div className="space-y-2">
              <label className="flex items-center justify-between p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60 cursor-pointer">
                <span className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-2">
                  <ArrowLeftRight className="w-3.5 h-3.5 text-indigo-500" />
                  Bidirectional Path
                </span>
                <input
                  type="checkbox"
                  checked={activeObj.is_bidirectional}
                  onChange={(e) => updateProperty('is_bidirectional', e.target.checked)}
                  className="w-4 h-4 rounded accent-indigo-600 cursor-pointer"
                />
              </label>
              <label className="flex items-center justify-between p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60 cursor-pointer">
                <span className="text-xs font-bold text-slate-800 dark:text-slate-200">
                  Path is Accessible
                </span>
                <input
                  type="checkbox"
                  checked={activeObj.is_accessible === 'ALLOW'}
                  onChange={(e) =>
                    updateProperty('is_accessible', e.target.checked ? 'ALLOW' : 'DENY')
                  }
                  className="w-4 h-4 rounded accent-indigo-600 cursor-pointer"
                />
              </label>
            </div>

            <div className="pt-3 border-t border-slate-200 dark:border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">
                  Allowed Campus Roles
                </h4>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500">
                  Auto-Derived
                </span>
              </div>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                Intersection of roles permitted on both connected nodes.
              </p>
              <div className="space-y-1.5 p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60">
                {rolesList.map((role) => (
                  <label
                    key={role.role_id}
                    className="flex items-center gap-2.5 text-xs text-slate-500 select-none"
                  >
                    <input
                      type="checkbox"
                      checked={(activeObj.allowed_roles || []).includes(role.role_id)}
                      disabled
                      className="w-3.5 h-3.5 rounded accent-indigo-600 opacity-60"
                    />
                    <span>{role.role_name}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
