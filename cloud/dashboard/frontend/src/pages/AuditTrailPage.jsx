import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';

export function AuditTrailPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10));
  const pageSize = [10, 25, 50, 100].includes(parseInt(searchParams.get('page_size') || '25', 10))
    ? parseInt(searchParams.get('page_size') || '25', 10)
    : 25;
  const qParam = searchParams.get('q') || '';
  const targetType = searchParams.get('target_type') || 'ALL';

  const [searchInput, setSearchInput] = useState(qParam);

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

  const { data, isLoading } = useQuery({
    queryKey: ['audit-events-paginated', { page, pageSize, qParam, targetType }],
    queryFn: () =>
      cloudApi.get('/api/infra/audit-events/paginated', {
        page,
        page_size: pageSize,
        q: qParam,
        target_type: targetType,
      }),
    placeholderData: (prev) => prev,
  });

  const columns = useMemo(
    () => [
      {
        id: 'time',
        header: 'When',
        cell: ({ row }) => (
          <span className="text-xs font-mono text-slate-500 tabular-nums whitespace-nowrap">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        id: 'actor',
        header: 'Actor',
        cell: ({ row }) => (
          <div>
            <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">{row.original.actor_name}</div>
            {row.original.actor_email && <div className="text-xs font-mono text-slate-500">{row.original.actor_email}</div>}
          </div>
        ),
      },
      {
        id: 'action',
        header: 'Action & Target',
        cell: ({ row }) => (
          <div>
            <span className="font-mono text-xs font-bold text-indigo-700 dark:text-indigo-300">{row.original.action}</span>
            <div className="text-xs text-slate-500">
              {row.original.target_type} {row.original.target_id ? `· ${row.original.target_id}` : ''}
            </div>
          </div>
        ),
      },
      {
        id: 'result',
        header: 'Result',
        cell: ({ row }) => (
          <StatusBadge variant={row.original.result === 'success' ? 'success' : 'danger'}>
            {row.original.result}
          </StatusBadge>
        ),
      },
      {
        id: 'details',
        header: 'Metadata',
        cell: ({ row }) => (
          <code className="text-[11px] font-mono text-slate-600 dark:text-slate-400 break-all">
            {Object.keys(row.original.details || {}).length > 0 ? JSON.stringify(row.original.details) : '—'}
          </code>
        ),
      },
    ],
    []
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
          Admin Audit Trail
        </h1>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search action, target, IP..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
        <select
          value={targetType}
          onChange={(e) => updateParams({ target_type: e.target.value })}
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
        >
          <option value="ALL">All Target Types</option>
          <option value="user">user</option>
          <option value="role">role</option>
          <option value="admin">admin</option>
          <option value="device">device</option>
          <option value="node">node</option>
          <option value="jwt_session">jwt_session</option>
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
      />
    </div>
  );
}
