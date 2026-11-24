import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';

export function AccessLogsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10));
  const pageSize = [10, 25, 50, 100].includes(parseInt(searchParams.get('page_size') || '25', 10))
    ? parseInt(searchParams.get('page_size') || '25', 10)
    : 25;
  const qParam = searchParams.get('q') || '';
  const status = searchParams.get('status') || 'ALL';
  const dateFrom = searchParams.get('date_from') || '';
  const dateTo = searchParams.get('date_to') || '';

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
    queryKey: ['auth-logs-paginated', { page, pageSize, qParam, status, dateFrom, dateTo }],
    queryFn: () =>
      cloudApi.get('/api/infra/auth-logs/paginated', {
        page,
        page_size: pageSize,
        q: qParam,
        status,
        date_from: dateFrom,
        date_to: dateTo,
      }),
    placeholderData: (prev) => prev,
  });

  const columns = useMemo(
    () => [
      {
        id: 'time',
        header: 'Timestamp',
        cell: ({ row }) => (
          <span className="text-xs font-mono text-slate-600 dark:text-slate-400 tabular-nums whitespace-nowrap">
            {formatDateTime(row.original.timestamp)}
          </span>
        ),
      },
      {
        id: 'user',
        header: 'User',
        cell: ({ row }) => {
          const r = row.original;
          return (
            <div>
              <button
                type="button"
                onClick={() => r.user_id && navigate(`/dashboard/users/${r.user_id}`)}
                className="font-semibold text-slate-900 dark:text-slate-100 hover:text-indigo-600 text-left"
              >
                {r.full_name}
              </button>
              {r.email && <div className="text-xs font-mono text-slate-500">{r.email}</div>}
            </div>
          );
        },
      },
      {
        id: 'device',
        header: 'Device & Location',
        cell: ({ row }) => {
          const r = row.original;
          return (
            <div>
              <button
                type="button"
                onClick={() => navigate(`/dashboard/devices/${r.device_id}`)}
                className="text-sm font-semibold text-slate-800 dark:text-slate-200 hover:text-indigo-600"
              >
                {r.device_name}
              </button>
              {r.node_label && <div className="text-xs text-slate-500">{r.node_label}</div>}
            </div>
          );
        },
      },
      {
        id: 'status',
        header: 'Decision',
        cell: ({ row }) => {
          const st = row.original.auth_status;
          const variant = st === 'SUCCESS' ? 'success' : st === 'SPOOFING' ? 'danger' : 'warning';
          return <StatusBadge variant={variant} dot>{st}</StatusBadge>;
        },
      },
      {
        id: 'score',
        header: 'Confidence / Reason',
        cell: ({ row }) => {
          const r = row.original;
          return (
            <div className="text-xs">
              {r.confidence_score != null && (
                <span className="font-mono font-semibold text-slate-700 dark:text-slate-300 mr-2">
                  {(r.confidence_score * 100).toFixed(1)}%
                </span>
              )}
              <span className="text-slate-500">{r.reason || '—'}</span>
            </div>
          );
        },
      },
    ],
    []
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">Access Logs</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Server-paginated gate and door authentication history with date-range and anomaly filtering.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search user, device, reason..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
        <select
          value={status}
          onChange={(e) => updateParams({ status: e.target.value })}
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
        >
          <option value="ALL">All Decisions</option>
          <option value="SUCCESS">SUCCESS</option>
          <option value="FAILED">FAILED</option>
          <option value="SPOOFING">SPOOFING</option>
        </select>
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => updateParams({ date_from: e.target.value })}
          aria-label="Date from"
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
        />
        <input
          type="date"
          value={dateTo}
          onChange={(e) => updateParams({ date_to: e.target.value })}
          aria-label="Date to"
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
        />
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
