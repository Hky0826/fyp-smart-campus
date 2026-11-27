import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, ArrowLeft, Cpu, KeyRound, Layers, Plus, QrCode, Search, Shield, UserPlus, X } from 'lucide-react';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { StatusBadge } from '../components/ui/StatusBadge';
import { DevicePairingModal } from '../components/DevicePairingModal';
import { AccessControlSettingsCard } from '../components/AccessControlSettingsCard';

export function DeviceDetailPage() {
  const { deviceId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [rotatedSecret, setRotatedSecret] = useState('');
  const [pairingDetails, setPairingDetails] = useState(null);
  const [userSearch, setUserSearch] = useState('');
  const [showUserPicker, setShowUserPicker] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['device-detail', deviceId],
    queryFn: () => cloudApi.get(`/api/infra/devices/${deviceId}/detail`),
  });

  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: () => cloudApi.get('/api/iam/roles'),
    staleTime: 60_000,
  });

  const { data: groups = [] } = useQuery({
    queryKey: ['access-groups'],
    queryFn: () => cloudApi.get('/api/iam/access-groups'),
    staleTime: 60_000,
  });

  const { data: userSearchRes } = useQuery({
    queryKey: ['device-user-picker', userSearch],
    queryFn: () =>
      cloudApi.get(`/api/iam/users/paginated?page=1&page_size=12&q=${encodeURIComponent(userSearch.trim())}`),
    enabled: showUserPicker,
    staleTime: 15_000,
  });

  const dev = data?.device;

  const userCandidates = useMemo(() => {
    const existing = new Set(dev?.allowed_user_ids || []);
    return (userSearchRes?.items || []).filter((u) => !existing.has(u.user_id));
  }, [userSearchRes, dev?.allowed_user_ids]);

  if (isLoading) {
    return (
      <div className="py-24 flex flex-col items-center text-slate-500">
        <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mb-3" />
        <span className="text-sm">Loading device telemetry...</span>
      </div>
    );
  }

  if (!dev) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-10 text-center">
        <p className="text-base font-bold">Device not found</p>
        <button type="button" onClick={() => navigate('/dashboard/devices')} className="mt-4 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 text-white">
          Back to Devices
        </button>
      </div>
    );
  }

  const handleToggleRole = async (roleId, currentlyAllowed) => {
    try {
      await cloudApi.put('/api/infra/rbac-matrix/toggle', {
        target_type: 'device',
        target_id: dev.device_id,
        role_id: roleId,
        allowed: !currentlyAllowed,
      });
      toast.success('Updated device role rule.');
      queryClient.invalidateQueries({ queryKey: ['device-detail', deviceId] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleToggleGroup = async (groupId, currentlyAssigned) => {
    try {
      await cloudApi.put('/api/infra/rbac-matrix/toggle-group', {
        target_type: 'device',
        target_id: dev.device_id,
        group_id: groupId,
        allowed: !currentlyAssigned,
      });
      toast.success('Updated device access group.');
      queryClient.invalidateQueries({ queryKey: ['device-detail', deviceId] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleToggleUser = async (userId, allowed) => {
    try {
      await cloudApi.put('/api/infra/rbac-matrix/toggle-user', {
        target_type: 'device',
        target_id: dev.device_id,
        user_id: userId,
        allowed,
      });
      toast.success(allowed ? 'Granted individual user access.' : 'Removed individual user access.');
      queryClient.invalidateQueries({ queryKey: ['device-detail', deviceId] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleRotateSecret = async () => {
    try {
      const res = await cloudApi.post(`/api/infra/devices/${dev.device_id}/rotate-credential`, {});
      setRotatedSecret(res.device_secret || res.provisioned_secret || '');
      toast.success(
        res.pushed_over_ws
          ? 'Device secret rotated and pushed live over WebSocket.'
          : 'Device secret rotated. Use Pair / QR or update the device manually.'
      );
      queryClient.invalidateQueries({ queryKey: ['device-detail', deviceId] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleIssuePairingCode = async () => {
    try {
      const res = await cloudApi.post(`/api/infra/devices/${dev.device_id}/pairing-code`, {});
      setPairingDetails({
        device_id: res.device_id,
        device_name: res.device_name,
        secret: '',
        pairing_code: res.pairing_code || '',
        pairing_expires_at: res.pairing_expires_at || '',
        pairing_qr_payload: res.pairing_qr_payload || '',
        pairing_qr_svg_data_uri: res.pairing_qr_svg_data_uri || '',
        paired: false,
      });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handlePing = async () => {
    try {
      await cloudApi.post(`/api/infra/devices/${dev.device_id}/heartbeat`, {});
      toast.success('Heartbeat verified.');
      queryClient.invalidateQueries({ queryKey: ['device-detail', deviceId] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const metrics = data?.metrics_24h || { attempts: 0, failures: 0, success_rate: 100 };
  const logs = data?.recent_logs || [];
  const assignedGroupIds = dev.assigned_group_ids || [];
  const inheritedGroupIds = dev.inherited_node_group_ids || [];
  const directUsers = dev.allowed_users || [];
  const inheritedUsers = dev.inherited_node_users || [];

  return (
    <div className="space-y-6">
      <button
        type="button"
        onClick={() => navigate('/dashboard/devices')}
        className="inline-flex items-center gap-1.5 text-xs font-bold text-slate-500 hover:text-indigo-600"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Back to Edge Devices
      </button>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-indigo-600 text-white flex items-center justify-center shrink-0">
            <Cpu className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-xl font-extrabold text-slate-900 dark:text-slate-100">{dev.device_name}</h1>
              <StatusBadge variant={dev.is_online ? 'success' : 'warning'} dot>
                {dev.is_online ? 'Online' : 'Offline'}
              </StatusBadge>
              <StatusBadge variant="neutral">{dev.device_type}</StatusBadge>
            </div>
            <p className="text-xs font-mono text-slate-500 mt-1">
              {dev.device_id} · {dev.building_name || 'Campus'} {dev.floor_level ? `(${dev.floor_level})` : ''} · {dev.room_label || `Node #${dev.node_id}`}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleIssuePairingCode}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-amber-500 hover:bg-amber-600 text-slate-950"
          >
            <QrCode className="w-3.5 h-3.5" /> Pair / QR
          </button>
          <button
            type="button"
            onClick={handlePing}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white"
          >
            <Activity className="w-3.5 h-3.5" /> Ping Health
          </button>
          <button
            type="button"
            onClick={handleRotateSecret}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200"
          >
            <KeyRound className="w-3.5 h-3.5" /> Rotate Secret
          </button>
        </div>
      </div>

      <DevicePairingModal
        details={pairingDetails}
        onClose={() => setPairingDetails(null)}
        onPaired={() => queryClient.invalidateQueries({ queryKey: ['device-detail', deviceId] })}
      />

      {rotatedSecret && (
        <div className="p-4 rounded-2xl bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/30">
          <div className="text-xs font-bold uppercase text-amber-800 dark:text-amber-300">New Rotated Device Secret (copy now)</div>
          <div className="text-xs font-mono mt-1 break-all text-amber-900 dark:text-amber-200">{rotatedSecret}</div>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="p-5 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
          <div className="text-xs font-bold uppercase text-slate-500">24h Attempts</div>
          <div className="text-2xl font-extrabold tabular-nums mt-1">{metrics.attempts}</div>
        </div>
        <div className="p-5 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
          <div className="text-xs font-bold uppercase text-slate-500">Success Rate</div>
          <div className="text-2xl font-extrabold tabular-nums mt-1 text-emerald-600 dark:text-emerald-400">{metrics.success_rate}%</div>
        </div>
        <div className="p-5 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
          <div className="text-xs font-bold uppercase text-slate-500">Last Heartbeat</div>
          <div className="text-sm font-bold mt-2">{formatDateTime(dev.last_heartbeat)}</div>
        </div>
      </div>

      <AccessControlSettingsCard deviceId={dev.device_id} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Per-Device Access Policy (Groups + Roles + Individual Users) */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
              <h2 className="text-base font-bold">Authorized Access</h2>
            </div>
            <StatusBadge variant={dev.uses_device_override ? 'info' : 'neutral'}>
              {dev.uses_device_override ? 'Override' : 'Inherited'}
            </StatusBadge>
          </div>
          <p className="text-xs text-slate-500">
            {dev.uses_device_override
              ? 'Using device-specific access rules (overrides node policy).'
              : 'No device-specific rules set — inheriting full policy from assigned node.'}
          </p>

          {/* Access Groups */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1">
                <Layers className="w-3 h-3" /> Access Groups
              </span>
              <button
                type="button"
                onClick={() => navigate('/dashboard/roles?tab=groups')}
                className="text-[11px] font-semibold text-indigo-600 hover:underline"
              >
                Manage
              </button>
            </div>
            {groups.length === 0 ? (
              <p className="text-xs text-slate-400">No access groups created yet.</p>
            ) : (
              groups.map((g) => {
                const assigned = assignedGroupIds.includes(g.group_id);
                const inherited = !dev.uses_device_override && inheritedGroupIds.includes(g.group_id);
                return (
                  <label
                    key={g.group_id}
                    className="flex items-center justify-between p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  >
                    <div>
                      <div className="text-sm font-bold text-slate-900 dark:text-slate-100">{g.group_name}</div>
                      <div className="text-[11px] text-slate-500">
                        {(g.roles || []).length} role{(g.roles || []).length === 1 ? '' : 's'} · {(g.users || []).length} user{(g.users || []).length === 1 ? '' : 's'}
                        {inherited && ' · Inherited from node'}
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={assigned}
                      onChange={() => handleToggleGroup(g.group_id, assigned)}
                      className="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                    />
                  </label>
                );
              })
            )}
          </div>

          {/* Individual Roles */}
          <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 block">
              Individual Roles
            </span>
            {roles.map((r) => {
              const direct = (dev.allowed_role_ids || []).includes(r.role_id);
              const viaGroup = !direct && (dev.effective_role_ids || []).includes(r.role_id);
              const inherited = !dev.uses_device_override && (dev.inherited_node_role_ids || []).includes(r.role_id);
              return (
                <label
                  key={r.role_id}
                  className="flex items-center justify-between p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                >
                  <div>
                    <div className="text-sm font-bold text-slate-900 dark:text-slate-100">{r.role_name}</div>
                    {viaGroup && <div className="text-[11px] text-indigo-600 dark:text-indigo-400">Granted via group</div>}
                    {!viaGroup && inherited && <div className="text-[11px] text-emerald-600 dark:text-emerald-400">Inherited from node</div>}
                  </div>
                  <input
                    type="checkbox"
                    checked={direct}
                    onChange={() => handleToggleRole(r.role_id, direct)}
                    className="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </label>
              );
            })}
          </div>

          {/* Individual Users */}
          <div className="space-y-2.5 pt-2 border-t border-slate-100 dark:border-slate-800">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                Individual Users
              </span>
              <button
                type="button"
                onClick={() => {
                  setUserSearch('');
                  setShowUserPicker((prev) => !prev);
                }}
                className="inline-flex items-center gap-1 text-[11px] font-bold text-indigo-600 hover:underline"
              >
                <UserPlus className="w-3 h-3" /> {showUserPicker ? 'Close' : 'Add User'}
              </button>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {directUsers.map((u) => (
                <span
                  key={u.user_id}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-indigo-50 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300"
                >
                  {u.full_name}
                  <button
                    type="button"
                    onClick={() => handleToggleUser(u.user_id, false)}
                    className="hover:text-red-600"
                    aria-label={`Remove ${u.full_name}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}

              {!dev.uses_device_override &&
                inheritedUsers.map((u) => (
                  <span
                    key={`inh-${u.user_id}`}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  >
                    {u.full_name} <span className="text-[9px] opacity-75">(node)</span>
                  </span>
                ))}

              {directUsers.length === 0 && (dev.uses_device_override || inheritedUsers.length === 0) && (
                <span className="text-xs text-slate-400">No individual users assigned.</span>
              )}
            </div>

            {showUserPicker && (
              <div className="space-y-2 pt-1">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={userSearch}
                    onChange={(e) => setUserSearch(e.target.value)}
                    placeholder="Search user name or email..."
                    className="w-full pl-8 pr-3 py-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-xs"
                  />
                </div>
                <div className="max-h-36 overflow-y-auto rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
                  {userCandidates.length === 0 ? (
                    <div className="p-2.5 text-xs text-slate-400 text-center">No matching users.</div>
                  ) : (
                    userCandidates.map((u) => (
                      <button
                        key={u.user_id}
                        type="button"
                        onClick={() => handleToggleUser(u.user_id, true)}
                        className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-slate-50 dark:hover:bg-slate-800/50"
                      >
                        <div>
                          <div className="text-xs font-bold text-slate-900 dark:text-slate-100">{u.full_name}</div>
                          <div className="text-[10px] font-mono text-slate-500">{u.email}</div>
                        </div>
                        <Plus className="w-3.5 h-3.5 text-indigo-600" />
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Recent Door Events */}
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-3">
          <h2 className="text-base font-bold">Recent Door Events</h2>
          {logs.length === 0 ? (
            <p className="text-sm text-slate-500 py-8 text-center">No events recorded on this device.</p>
          ) : (
            logs.map((l) => (
              <div key={l.log_id} className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
                <div>
                  <button
                    type="button"
                    onClick={() => l.user_id && navigate(`/dashboard/users/${l.user_id}`)}
                    className="text-sm font-bold text-slate-900 dark:text-slate-100 hover:text-indigo-600 text-left"
                  >
                    {l.full_name} {l.email && <span className="font-mono text-xs text-slate-500">({l.email})</span>}
                  </button>
                  <div className="text-xs text-slate-500 mt-0.5">
                    {formatDateTime(l.timestamp)} {l.reason && `· ${l.reason}`}
                  </div>
                </div>
                <StatusBadge variant={l.auth_status === 'SUCCESS' ? 'success' : 'danger'}>
                  {l.auth_status}
                </StatusBadge>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
