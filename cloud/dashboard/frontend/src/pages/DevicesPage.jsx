import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, Cpu, Eye, Plus, Search, Trash2, X } from 'lucide-react';
import { cloudApi, formatRelativeTime } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';

export function DevicesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [provisionedSecret, setProvisionedSecret] = useState(null);

  const [deviceName, setDeviceName] = useState('');
  const [deviceType, setDeviceType] = useState('ENTRY_GATE');
  const [nodeId, setNodeId] = useState('');
  const [ipAddress, setIpAddress] = useState('');
  const [saving, setSaving] = useState(false);

  const { data: devices = [], isLoading } = useQuery({
    queryKey: ['devices'],
    queryFn: () => cloudApi.get('/api/infra/devices'),
  });

  const { data: nodes = [] } = useQuery({
    queryKey: ['ref-nodes'],
    queryFn: () => cloudApi.get('/api/refs/nodes'),
    staleTime: 60_000,
  });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return devices;
    return devices.filter(
      (d) =>
        d.device_name?.toLowerCase().includes(q) ||
        d.device_id?.toLowerCase().includes(q) ||
        d.ip_address?.toLowerCase().includes(q)
    );
  }, [devices, search]);

  const handleCreate = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const created = await cloudApi.post('/api/infra/devices', {
        device_name: deviceName.trim(),
        device_type: deviceType,
        node_id: parseInt(nodeId, 10),
        ip_address: ipAddress.trim() || null,
        is_active: true,
      });
      toast.success(`Provisioned ${created.device_name}.`);
      if (created.provisioned_secret) {
        setProvisionedSecret({ device_id: created.device_id, secret: created.provisioned_secret });
      }
      setCreateOpen(false);
      setDeviceName('');
      setIpAddress('');
      queryClient.invalidateQueries({ queryKey: ['devices'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handlePing = async (dev) => {
    try {
      await cloudApi.post(`/api/infra/devices/${dev.device_id}/heartbeat`, {});
      toast.success(`${dev.device_name} responded to heartbeat.`);
      queryClient.invalidateQueries({ queryKey: ['devices'] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      const res = await cloudApi.delete(`/api/infra/devices/${deleteTarget.device_id}`);
      toast.success(res.detail || 'Device removed.');
      queryClient.invalidateQueries({ queryKey: ['devices'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setDeleteTarget(null);
    }
  };

  const isOnline = (d) =>
    Boolean(d.is_active && d.last_heartbeat && Date.now() - new Date(d.last_heartbeat).getTime() < 5 * 60_000);

  const columns = useMemo(
    () => [
      {
        id: 'device',
        header: 'Device',
        cell: ({ row }) => {
          const d = row.original;
          return (
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 flex items-center justify-center shrink-0">
                <Cpu className="w-4 h-4" />
              </div>
              <div>
                <div className="font-bold text-slate-900 dark:text-slate-100">{d.device_name}</div>
                <div className="text-xs font-mono text-slate-500">{d.device_id}</div>
              </div>
            </div>
          );
        },
      },
      {
        id: 'type',
        header: 'Type',
        cell: ({ row }) => <StatusBadge variant="neutral">{row.original.device_type}</StatusBadge>,
      },
      {
        id: 'ip',
        header: 'IP Address',
        cell: ({ row }) => <span className="text-xs font-mono text-slate-500">{row.original.ip_address || '—'}</span>,
      },
      {
        id: 'health',
        header: 'Health',
        cell: ({ row }) => {
          const online = isOnline(row.original);
          return (
            <StatusBadge variant={online ? 'success' : 'warning'} dot>
              {online ? 'Online' : 'Offline'}
            </StatusBadge>
          );
        },
      },
      {
        id: 'seen',
        header: 'Last Heartbeat',
        cell: ({ row }) => (
          <span className="text-xs text-slate-500 tabular-nums">
            {formatRelativeTime(row.original.last_heartbeat)}
          </span>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        meta: { align: 'right', stopClick: true },
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <button
              type="button"
              onClick={() => navigate(`/dashboard/devices/${row.original.device_id}`)}
              title="Open Device Workspace"
              className="p-1.5 rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-500/15"
            >
              <Eye className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => handlePing(row.original)}
              title="Ping Device"
              className="p-1.5 rounded-lg text-slate-500 hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-500/15"
            >
              <Activity className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => setDeleteTarget(row.original)}
              title="Delete Device"
              className="p-1.5 rounded-lg text-slate-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-500/15"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ),
      },
    ],
    []
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">Edge Devices</h1>
        </div>
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white"
        >
          <Plus className="w-4 h-4" /> Add Device
        </button>
      </div>

      {provisionedSecret && (
        <div className="p-4 rounded-2xl bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <div className="text-sm font-bold text-amber-900 dark:text-amber-300">
              One-time Device Secret for {provisionedSecret.device_id}
            </div>
            <div className="text-xs font-mono text-amber-800 dark:text-amber-200 mt-1 break-all">
              {provisionedSecret.secret}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setProvisionedSecret(null)}
            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-white dark:bg-slate-900 border border-amber-300 text-amber-900 dark:text-amber-200 shrink-0"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative max-w-xs">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter devices by name, ID, IP..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
      </div>

      <DataTable
        columns={columns}
        data={filtered}
        loading={isLoading}
        total={filtered.length}
        onRowClick={(d) => navigate(`/dashboard/devices/${d.device_id}`)}
      />

      {createOpen && (
        <div className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-900/50 p-4" onClick={() => setCreateOpen(false)}>
          <div className="w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">Provision Edge Device</h3>
              <button type="button" onClick={() => setCreateOpen(false)} className="p-1 text-slate-400"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Device Name *</label>
                <input type="text" required value={deviceName} onChange={(e) => setDeviceName(e.target.value)} className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Device Type *</label>
                <select value={deviceType} onChange={(e) => setDeviceType(e.target.value)} className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm">
                  {['ENTRY_GATE', 'KIOSK', 'CLASSROOM', 'OFFICE', 'OTHER'].map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Campus Location Node *</label>
                <select required value={nodeId} onChange={(e) => setNodeId(e.target.value)} className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm">
                  <option value="">Select node...</option>
                  {nodes.map((n) => (
                    <option key={n.node_id} value={n.node_id}>{n.room_label || `Node #${n.node_id}`}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">IP Address (Optional)</label>
                <input type="text" value={ipAddress} onChange={(e) => setIpAddress(e.target.value)} placeholder="192.168.1.50" className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm" />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setCreateOpen(false)} className="px-4 py-2 rounded-xl text-sm font-semibold bg-slate-100 dark:bg-slate-800">Cancel</button>
                <button type="submit" disabled={saving} className="px-4 py-2 rounded-xl text-sm font-bold bg-indigo-600 text-white">{saving ? 'Saving...' : 'Provision'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete Device"
        message={`Remove device "${deleteTarget?.device_name}"? If audit logs reference it, it will be deactivated instead.`}
        confirmLabel="Remove"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
