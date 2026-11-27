import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Building2,
  Check,
  Cpu,
  Grid3x3,
  Layers,
  List,
  Plus,
  Search,
  Shield,
  SlidersHorizontal,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { isCorridorNode } from '../utils/nodeUtils';
import { useToast } from '../providers/ToastProvider';
import { StatusBadge } from '../components/ui/StatusBadge';

export function RbacMatrixPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [mode, setMode] = useState('node'); // 'node' | 'device'
  const [layout, setLayout] = useState('list'); // 'list' | 'matrix'
  const [matrixDimension, setMatrixDimension] = useState('groups'); // 'groups' | 'roles'
  const [search, setSearch] = useState('');
  const [buildingFilter, setBuildingFilter] = useState('ALL');
  const [levelFilter, setLevelFilter] = useState('ALL');
  const [busyKey, setBusyKey] = useState('');

  // Slide-over policy editor drawer for a single node or device
  const [drawerTarget, setDrawerTarget] = useState(null); // { type: 'node' | 'device', id: string | number }
  const [drawerUserSearch, setDrawerUserSearch] = useState('');

  // Inline quick group dropdown per row
  const [quickGroupRow, setQuickGroupRow] = useState(null); // `${mode}:${id}` | null

  const { data, isLoading } = useQuery({
    queryKey: ['rbac-matrix'],
    queryFn: () => cloudApi.get('/api/infra/rbac-matrix'),
  });

  const { data: userSearchRes } = useQuery({
    queryKey: ['rbac-drawer-user-picker', drawerUserSearch],
    queryFn: () =>
      cloudApi.get(`/api/iam/users/paginated?page=1&page_size=15&q=${encodeURIComponent(drawerUserSearch.trim())}`),
    enabled: Boolean(drawerTarget),
    staleTime: 15_000,
  });

  const roles = data?.roles ?? [];
  const groups = data?.groups ?? [];
  const nodes = useMemo(
    () => (data?.nodes ?? []).filter((n) => !isCorridorNode(n)),
    [data?.nodes]
  );
  const devices = data?.devices ?? [];

  const groupsById = useMemo(
    () => Object.fromEntries(groups.map((g) => [g.group_id, g])),
    [groups]
  );
  const rolesById = useMemo(
    () => Object.fromEntries(roles.map((r) => [r.role_id, r])),
    [roles]
  );

  const buildings = useMemo(
    () => Array.from(new Set(nodes.map((n) => n.building_name).filter(Boolean))).sort(),
    [nodes]
  );

  const levelsForBuilding = useMemo(() => {
    const scoped = buildingFilter === 'ALL' ? nodes : nodes.filter((n) => n.building_name === buildingFilter);
    return Array.from(new Set(scoped.map((n) => n.floor_level).filter((lv) => lv !== null && lv !== undefined && String(lv).trim() !== ''))).sort(
      (a, b) => String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
    );
  }, [nodes, buildingFilter]);

  const handleBuildingChange = (nextBuilding) => {
    setBuildingFilter(nextBuilding);
    setLevelFilter('ALL');
  };

  const filteredNodes = useMemo(() => {
    const q = search.trim().toLowerCase();
    return nodes.filter((n) => {
      const mB = buildingFilter === 'ALL' || n.building_name === buildingFilter;
      const mL = levelFilter === 'ALL' || String(n.floor_level) === String(levelFilter);
      const mQ =
        !q ||
        n.room_label?.toLowerCase().includes(q) ||
        n.building_name?.toLowerCase().includes(q) ||
        String(n.floor_level || '').toLowerCase().includes(q);
      return mB && mL && mQ;
    });
  }, [nodes, search, buildingFilter, levelFilter]);

  const filteredDevices = useMemo(() => {
    const q = search.trim().toLowerCase();
    return devices.filter(
      (d) => !q || d.device_name?.toLowerCase().includes(q) || d.device_id?.toLowerCase().includes(q)
    );
  }, [devices, search]);

  const activeDrawerItem = useMemo(() => {
    if (!drawerTarget) return null;
    if (drawerTarget.type === 'node') {
      return nodes.find((n) => String(n.node_id) === String(drawerTarget.id)) || null;
    }
    return devices.find((d) => String(d.device_id) === String(drawerTarget.id)) || null;
  }, [drawerTarget, nodes, devices]);

  const drawerUserCandidates = useMemo(() => {
    if (!activeDrawerItem) return [];
    const existing = new Set(activeDrawerItem.user_ids || []);
    return (userSearchRes?.items || []).filter((u) => !existing.has(u.user_id));
  }, [userSearchRes, activeDrawerItem]);

  const handleToggleRole = async (targetType, targetId, roleId, currentAllowed) => {
    const key = `role:${targetType}:${targetId}:${roleId}`;
    if (busyKey) return;
    setBusyKey(key);
    try {
      await cloudApi.put('/api/infra/rbac-matrix/toggle', {
        target_type: targetType,
        target_id: String(targetId),
        role_id: roleId,
        allowed: !currentAllowed,
      });
      toast.success(`Updated ${targetType} role rule.`);
      queryClient.invalidateQueries({ queryKey: ['rbac-matrix'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusyKey('');
    }
  };

  const handleToggleGroup = async (targetType, targetId, groupId, currentAllowed) => {
    const key = `group:${targetType}:${targetId}:${groupId}`;
    if (busyKey) return;
    setBusyKey(key);
    try {
      await cloudApi.put('/api/infra/rbac-matrix/toggle-group', {
        target_type: targetType,
        target_id: String(targetId),
        group_id: groupId,
        allowed: !currentAllowed,
      });
      toast.success(`Updated ${targetType} access group.`);
      queryClient.invalidateQueries({ queryKey: ['rbac-matrix'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusyKey('');
    }
  };

  const handleToggleUser = async (targetType, targetId, userId, allowed) => {
    const key = `user:${targetType}:${targetId}:${userId}`;
    if (busyKey) return;
    setBusyKey(key);
    try {
      await cloudApi.put('/api/infra/rbac-matrix/toggle-user', {
        target_type: targetType,
        target_id: String(targetId),
        user_id: userId,
        allowed,
      });
      toast.success(allowed ? 'Granted individual user access.' : 'Removed individual user access.');
      queryClient.invalidateQueries({ queryKey: ['rbac-matrix'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusyKey('');
    }
  };

  const rows = mode === 'node' ? filteredNodes : filteredDevices;

  return (
    <div className="space-y-5" onClick={() => quickGroupRow && setQuickGroupRow(null)}>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
            Access Policy Settings
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Assign reusable Access Groups to rooms or devices, and fine-tune individual role or user overrides.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            onClick={() => navigate('/dashboard/roles?tab=groups')}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 hover:border-indigo-400 transition-colors"
          >
            <Layers className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" /> Manage Groups ({groups.length})
          </button>

          <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-1">
            <button
              type="button"
              onClick={() => {
                setMode('node');
                setDrawerTarget(null);
              }}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${
                mode === 'node'
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
              }`}
            >
              <Building2 className="w-3.5 h-3.5" /> Rooms & Nodes ({nodes.length})
            </button>
            <button
              type="button"
              onClick={() => {
                setMode('device');
                setDrawerTarget(null);
              }}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${
                mode === 'device'
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
              }`}
            >
              <Cpu className="w-3.5 h-3.5" /> Edge Devices ({devices.length})
            </button>
          </div>
        </div>
      </div>

      {/* Filters & Layout Switcher */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="flex flex-wrap items-center gap-2.5 flex-1">
          <div className="relative flex-1 min-w-[200px] max-w-xs">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={mode === 'node' ? 'Search room, building, or level...' : 'Search device name or ID...'}
              className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
            />
          </div>

          {mode === 'node' && buildings.length > 0 && (
            <select
              value={buildingFilter}
              onChange={(e) => handleBuildingChange(e.target.value)}
              aria-label="Filter by building"
              className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
            >
              <option value="ALL">All Buildings</option>
              {buildings.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          )}

          {mode === 'node' && levelsForBuilding.length > 0 && (
            <select
              value={levelFilter}
              onChange={(e) => setLevelFilter(e.target.value)}
              aria-label="Filter by level"
              className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
            >
              <option value="ALL">All Levels</option>
              {levelsForBuilding.map((lv) => (
                <option key={lv} value={lv}>Level {lv}</option>
              ))}
            </select>
          )}

          {(search || buildingFilter !== 'ALL' || levelFilter !== 'ALL') && (
            <button
              type="button"
              onClick={() => {
                setSearch('');
                setBuildingFilter('ALL');
                setLevelFilter('ALL');
              }}
              className="text-xs font-semibold text-slate-500 hover:text-indigo-600 px-2 py-1"
            >
              Reset
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {layout === 'matrix' && (
            <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 p-0.5">
              <button
                type="button"
                onClick={() => setMatrixDimension('groups')}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-colors ${
                  matrixDimension === 'groups'
                    ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
                    : 'text-slate-500 hover:text-slate-900'
                }`}
              >
                Groups
              </button>
              <button
                type="button"
                onClick={() => setMatrixDimension('roles')}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-colors ${
                  matrixDimension === 'roles'
                    ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
                    : 'text-slate-500 hover:text-slate-900'
                }`}
              >
                Roles
              </button>
            </div>
          )}

          <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 p-0.5">
            <button
              type="button"
              onClick={() => setLayout('list')}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold flex items-center gap-1 transition-colors ${
                layout === 'list'
                  ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
                  : 'text-slate-500 hover:text-slate-900'
              }`}
            >
              <List className="w-3.5 h-3.5" /> Policy View
            </button>
            <button
              type="button"
              onClick={() => setLayout('matrix')}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold flex items-center gap-1 transition-colors ${
                layout === 'matrix'
                  ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
                  : 'text-slate-500 hover:text-slate-900'
              }`}
            >
              <Grid3x3 className="w-3.5 h-3.5" /> Matrix
            </button>
          </div>
        </div>
      </div>

      {/* Main Content */}
      {isLoading ? (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-16 text-center text-sm text-slate-500">
          Loading access policies...
        </div>
      ) : rows.length === 0 ? (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-12 text-center text-sm text-slate-500">
          No {mode === 'node' ? 'locations' : 'devices'} match the current filters.
        </div>
      ) : layout === 'list' ? (
        /* CLEAN UNIFIED POLICY VIEW */
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-xs overflow-visible">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm border-collapse">
              <thead className="bg-slate-50/95 dark:bg-slate-900/95 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="py-3 px-4 text-xs font-bold uppercase tracking-wider text-slate-500 min-w-[230px]">
                    {mode === 'node' ? 'Location / Room' : 'Edge Device'}
                  </th>
                  <th className="py-3 px-4 text-xs font-bold uppercase tracking-wider text-slate-500 min-w-[260px]">
                    Access Groups
                  </th>
                  <th className="py-3 px-4 text-xs font-bold uppercase tracking-wider text-slate-500 min-w-[220px]">
                    Individual Roles & Users
                  </th>
                  <th className="py-3 px-4 text-right text-xs font-bold uppercase tracking-wider text-slate-500 w-[130px]">
                    Policy
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map((item) => {
                  const isNode = mode === 'node';
                  const targetId = isNode ? item.node_id : item.device_id;
                  const rowKey = `${mode}:${targetId}`;
                  const hasOverrides = !isNode && Boolean(item.uses_device_override);
                  const assignedGroups = (item.group_ids || []).map((gid) => groupsById[gid]).filter(Boolean);
                  const inheritedGroups = !isNode && !hasOverrides
                    ? (item.inherited_group_ids || []).map((gid) => groupsById[gid]).filter(Boolean)
                    : [];
                  const directRoles = (item.role_ids || []).map((rid) => rolesById[rid]).filter(Boolean);
                  const directUsers = item.direct_users || [];
                  const inheritedRoles = !isNode && !hasOverrides
                    ? (item.inherited_role_ids || []).map((rid) => rolesById[rid]).filter(Boolean)
                    : [];
                  const inheritedUsers = !isNode && !hasOverrides ? item.inherited_users || [] : [];

                  return (
                    <tr key={targetId} className="hover:bg-slate-50/70 dark:hover:bg-slate-800/30 transition-colors">
                      {/* Location / Device */}
                      <td className="py-3.5 px-4 align-top">
                        {isNode ? (
                          <>
                            <div className="font-bold text-slate-900 dark:text-slate-100">{item.room_label}</div>
                            <div className="text-xs text-slate-500 mt-0.5">
                              {item.building_name}
                              {item.floor_level ? ` · Level ${item.floor_level}` : ''} · {item.node_type}
                            </div>
                          </>
                        ) : (
                          <>
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-bold text-slate-900 dark:text-slate-100">{item.device_name}</span>
                              <StatusBadge variant={hasOverrides ? 'info' : 'neutral'}>
                                {hasOverrides ? 'Override' : 'Inherited'}
                              </StatusBadge>
                            </div>
                            <div className="text-xs font-mono text-slate-500 mt-0.5">
                              {item.device_id} · Node #{item.node_id}
                            </div>
                          </>
                        )}
                      </td>

                      {/* Access Groups with 1-click inline picker */}
                      <td className="py-3.5 px-4 align-top">
                        <div className="flex flex-wrap items-center gap-1.5 relative">
                          {assignedGroups.map((g) => (
                            <span
                              key={g.group_id}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-indigo-50 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border border-indigo-200/80 dark:border-indigo-500/30"
                            >
                              <Layers className="w-3 h-3 opacity-75" />
                              {g.group_name}
                              <button
                                type="button"
                                disabled={busyKey === `group:${mode}:${targetId}:${g.group_id}`}
                                onClick={() => handleToggleGroup(mode, targetId, g.group_id, true)}
                                className="hover:text-red-600 ml-0.5"
                                aria-label={`Remove ${g.group_name}`}
                              >
                                <X className="w-3 h-3" />
                              </button>
                            </span>
                          ))}

                          {inheritedGroups.map((g) => (
                            <span
                              key={`inh-${g.group_id}`}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-200/70 dark:border-emerald-500/20"
                            >
                              {g.group_name}
                              <span className="text-[9px] opacity-75">(node)</span>
                            </span>
                          ))}

                          <div className="relative" onClick={(e) => e.stopPropagation()}>
                            <button
                              type="button"
                              onClick={() => setQuickGroupRow(quickGroupRow === rowKey ? null : rowKey)}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold border border-dashed border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:border-indigo-500 hover:text-indigo-600 transition-colors"
                            >
                              <Plus className="w-3 h-3" /> Group
                            </button>

                            {quickGroupRow === rowKey && (
                              <div className="absolute left-0 top-full mt-1.5 z-30 w-60 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-xl p-1.5 space-y-0.5">
                                {groups.length === 0 ? (
                                  <button
                                    type="button"
                                    onClick={() => navigate('/dashboard/roles?tab=groups')}
                                    className="w-full px-3 py-2 text-left text-xs font-semibold text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-500/10 rounded-lg"
                                  >
                                    + Create your first Access Group
                                  </button>
                                ) : (
                                  groups.map((g) => {
                                    const isAssigned = (item.group_ids || []).includes(g.group_id);
                                    return (
                                      <button
                                        key={g.group_id}
                                        type="button"
                                        disabled={Boolean(busyKey)}
                                        onClick={() => handleToggleGroup(mode, targetId, g.group_id, isAssigned)}
                                        className="w-full px-2.5 py-2 rounded-lg flex items-center justify-between text-left hover:bg-slate-50 dark:hover:bg-slate-800/70 transition-colors"
                                      >
                                        <div className="min-w-0 pr-2">
                                          <div className="text-xs font-bold text-slate-900 dark:text-slate-100 truncate">
                                            {g.group_name}
                                          </div>
                                          <div className="text-[10px] text-slate-400">
                                            {g.role_ids.length} role{g.role_ids.length === 1 ? '' : 's'} · {g.user_count} user{g.user_count === 1 ? '' : 's'}
                                          </div>
                                        </div>
                                        {isAssigned && <Check className="w-3.5 h-3.5 text-indigo-600 shrink-0" />}
                                      </button>
                                    );
                                  })
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Individual Roles & Users Summary */}
                      <td className="py-3.5 px-4 align-top">
                        <div className="flex flex-wrap gap-1">
                          {directRoles.map((r) => (
                            <span
                              key={r.role_id}
                              className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                            >
                              {r.role_name}
                            </span>
                          ))}
                          {directUsers.map((u) => (
                            <span
                              key={u.user_id}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-amber-50 dark:bg-amber-500/15 text-amber-800 dark:text-amber-300"
                            >
                              <Users className="w-2.5 h-2.5" /> {u.full_name}
                            </span>
                          ))}
                          {directRoles.length === 0 && directUsers.length === 0 && (
                            !isNode && !hasOverrides && (inheritedRoles.length > 0 || inheritedUsers.length > 0) ? (
                              <span className="text-xs text-slate-400">
                                Inheriting {inheritedRoles.length} role{inheritedRoles.length === 1 ? '' : 's'}
                                {inheritedUsers.length > 0 ? `, ${inheritedUsers.length} user${inheritedUsers.length === 1 ? '' : 's'}` : ''}
                              </span>
                            ) : (
                              <span className="text-xs text-slate-400">No individual overrides</span>
                            )
                          )}
                        </div>
                      </td>

                      {/* Configure Drawer Trigger */}
                      <td className="py-3.5 px-4 align-top text-right">
                        <button
                          type="button"
                          onClick={() => {
                            setDrawerUserSearch('');
                            setDrawerTarget({ type: mode, id: targetId });
                          }}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 hover:border-indigo-500 hover:text-indigo-600 transition-colors"
                        >
                          <SlidersHorizontal className="w-3.5 h-3.5" /> Configure
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* OPTIONAL COMPACT GRID MATRIX VIEW */
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-xs overflow-hidden">
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full text-left text-sm border-collapse">
              <thead className="bg-slate-50/95 dark:bg-slate-900/95 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="py-3 px-4 text-xs font-bold uppercase tracking-wider text-slate-500 min-w-[230px]">
                    {mode === 'node' ? 'Location / Room' : 'Edge Device'}
                  </th>
                  {matrixDimension === 'groups'
                    ? groups.map((g) => (
                        <th key={g.group_id} className="py-3 px-4 text-center min-w-[130px]">
                          <div className="text-xs font-extrabold text-slate-800 dark:text-slate-200">{g.group_name}</div>
                          <div className="text-[10px] font-mono text-slate-400">
                            {g.role_ids.length}R · {g.user_count}U
                          </div>
                        </th>
                      ))
                    : roles.map((r) => (
                        <th key={r.role_id} className="py-3 px-4 text-center min-w-[110px]">
                          <div className="text-xs font-extrabold uppercase text-slate-800 dark:text-slate-200">{r.role_name}</div>
                          <div className="text-[10px] font-mono text-slate-400">{r.user_count} users</div>
                        </th>
                      ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map((item) => {
                  const isNode = mode === 'node';
                  const targetId = isNode ? item.node_id : item.device_id;
                  const hasOverrides = !isNode && Boolean(item.uses_device_override);
                  return (
                    <tr key={targetId} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40">
                      <td className="py-3 px-4">
                        <div className="font-bold text-slate-900 dark:text-slate-100">
                          {isNode ? item.room_label : item.device_name}
                        </div>
                        <div className="text-xs text-slate-500">
                          {isNode
                            ? `${item.building_name}${item.floor_level ? ` · Level ${item.floor_level}` : ''}`
                            : `${item.device_id} · ${hasOverrides ? 'Override' : 'Inherited'}`}
                        </div>
                      </td>
                      {matrixDimension === 'groups'
                        ? groups.map((g) => {
                            const assigned = (item.group_ids || []).includes(g.group_id);
                            const inherited = !isNode && !hasOverrides && (item.inherited_group_ids || []).includes(g.group_id);
                            return (
                              <td key={g.group_id} className="py-3 px-4 text-center">
                                <div className="flex flex-col items-center gap-0.5">
                                  <input
                                    type="checkbox"
                                    disabled={busyKey === `group:${mode}:${targetId}:${g.group_id}`}
                                    checked={assigned}
                                    onChange={() => handleToggleGroup(mode, targetId, g.group_id, assigned)}
                                    className="w-4 h-4 rounded border-slate-300 dark:border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                                  />
                                  {inherited && <span className="text-[9px] font-semibold text-emerald-600">via node</span>}
                                </div>
                              </td>
                            );
                          })
                        : roles.map((r) => {
                            const direct = (item.role_ids || []).includes(r.role_id);
                            const viaGroup = !direct && (item.group_role_ids || []).includes(r.role_id);
                            const inherited = !isNode && !hasOverrides && (item.inherited_role_ids || []).includes(r.role_id);
                            return (
                              <td key={r.role_id} className="py-3 px-4 text-center">
                                <div className="flex flex-col items-center gap-0.5">
                                  <input
                                    type="checkbox"
                                    disabled={busyKey === `role:${mode}:${targetId}:${r.role_id}`}
                                    checked={direct}
                                    onChange={() => handleToggleRole(mode, targetId, r.role_id, direct)}
                                    className="w-4 h-4 rounded border-slate-300 dark:border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                                  />
                                  {viaGroup && <span className="text-[9px] font-semibold text-indigo-600">via group</span>}
                                  {!viaGroup && inherited && <span className="text-[9px] font-semibold text-emerald-600">via node</span>}
                                </div>
                              </td>
                            );
                          })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Slide-Over Access Policy Configuration Drawer */}
      {drawerTarget && activeDrawerItem && (
        <div
          className="fixed inset-0 z-[85] flex justify-end bg-slate-900/40 backdrop-blur-[1px]"
          onClick={() => setDrawerTarget(null)}
        >
          <div
            className="w-full max-w-md h-full bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 shadow-2xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Drawer Header */}
            <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-extrabold text-slate-900 dark:text-slate-100 truncate">
                    {drawerTarget.type === 'node' ? activeDrawerItem.room_label : activeDrawerItem.device_name}
                  </h2>
                  {drawerTarget.type === 'device' && (
                    <StatusBadge variant={activeDrawerItem.uses_device_override ? 'info' : 'neutral'}>
                      {activeDrawerItem.uses_device_override ? 'Override' : 'Inherited'}
                    </StatusBadge>
                  )}
                </div>
                <p className="text-xs text-slate-500 mt-0.5">
                  {drawerTarget.type === 'node'
                    ? `${activeDrawerItem.building_name}${activeDrawerItem.floor_level ? ` · Level ${activeDrawerItem.floor_level}` : ''}`
                    : `${activeDrawerItem.device_id} · Node #${activeDrawerItem.node_id}`}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setDrawerTarget(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Drawer Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Section 1: Access Groups */}
              <div className="space-y-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-indigo-500" /> Access Groups
                  </span>
                  <button
                    type="button"
                    onClick={() => navigate('/dashboard/roles?tab=groups')}
                    className="text-[11px] font-semibold text-indigo-600 hover:underline"
                  >
                    Manage Groups
                  </button>
                </div>
                {groups.length === 0 ? (
                  <p className="text-xs text-slate-400">No access groups created yet.</p>
                ) : (
                  <div className="space-y-2">
                    {groups.map((g) => {
                      const assigned = (activeDrawerItem.group_ids || []).includes(g.group_id);
                      const inherited =
                        drawerTarget.type === 'device' &&
                        !activeDrawerItem.uses_device_override &&
                        (activeDrawerItem.inherited_group_ids || []).includes(g.group_id);
                      return (
                        <label
                          key={g.group_id}
                          className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-colors ${
                            assigned
                              ? 'border-indigo-300 dark:border-indigo-500/40 bg-indigo-50/50 dark:bg-indigo-500/10'
                              : 'border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/40'
                          }`}
                        >
                          <div>
                            <div className="text-sm font-bold text-slate-900 dark:text-slate-100">{g.group_name}</div>
                            <div className="text-[11px] text-slate-500">
                              {g.role_names.length ? g.role_names.join(', ') : 'No roles'}
                              {g.user_count > 0 ? ` · +${g.user_count} user${g.user_count === 1 ? '' : 's'}` : ''}
                              {inherited && ' · Inherited from node'}
                            </div>
                          </div>
                          <input
                            type="checkbox"
                            disabled={Boolean(busyKey)}
                            checked={assigned}
                            onChange={() => handleToggleGroup(drawerTarget.type, drawerTarget.id, g.group_id, assigned)}
                            className="w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500"
                          />
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Section 2: Individual Roles */}
              <div className="space-y-2.5 pt-4 border-t border-slate-100 dark:border-slate-800">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-indigo-500" /> Individual Roles
                </span>
                <div className="grid grid-cols-2 gap-2">
                  {roles.map((r) => {
                    const direct = (activeDrawerItem.role_ids || []).includes(r.role_id);
                    const viaGroup = !direct && (activeDrawerItem.group_role_ids || []).includes(r.role_id);
                    const inherited =
                      drawerTarget.type === 'device' &&
                      !activeDrawerItem.uses_device_override &&
                      (activeDrawerItem.inherited_role_ids || []).includes(r.role_id);
                    return (
                      <label
                        key={r.role_id}
                        className={`flex items-center justify-between p-2.5 rounded-xl border cursor-pointer transition-colors ${
                          direct
                            ? 'border-indigo-300 dark:border-indigo-500/40 bg-indigo-50/50 dark:bg-indigo-500/10'
                            : 'border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/40'
                        }`}
                      >
                        <div className="min-w-0 pr-2">
                          <div className="text-xs font-bold text-slate-900 dark:text-slate-100 truncate">{r.role_name}</div>
                          {viaGroup && <div className="text-[10px] text-indigo-600 dark:text-indigo-400">via group</div>}
                          {!viaGroup && inherited && <div className="text-[10px] text-emerald-600 dark:text-emerald-400">via node</div>}
                        </div>
                        <input
                          type="checkbox"
                          disabled={Boolean(busyKey)}
                          checked={direct}
                          onChange={() => handleToggleRole(drawerTarget.type, drawerTarget.id, r.role_id, direct)}
                          className="w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 shrink-0"
                        />
                      </label>
                    );
                  })}
                </div>
              </div>

              {/* Section 3: Individual Users */}
              <div className="space-y-3 pt-4 border-t border-slate-100 dark:border-slate-800">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                  <UserPlus className="w-3.5 h-3.5 text-indigo-500" /> Individual Users
                </span>

                <div className="flex flex-wrap gap-1.5">
                  {(activeDrawerItem.direct_users || []).map((u) => (
                    <span
                      key={u.user_id}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-50 dark:bg-amber-500/15 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-500/30"
                    >
                      {u.full_name}
                      <button
                        type="button"
                        disabled={Boolean(busyKey)}
                        onClick={() => handleToggleUser(drawerTarget.type, drawerTarget.id, u.user_id, false)}
                        className="hover:text-red-600"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                  {(activeDrawerItem.direct_users || []).length === 0 && (
                    <span className="text-xs text-slate-400">No direct individual users assigned.</span>
                  )}
                </div>

                <div className="relative">
                  <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={drawerUserSearch}
                    onChange={(e) => setDrawerUserSearch(e.target.value)}
                    placeholder="Search user by name or email to grant access..."
                    className="w-full pl-9 pr-3 py-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-xs"
                  />
                </div>

                <div className="max-h-44 overflow-y-auto rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
                  {drawerUserCandidates.length === 0 ? (
                    <div className="p-3 text-xs text-slate-400 text-center">No matching users available.</div>
                  ) : (
                    drawerUserCandidates.map((u) => (
                      <button
                        key={u.user_id}
                        type="button"
                        disabled={Boolean(busyKey)}
                        onClick={() => handleToggleUser(drawerTarget.type, drawerTarget.id, u.user_id, true)}
                        className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-slate-50 dark:hover:bg-slate-800/50"
                      >
                        <div>
                          <div className="text-xs font-bold text-slate-900 dark:text-slate-100">{u.full_name}</div>
                          <div className="text-[10px] font-mono text-slate-500">{u.email}</div>
                        </div>
                        <span className="text-xs font-bold text-indigo-600 dark:text-indigo-400 flex items-center gap-0.5">
                          <Plus className="w-3.5 h-3.5" /> Add
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
