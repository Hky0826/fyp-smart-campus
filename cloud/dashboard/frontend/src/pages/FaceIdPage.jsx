import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Eye, RefreshCw, ScanFace, Search } from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { useAuthSession } from '../providers/AuthProvider';
import { useToast } from '../providers/ToastProvider';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { FaceEnrollModal } from '../components/users/FaceEnrollModal';

export function FaceIdPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { admin } = useAuthSession();
  const toast = useToast();

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10));
  const pageSize = [10, 25, 50, 100].includes(parseInt(searchParams.get('page_size') || '25', 10))
    ? parseInt(searchParams.get('page_size') || '25', 10)
    : 25;
  const qParam = searchParams.get('q') || '';
  const faceStatus = searchParams.get('face_status') || 'ALL';
  const roleId = searchParams.get('role_id') || 'ALL';

  const [searchInput, setSearchInput] = useState(qParam);
  const [faceUser, setFaceUser] = useState(null);
  const [reembedOpen, setReembedOpen] = useState(false);
  const [reembedding, setReembedding] = useState(false);

  const updateParams = (patch, resetPage = true) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([k, v]) => {
      if (!v || v === 'ALL') next.delete(k);
      else next.set(k, String(v));
    });
    if (resetPage) next.set('page', '1');
    setSearchParams(next, { replace: true });
  };

  useEffect(() => {
    const t = setTimeout(() => {
      if (searchInput.trim() !== qParam) updateParams({ q: searchInput.trim() });
    }, 250);
    return () => clearTimeout(t);
  }, [searchInput]);

  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: () => cloudApi.get('/api/iam/roles'),
    staleTime: 60_000,
  });

  const { data, isLoading } = useQuery({
    queryKey: ['face-id-users', { page, pageSize, qParam, faceStatus, roleId }],
    queryFn: () =>
      cloudApi.get('/api/iam/users/paginated', {
        page,
        page_size: pageSize,
        q: qParam,
        face_status: faceStatus,
        role_id: roleId,
      }),
    placeholderData: (prev) => prev,
  });

  const handleReembedAll = async () => {
    setReembedOpen(false);
    setReembedding(true);
    try {
      const res = await cloudApi.post('/api/iam/users/reembed-all', {});
      toast.success(res.detail || 'Re-embedded all facial vectors.');
      queryClient.invalidateQueries({ queryKey: ['face-id-users'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setReembedding(false);
    }
  };

  const columns = useMemo(
    () => [
      {
        id: 'user',
        header: 'User',
        cell: ({ row }) => {
          const u = row.original;
          return (
            <div>
              <div className="font-bold text-slate-900 dark:text-slate-100">
                {u.full_name} <span className="text-xs font-mono text-slate-400">#{u.user_id}</span>
              </div>
              <div className="text-xs font-mono text-slate-500">{u.email}</div>
            </div>
          );
        },
      },
      {
        id: 'status',
        header: 'Biometric Status',
        cell: ({ row }) => (
          <StatusBadge variant={row.original.face_enrolled ? 'success' : 'neutral'} dot>
            {row.original.face_enrolled ? 'Enrolled' : 'Not Enrolled'}
          </StatusBadge>
        ),
      },
      {
        id: 'poses',
        header: 'Enrolled Poses',
        cell: ({ row }) => (
          <span className="text-xs font-mono text-slate-500">
            {row.original.enrolled_poses?.length
              ? row.original.enrolled_poses.join(', ')
              : 'None'}
          </span>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        meta: { align: 'right', stopClick: true },
        cell: ({ row }) => (
          <div className="flex items-center justify-end gap-1.5">
            <button
              type="button"
              onClick={() => navigate(`/dashboard/users/${row.original.user_id}`)}
              className="p-1.5 rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-500/15"
              title="Open User Workspace"
            >
              <Eye className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => setFaceUser(row.original)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-indigo-50 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100"
            >
              <ScanFace className="w-3.5 h-3.5" /> Enroll
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
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
            Face ID Enrollment
          </h1>
        </div>
        {admin?.admin_type === 'SUPER_ADMIN' && (
          <button
            type="button"
            disabled={reembedding}
            onClick={() => setReembedOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 hover:border-indigo-400 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${reembedding ? 'animate-spin' : ''}`} />
            <span>{reembedding ? 'Re-processing...' : 'Re-embed All Vectors'}</span>
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search user..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
        <select
          value={faceStatus}
          onChange={(e) => updateParams({ face_status: e.target.value })}
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
        >
          <option value="ALL">All Biometric Status</option>
          <option value="ENROLLED">Enrolled</option>
          <option value="NOT_ENROLLED">Not Enrolled</option>
        </select>
        <select
          value={roleId}
          onChange={(e) => updateParams({ role_id: e.target.value })}
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
        >
          <option value="ALL">All Roles</option>
          {roles.map((r) => (
            <option key={r.role_id} value={r.role_id}>{r.role_name}</option>
          ))}
        </select>
      </div>

      <DataTable
        columns={columns}
        data={data?.items ?? []}
        loading={isLoading}
        total={data?.total ?? 0}
        page={data?.page ?? page}
        pageSize={data?.page_size ?? pageSize}
        totalPages={data?.total_pages ?? 1}
        onPageChange={(p) => updateParams({ page: p }, false)}
        onPageSizeChange={(sz) => updateParams({ page_size: sz }, true)}
        onRowClick={(u) => navigate(`/dashboard/users/${u.user_id}`)}
      />

      <FaceEnrollModal
        open={Boolean(faceUser)}
        user={faceUser}
        onClose={() => setFaceUser(null)}
        onEnrolled={() => queryClient.invalidateQueries({ queryKey: ['face-id-users'] })}
      />

      <ConfirmDialog
        open={reembedOpen}
        title="Re-embed All Facial Vectors"
        message="This regenerates all SFace and ArcFace embeddings from stored face crops on disk. Continue?"
        confirmLabel="Re-embed All"
        variant="primary"
        onConfirm={handleReembedAll}
        onCancel={() => setReembedOpen(false)}
      />
    </div>
  );
}
