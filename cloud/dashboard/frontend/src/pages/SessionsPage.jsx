import { useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';

export function SessionsPage() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ['jwt-sessions'],
    queryFn: () => cloudApi.get('/api/infra/jwt-sessions', { limit: 100 }),
  });

  const handleRevoke = async (sessionId) => {
    try {
      await cloudApi.delete(`/api/infra/jwt-sessions/${sessionId}`);
      toast.success('Session revoked.');
      queryClient.invalidateQueries({ queryKey: ['jwt-sessions'] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const columns = useMemo(
    () => [
      {
        id: 'id',
        header: 'Session',
        cell: ({ row }) => <span className="font-mono text-xs text-slate-500">#{row.original.session_id}</span>,
      },
      {
        id: 'principal',
        header: 'Principal',
        cell: ({ row }) => (
          <div>
            <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {row.original.user?.email || `User #${row.original.user_id}`}
            </div>
            <div className="text-xs text-slate-500">{row.original.principal_type || 'ADMIN'}</div>
          </div>
        ),
      },
      {
        id: 'issued',
        header: 'Issued / Expires',
        cell: ({ row }) => (
          <div className="text-xs text-slate-500 tabular-nums">
            <div>Issued: {formatDateTime(row.original.issued_at || row.original.created_at)}</div>
            <div>Expires: {formatDateTime(row.original.expires_at)}</div>
          </div>
        ),
      },
      {
        id: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <StatusBadge variant={row.original.is_revoked ? 'danger' : 'success'} dot>
            {row.original.is_revoked ? 'Revoked' : 'Active'}
          </StatusBadge>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        meta: { align: 'right' },
        cell: ({ row }) =>
          !row.original.is_revoked ? (
            <button
              type="button"
              onClick={() => handleRevoke(row.original.session_id)}
              className="px-3 py-1 rounded-lg text-xs font-bold bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-500/20"
            >
              Revoke
            </button>
          ) : null,
      },
    ],
    []
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">Active JWT Sessions</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Inspect issued administrator and kiosk sessions and revoke compromised tokens immediately.
        </p>
      </div>
      <DataTable columns={columns} data={sessions} loading={isLoading} total={sessions.length} />
    </div>
  );
}
