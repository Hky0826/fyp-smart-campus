import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Edit3, Plus, Trash2, X } from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';

export function RolesPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [modal, setModal] = useState({ open: false, role: null });
  const [roleName, setRoleName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const { data: roles = [], isLoading } = useQuery({
    queryKey: ['roles'],
    queryFn: () => cloudApi.get('/api/iam/roles'),
  });

  const openModal = (role = null) => {
    setRoleName(role?.role_name || '');
    setDescription(role?.description || '');
    setModal({ open: true, role });
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (modal.role) {
        await cloudApi.put(`/api/iam/roles/${modal.role.role_id}`, { role_name: roleName.trim(), description });
        toast.success('Role updated.');
      } else {
        await cloudApi.post('/api/iam/roles', { role_name: roleName.trim(), description });
        toast.success('Role created.');
      }
      queryClient.invalidateQueries({ queryKey: ['roles'] });
      setModal({ open: false, role: null });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await cloudApi.delete(`/api/iam/roles/${deleteTarget.role_id}`);
      toast.success('Role deleted.');
      queryClient.invalidateQueries({ queryKey: ['roles'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setDeleteTarget(null);
    }
  };

  const columns = useMemo(
    () => [
      {
        id: 'id',
        header: 'ID',
        cell: ({ row }) => <span className="font-mono text-xs text-slate-500">#{row.original.role_id}</span>,
      },
      {
        id: 'name',
        header: 'Role Name',
        cell: ({ row }) => <StatusBadge variant="info">{row.original.role_name}</StatusBadge>,
      },
      {
        id: 'desc',
        header: 'Description',
        cell: ({ row }) => <span className="text-sm text-slate-600 dark:text-slate-400">{row.original.description || '—'}</span>,
      },
      {
        id: 'actions',
        header: 'Actions',
        meta: { align: 'right' },
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <button
              type="button"
              onClick={() => openModal(row.original)}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <Edit3 className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => setDeleteTarget(row.original)}
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
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">Access Roles</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Define campus identity roles used across door RBAC, navigation, and RAG document permissions.
          </p>
        </div>
        <button
          type="button"
          onClick={() => openModal(null)}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white"
        >
          <Plus className="w-4 h-4" /> Add Role
        </button>
      </div>

      <DataTable columns={columns} data={roles} loading={isLoading} total={roles.length} />

      {modal.open && (
        <div className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-900/50 p-4" onClick={() => setModal({ open: false, role: null })}>
          <div className="w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">{modal.role ? 'Edit Role' : 'Create Role'}</h3>
              <button type="button" onClick={() => setModal({ open: false, role: null })} className="p-1 text-slate-400"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={handleSave} className="space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Role Name *</label>
                <input
                  type="text"
                  required
                  value={roleName}
                  onChange={(e) => setRoleName(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Description</label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setModal({ open: false, role: null })} className="px-4 py-2 rounded-xl text-sm font-semibold bg-slate-100 dark:bg-slate-800">Cancel</button>
                <button type="submit" disabled={saving} className="px-4 py-2 rounded-xl text-sm font-bold bg-indigo-600 text-white">{saving ? 'Saving...' : 'Save'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete Role"
        message={`Delete role "${deleteTarget?.role_name}"? Roles assigned to active users cannot be deleted.`}
        confirmLabel="Delete"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
