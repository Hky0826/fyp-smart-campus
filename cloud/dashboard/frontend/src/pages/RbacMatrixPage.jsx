import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Building2, Cpu, Search } from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { StatusBadge } from '../components/ui/StatusBadge';

export function RbacMatrixPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [mode, setMode] = useState('node'); // 'node' | 'device'
  const [search, setSearch] = useState('');
  const [buildingFilter, setBuildingFilter] = useState('ALL');
  const [busyKey, setBusyKey] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['rbac-matrix'],
    queryFn: () => cloudApi.get('/api/infra/rbac-matrix'),
  });

  const roles = data?.roles ?? [];
  const nodes = data?.nodes ?? [];
  const devices = data?.devices ?? [];

  const buildings = useMemo(
    () => Array.from(new Set(nodes.map((n) => n.building_name).filter(Boolean))).sort(),
    [nodes]
  );

  const filteredNodes = useMemo(() => {
    const q = search.trim().toLowerCase();
    return nodes.filter((n) => {
      const mB = buildingFilter === 'ALL' || n.building_name === buildingFilter;
      const mQ = !q || n.room_label?.toLowerCase().includes(q) || n.building_name?.toLowerCase().includes(q);
      return mB && mQ;
    });
  }, [nodes, search, buildingFilter]);

  const filteredDevices = useMemo(() => {
    const q = search.trim().toLowerCase();
    return devices.filter(
      (d) => !q || d.device_name?.toLowerCase().includes(q) || d.device_id?.toLowerCase().includes(q)
    );
  }, [devices, search]);

  const handleToggle = async (targetType, targetId, roleId, currentAllowed) => {
    const key = `${targetType}:${targetId}:${roleId}`;
    if (busyKey) return;
    setBusyKey(key);
    try {
      await cloudApi.put('/api/infra/rbac-matrix/toggle', {
        target_type: targetType,
        target_id: String(targetId),
        role_id: roleId,
        allowed: !currentAllowed,
      });
      toast.success(`Updated ${targetType} access rule.`);
      queryClient.invalidateQueries({ queryKey: ['rbac-matrix'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusyKey('');
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
            Visual RBAC Policy Matrix
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Toggle role permissions across campus rooms and edge devices. Changes sync automatically to edge gates.
          </p>
        </div>

        <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-1">
          <button
            type="button"
            onClick={() => setMode('node')}
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
            onClick={() => setMode('device')}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${
              mode === 'device'
                ? 'bg-indigo-600 text-white'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
            }`}
          >
            <Cpu className="w-3.5 h-3.5" /> Device Overrides ({devices.length})
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={mode === 'node' ? 'Filter room or building...' : 'Filter device name or ID...'}
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
        {mode === 'node' && buildings.length > 0 && (
          <select
            value={buildingFilter}
            onChange={(e) => setBuildingFilter(e.target.value)}
            className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
          >
            <option value="ALL">All Buildings</option>
            {buildings.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        )}
      </div>

      {isLoading ? (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-16 text-center text-sm text-slate-500">
          Loading policy matrix...
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-xs overflow-hidden">
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full text-left text-sm border-collapse">
              <thead className="bg-slate-50/95 dark:bg-slate-900/95 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="py-3 px-4 text-xs font-bold uppercase tracking-wider text-slate-500 min-w-[240px]">
                    {mode === 'node' ? 'Location / Room' : 'Edge Device'}
                  </th>
                  {roles.map((r) => (
                    <th key={r.role_id} className="py-3 px-4 text-center min-w-[110px]">
                      <div className="text-xs font-extrabold uppercase tracking-wider text-slate-800 dark:text-slate-200">
                        {r.role_name}
                      </div>
                      <div className="text-[10px] font-mono text-slate-400 tabular-nums">
                        {r.user_count} user{r.user_count === 1 ? '' : 's'}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {mode === 'node' &&
                  filteredNodes.map((n) => (
                    <tr key={n.node_id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40">
                      <td className="py-3 px-4">
                        <div className="font-bold text-slate-900 dark:text-slate-100">{n.room_label}</div>
                        <div className="text-xs text-slate-500">
                          {n.building_name} {n.floor_level ? `· ${n.floor_level}` : ''} · {n.node_type}
                        </div>
                      </td>
                      {roles.map((r) => {
                        const allowed = n.role_ids.includes(r.role_id);
                        const key = `node:${n.node_id}:${r.role_id}`;
                        return (
                          <td key={r.role_id} className="py-3 px-4 text-center">
                            <input
                              type="checkbox"
                              disabled={busyKey === key}
                              checked={allowed}
                              onChange={() => handleToggle('node', n.node_id, r.role_id, allowed)}
                              aria-label={`${r.role_name} access to ${n.room_label}`}
                              className="w-4 h-4 rounded border-slate-300 dark:border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                            />
                          </td>
                        );
                      })}
                    </tr>
                  ))}

                {mode === 'device' &&
                  filteredDevices.map((d) => {
                    const hasOverrides = d.role_ids.length > 0;
                    return (
                      <tr key={d.device_id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40">
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-slate-900 dark:text-slate-100">{d.device_name}</span>
                            <StatusBadge variant={hasOverrides ? 'info' : 'neutral'}>
                              {hasOverrides ? 'Override' : 'Inherited'}
                            </StatusBadge>
                          </div>
                          <div className="text-xs font-mono text-slate-500">{d.device_id} · Node #{d.node_id}</div>
                        </td>
                        {roles.map((r) => {
                          const direct = d.role_ids.includes(r.role_id);
                          const inherited = !hasOverrides && d.inherited_role_ids.includes(r.role_id);
                          const key = `device:${d.device_id}:${r.role_id}`;
                          return (
                            <td key={r.role_id} className="py-3 px-4 text-center">
                              <div className="flex flex-col items-center gap-0.5">
                                <input
                                  type="checkbox"
                                  disabled={busyKey === key}
                                  checked={direct}
                                  onChange={() => handleToggle('device', d.device_id, r.role_id, direct)}
                                  aria-label={`${r.role_name} override on ${d.device_name}`}
                                  className="w-4 h-4 rounded border-slate-300 dark:border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                                />
                                {inherited && (
                                  <span className="text-[9px] font-semibold text-emerald-600 dark:text-emerald-400">
                                    via node
                                  </span>
                                )}
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
    </div>
  );
}
