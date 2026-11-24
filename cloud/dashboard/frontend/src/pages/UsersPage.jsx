import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Download,
  Edit3,
  Eye,
  Plus,
  ScanFace,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { CsvImportWizard } from '../components/users/CsvImportWizard';
import { UserFormModal } from '../components/users/UserFormModal';
import { FaceEnrollModal } from '../components/users/FaceEnrollModal';

export function UsersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10));
  const pageSize = [10, 25, 50, 100].includes(parseInt(searchParams.get('page_size') || '25', 10))
    ? parseInt(searchParams.get('page_size') || '25', 10)
    : 25;
  const qParam = searchParams.get('q') || '';
  const roleId = searchParams.get('role_id') || 'ALL';
  const status = searchParams.get('status') || 'ALL';
  const faceStatus = searchParams.get('face_status') || 'ALL';
  const facultyId = searchParams.get('faculty_id') || 'ALL';
  const departmentId = searchParams.get('department_id') || 'ALL';
  const sortBy = searchParams.get('sort_by') || 'user_id';
  const sortOrder = searchParams.get('sort_order') || 'desc';

  const [searchInput, setSearchInput] = useState(qParam);
  const [density, setDensity] = useState(() => localStorage.getItem('dashboard_density') || 'comfortable');
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkRoleId, setBulkRoleId] = useState('');
  const [bulkBusy, setBulkBusy] = useState(false);

  const [importOpen, setImportOpen] = useState(searchParams.get('import') === '1');
  const [formState, setFormState] = useState({ open: false, user: null });
  const [faceUser, setFaceUser] = useState(null);
  const [confirmState, setConfirmState] = useState({ open: false });

  useEffect(() => {
    setSearchInput(qParam);
  }, [qParam]);

  useEffect(() => {
    if (searchParams.get('import') === '1') {
      setImportOpen(true);
    }
  }, [searchParams]);

  const updateParams = (patch, resetPage = true) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([k, v]) => {
      if (v === undefined || v === null || v === '' || v === 'ALL') next.delete(k);
      else next.set(k, String(v));
    });
    if (resetPage) next.set('page', '1');
    setSearchParams(next, { replace: true });
    setSelectedIds([]);
  };

  useEffect(() => {
    const t = setTimeout(() => {
      if (searchInput.trim() !== qParam) {
        updateParams({ q: searchInput.trim() });
      }
    }, 250);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    localStorage.setItem('dashboard_density', density);
  }, [density]);

  const { data: refs } = useQuery({
    queryKey: ['iam-refs'],
    queryFn: async () => {
      const [roles, faculties, programmes, departments, nodes] = await Promise.all([
        cloudApi.get('/api/iam/roles'),
        cloudApi.get('/api/refs/faculties'),
        cloudApi.get('/api/refs/programmes'),
        cloudApi.get('/api/refs/departments'),
        cloudApi.get('/api/refs/nodes'),
      ]);
      return { roles, faculties, programmes, departments, nodes };
    },
    staleTime: 60_000,
  });

  const { data, isLoading } = useQuery({
    queryKey: ['users-paginated', { page, pageSize, qParam, roleId, status, faceStatus, facultyId, departmentId, sortBy, sortOrder }],
    queryFn: () =>
      cloudApi.get('/api/iam/users/paginated', {
        page,
        page_size: pageSize,
        q: qParam,
        role_id: roleId,
        status,
        face_status: faceStatus,
        faculty_id: facultyId,
        department_id: departmentId,
        sort_by: sortBy,
        sort_order: sortOrder,
      }),
    placeholderData: (prev) => prev,
  });

  const items = data?.items ?? [];
  const summary = data?.summary ?? { total_users: 0, active_users: 0, inactive_users: 0, face_enrolled_users: 0 };
  const facePct = summary.total_users > 0 ? Math.round((summary.face_enrolled_users / summary.total_users) * 100) : 0;

  const refreshUsers = () => {
    queryClient.invalidateQueries({ queryKey: ['users-paginated'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
  };

  const hasFilters =
    Boolean(qParam) ||
    roleId !== 'ALL' ||
    status !== 'ALL' ||
    faceStatus !== 'ALL' ||
    facultyId !== 'ALL' ||
    departmentId !== 'ALL';

  const resetFilters = () => {
    setSearchInput('');
    setSearchParams(new URLSearchParams({ page: '1', page_size: String(pageSize) }), { replace: true });
    setSelectedIds([]);
  };

  const pageIds = items.map((u) => u.user_id);
  const allSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.includes(id));

  const toggleAll = () => {
    if (allSelected) setSelectedIds((prev) => prev.filter((id) => !pageIds.includes(id)));
    else setSelectedIds((prev) => Array.from(new Set([...prev, ...pageIds])));
  };

  const toggleOne = (id) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const handleToggleStatus = async (user) => {
    try {
      await cloudApi.post(`/api/iam/users/${user.user_id}/toggle-active`, {});
      toast.success(`${user.full_name} is now ${user.is_active ? 'deactivated' : 'active'}.`);
      refreshUsers();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleBulkStatus = async (isActive) => {
    setBulkBusy(true);
    try {
      const res = await cloudApi.post('/api/iam/users/bulk-status', { user_ids: selectedIds, is_active: isActive });
      toast.success(res.detail);
      setSelectedIds([]);
      refreshUsers();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBulkBusy(false);
    }
  };

  const handleBulkRole = async () => {
    if (!bulkRoleId) return;
    setBulkBusy(true);
    try {
      const res = await cloudApi.post('/api/iam/users/bulk-role', {
        user_ids: selectedIds,
        role_id: parseInt(bulkRoleId, 10),
        mode: 'add',
      });
      toast.success(res.detail);
      setBulkRoleId('');
      setSelectedIds([]);
      refreshUsers();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBulkBusy(false);
    }
  };

  const handleDeleteUser = (user) => {
    setConfirmState({
      open: true,
      title: 'Delete User Account',
      message: `Permanently delete "${user.full_name}" (${user.email}) and their biometric templates?`,
      confirmLabel: 'Delete User',
      onConfirm: async () => {
        setConfirmState({ open: false });
        try {
          await cloudApi.delete(`/api/iam/users/${user.user_id}`);
          toast.success(`Deleted ${user.full_name}.`);
          refreshUsers();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  const handleBulkDelete = () => {
    const count = selectedIds.length;
    setConfirmState({
      open: true,
      title: `Delete ${count} Selected User${count > 1 ? 's' : ''}`,
      message: `This will permanently remove ${count} user accounts, role assignments, and stored facial embeddings.`,
      impactNote: count >= 5 ? 'High-impact bulk operation: please confirm carefully.' : '',
      requireText: count >= 5 ? 'DELETE' : '',
      confirmLabel: `Delete ${count} User${count > 1 ? 's' : ''}`,
      onConfirm: async () => {
        setConfirmState({ open: false });
        setBulkBusy(true);
        try {
          const res = await cloudApi.post('/api/iam/users/bulk-delete', { user_ids: selectedIds });
          toast.success(res.detail);
          setSelectedIds([]);
          refreshUsers();
        } catch (err) {
          toast.error(err.message);
        } finally {
          setBulkBusy(false);
        }
      },
    });
  };

  const exportCsv = () => {
    const rows = selectedIds.length > 0 ? items.filter((u) => selectedIds.includes(u.user_id)) : items;
    if (rows.length === 0) return toast.error('No rows to export.');
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const header = ['User ID', 'Full Name', 'Email', 'Roles', 'Status', 'Face Enrolled', 'Profile ID'];
    const lines = rows.map((u) => [
      u.user_id,
      u.full_name,
      u.email,
      (u.roles || []).map((r) => r.role_name).join('; '),
      u.is_active ? 'Active' : 'Deactivated',
      u.face_enrolled ? 'Yes' : 'No',
      u.student?.student_id || u.lecturer?.lecturer_id || u.staff?.staff_id || u.visitor?.id_number || u.admin?.admin_id || '',
    ].map(esc).join(','));
    const blob = new Blob([[header.map(esc).join(','), ...lines].join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `users-page-${page}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${rows.length} user(s).`);
  };

  const columns = useMemo(
    () => [
      {
        id: 'select',
        meta: { stopClick: true },
        header: () => (
          <input
            type="checkbox"
            checked={allSelected}
            onChange={toggleAll}
            aria-label="Select all on page"
            className="rounded border-slate-300 dark:border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            checked={selectedIds.includes(row.original.user_id)}
            onChange={() => toggleOne(row.original.user_id)}
            aria-label={`Select ${row.original.full_name}`}
            className="rounded border-slate-300 dark:border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
          />
        ),
      },
      {
        id: 'profile',
        header: 'User',
        meta: { sortKey: 'name' },
        cell: ({ row }) => {
          const u = row.original;
          const initials = ((u.given_name?.[0] || '') + (u.family_name?.[0] || '')).toUpperCase() || 'U';
          return (
            <div className="flex items-center gap-3 min-w-[220px]">
              <div className="w-9 h-9 rounded-full bg-indigo-50 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 font-bold text-xs flex items-center justify-center shrink-0 border border-indigo-100 dark:border-indigo-500/20">
                {initials}
              </div>
              <div className="min-w-0">
                <div className="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                  <span className="truncate">{u.full_name}</span>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 tabular-nums">
                    #{u.user_id}
                  </span>
                </div>
                <div className="text-xs font-mono text-slate-500 truncate">{u.email}</div>
              </div>
            </div>
          );
        },
      },
      {
        id: 'roles',
        header: 'Roles & Identity',
        cell: ({ row }) => {
          const u = row.original;
          const idTag =
            u.student?.student_id ||
            u.lecturer?.lecturer_id ||
            u.staff?.staff_id ||
            u.visitor?.id_number ||
            u.admin?.admin_id;
          return (
            <div className="space-y-1">
              <div className="flex flex-wrap gap-1">
                {(u.roles || []).map((r) => (
                  <StatusBadge key={r.role_id} variant="info">
                    {r.role_name}
                  </StatusBadge>
                ))}
              </div>
              {idTag && <div className="text-xs font-mono text-slate-500">{idTag}</div>}
            </div>
          );
        },
      },
      {
        id: 'face',
        header: 'Face ID',
        cell: ({ row }) => {
          const u = row.original;
          return u.face_enrolled ? (
            <StatusBadge variant="success" dot>
              {u.enrolled_poses_count ? `${u.enrolled_poses_count} pose${u.enrolled_poses_count > 1 ? 's' : ''}` : 'Enrolled'}
            </StatusBadge>
          ) : (
            <StatusBadge variant="neutral">Not enrolled</StatusBadge>
          );
        },
      },
      {
        id: 'status',
        header: 'Status',
        meta: { sortKey: 'is_active', stopClick: true },
        cell: ({ row }) => {
          const u = row.original;
          return (
            <button type="button" onClick={() => handleToggleStatus(u)} title="Click to toggle status">
              <StatusBadge variant={u.is_active ? 'success' : 'danger'} dot>
                {u.is_active ? 'Active' : 'Deactivated'}
              </StatusBadge>
            </button>
          );
        },
      },
      {
        id: 'actions',
        header: 'Actions',
        meta: { align: 'right', stopClick: true },
        cell: ({ row }) => {
          const u = row.original;
          return (
            <div className="flex items-center justify-end gap-1">
              <button
                type="button"
                onClick={() => navigate(`/dashboard/users/${u.user_id}`)}
                title="Open 360° User Workspace"
                className="p-1.5 rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-500/15"
              >
                <Eye className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={() => setFaceUser(u)}
                title="Enroll Face ID"
                className="p-1.5 rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-500/15"
              >
                <ScanFace className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={() => setFormState({ open: true, user: u })}
                title="Edit User"
                className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <Edit3 className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={() => handleDeleteUser(u)}
                title="Delete User"
                className="p-1.5 rounded-lg text-slate-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-500/15"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          );
        },
      },
    ],
    [allSelected, selectedIds, items]
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
            Users Directory
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Server-paginated identity directory. Click any row to open their full 360° profile and effective door access.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={exportCsv}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 hover:border-slate-300"
          >
            <Download className="w-3.5 h-3.5" />
            <span>{selectedIds.length > 0 ? `Export (${selectedIds.length})` : 'Export CSV'}</span>
          </button>
          <button
            type="button"
            onClick={() => setImportOpen(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold border border-indigo-200 dark:border-indigo-500/30 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-500/20"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>Import CSV</span>
          </button>
          <button
            type="button"
            onClick={() => setFormState({ open: true, user: null })}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white shadow-xs"
          >
            <Plus className="w-4 h-4" />
            <span>Register User</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <button
          type="button"
          onClick={resetFilters}
          className="text-left p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 hover:border-indigo-400 transition-colors"
        >
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Total Users</div>
          <div className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tabular-nums mt-1">
            {summary.total_users.toLocaleString()}
          </div>
        </button>
        <button
          type="button"
          onClick={() => updateParams({ status: status === 'ACTIVE' ? 'ALL' : 'ACTIVE' })}
          className={`text-left p-4 rounded-2xl border transition-colors ${
            status === 'ACTIVE'
              ? 'bg-emerald-50/70 dark:bg-emerald-500/10 border-emerald-400'
              : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-slate-300'
          }`}
        >
          <div className="text-[11px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">Active</div>
          <div className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tabular-nums mt-1">
            {summary.active_users.toLocaleString()}
          </div>
        </button>
        <button
          type="button"
          onClick={() => updateParams({ status: status === 'DEACTIVATED' ? 'ALL' : 'DEACTIVATED' })}
          className={`text-left p-4 rounded-2xl border transition-colors ${
            status === 'DEACTIVATED'
              ? 'bg-red-50/70 dark:bg-red-500/10 border-red-400'
              : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-slate-300'
          }`}
        >
          <div className="text-[11px] font-bold uppercase tracking-wider text-red-700 dark:text-red-400">Deactivated</div>
          <div className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tabular-nums mt-1">
            {summary.inactive_users.toLocaleString()}
          </div>
        </button>
        <button
          type="button"
          onClick={() => updateParams({ face_status: faceStatus === 'ENROLLED' ? 'ALL' : 'ENROLLED' })}
          className={`text-left p-4 rounded-2xl border transition-colors ${
            faceStatus === 'ENROLLED'
              ? 'bg-indigo-50/70 dark:bg-indigo-500/10 border-indigo-400'
              : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-slate-300'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-700 dark:text-indigo-400">Face ID Enrolled</span>
            <span className="text-xs font-mono font-bold text-indigo-600 dark:text-indigo-400 tabular-nums">{facePct}%</span>
          </div>
          <div className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tabular-nums mt-1">
            {summary.face_enrolled_users.toLocaleString()}
          </div>
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="flex flex-wrap items-center gap-2 flex-1 min-w-0">
          <div className="relative flex-1 min-w-[200px] max-w-xs">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search name, email, student/staff ID..."
              className="w-full pl-9 pr-8 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500"
            />
            {searchInput && (
              <button
                type="button"
                onClick={() => setSearchInput('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <select
            value={roleId}
            onChange={(e) => updateParams({ role_id: e.target.value })}
            className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300"
          >
            <option value="ALL">All Roles</option>
            {(refs?.roles || []).map((r) => (
              <option key={r.role_id} value={r.role_id}>{r.role_name}</option>
            ))}
          </select>

          <select
            value={status}
            onChange={(e) => updateParams({ status: e.target.value })}
            className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300"
          >
            <option value="ALL">All Status</option>
            <option value="ACTIVE">Active</option>
            <option value="DEACTIVATED">Deactivated</option>
          </select>

          <select
            value={faceStatus}
            onChange={(e) => updateParams({ face_status: e.target.value })}
            className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300"
          >
            <option value="ALL">All Face ID</option>
            <option value="ENROLLED">Enrolled</option>
            <option value="NOT_ENROLLED">Not Enrolled</option>
          </select>

          {(refs?.faculties?.length ?? 0) > 0 && (
            <select
              value={facultyId}
              onChange={(e) => updateParams({ faculty_id: e.target.value })}
              className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300 max-w-[170px]"
            >
              <option value="ALL">All Faculties</option>
              {refs.faculties.map((f) => (
                <option key={f.faculty_id} value={f.faculty_id}>{f.faculty_name}</option>
              ))}
            </select>
          )}

          {(refs?.departments?.length ?? 0) > 0 && (
            <select
              value={departmentId}
              onChange={(e) => updateParams({ department_id: e.target.value })}
              className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300 max-w-[170px]"
            >
              <option value="ALL">All Departments</option>
              {refs.departments.map((d) => (
                <option key={d.department_id} value={d.department_id}>{d.department_name}</option>
              ))}
            </select>
          )}

          {hasFilters && (
            <button
              type="button"
              onClick={resetFilters}
              className="px-2.5 py-1.5 rounded-xl text-xs font-bold text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-500/10"
            >
              Reset
            </button>
          )}
        </div>

        <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 p-0.5 shrink-0">
          {['comfortable', 'compact'].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDensity(d)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold capitalize transition-colors ${
                density === d
                  ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 shadow-xs'
                  : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      {selectedIds.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 rounded-2xl bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200 dark:border-indigo-500/40">
          <div className="flex items-center gap-2 text-sm font-bold text-indigo-900 dark:text-indigo-200 tabular-nums">
            <span className="px-2 py-0.5 rounded-lg bg-indigo-600 text-white text-xs">{selectedIds.length}</span>
            <span>selected</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={bulkBusy}
              onClick={() => handleBulkStatus(true)}
              className="px-3 py-1.5 rounded-xl text-xs font-bold bg-white dark:bg-slate-900 border border-emerald-300 dark:border-emerald-500/30 text-emerald-700 dark:text-emerald-400"
            >
              Activate
            </button>
            <button
              type="button"
              disabled={bulkBusy}
              onClick={() => handleBulkStatus(false)}
              className="px-3 py-1.5 rounded-xl text-xs font-bold bg-white dark:bg-slate-900 border border-amber-300 dark:border-amber-500/30 text-amber-700 dark:text-amber-400"
            >
              Deactivate
            </button>
            <div className="flex items-center gap-1">
              <select
                value={bulkRoleId}
                onChange={(e) => setBulkRoleId(e.target.value)}
                className="rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs text-slate-800 dark:text-slate-200"
              >
                <option value="">Add role...</option>
                {(refs?.roles || []).map((r) => (
                  <option key={r.role_id} value={r.role_id}>{r.role_name}</option>
                ))}
              </select>
              <button
                type="button"
                disabled={!bulkRoleId || bulkBusy}
                onClick={handleBulkRole}
                className="px-3 py-1.5 rounded-xl text-xs font-bold bg-indigo-600 text-white disabled:opacity-40"
              >
                Apply
              </button>
            </div>
            <button
              type="button"
              disabled={bulkBusy}
              onClick={handleBulkDelete}
              className="px-3 py-1.5 rounded-xl text-xs font-bold bg-red-600 hover:bg-red-700 text-white"
            >
              Delete
            </button>
            <button
              type="button"
              onClick={() => setSelectedIds([])}
              className="px-2 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      <DataTable
        columns={columns}
        data={items}
        loading={isLoading}
        total={data?.total ?? 0}
        page={data?.page ?? page}
        pageSize={data?.page_size ?? pageSize}
        totalPages={data?.total_pages ?? 1}
        onPageChange={(p) => updateParams({ page: p }, false)}
        onPageSizeChange={(sz) => updateParams({ page_size: sz }, true)}
        sortBy={sortBy}
        sortOrder={sortOrder}
        onSortChange={(k, o) => updateParams({ sort_by: k, sort_order: o }, false)}
        density={density}
        onRowClick={(u) => navigate(`/dashboard/users/${u.user_id}`)}
        emptyTitle={hasFilters ? 'No users match your filters' : 'No users registered yet'}
        emptyDescription={
          hasFilters
            ? 'Clear or adjust your search query and facet filters.'
            : 'Register a user manually or use Bulk CSV Import to onboard hundreds of users at once.'
        }
        emptyAction={
          hasFilters ? (
            <button
              type="button"
              onClick={resetFilters}
              className="px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 text-white"
            >
              Reset Filters
            </button>
          ) : null
        }
      />

      <CsvImportWizard
        open={importOpen}
        onClose={() => {
          setImportOpen(false);
          if (searchParams.get('import')) {
            const next = new URLSearchParams(searchParams);
            next.delete('import');
            setSearchParams(next, { replace: true });
          }
        }}
        onImported={refreshUsers}
      />

      <UserFormModal
        open={formState.open}
        user={formState.user}
        refs={refs}
        onClose={() => setFormState({ open: false, user: null })}
        onSaved={refreshUsers}
      />

      <FaceEnrollModal
        open={Boolean(faceUser)}
        user={faceUser}
        onClose={() => setFaceUser(null)}
        onEnrolled={refreshUsers}
      />

      <ConfirmDialog
        {...confirmState}
        busy={bulkBusy}
        onCancel={() => setConfirmState({ open: false })}
      />
    </div>
  );
}
