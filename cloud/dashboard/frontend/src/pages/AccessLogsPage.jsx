import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Calendar, Camera, Search, X } from 'lucide-react';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';

function formatMytDate(date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kuala_Lumpur',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const y = parts.find((p) => p.type === 'year')?.value;
  const m = parts.find((p) => p.type === 'month')?.value;
  const d = parts.find((p) => p.type === 'day')?.value;
  return `${y}-${m}-${d}`;
}

function getPresetRange(preset) {
  const now = new Date();
  const today = formatMytDate(now);
  if (preset === 'TODAY') return { date_from: today, date_to: today };
  if (preset === 'YESTERDAY') {
    const y = formatMytDate(new Date(now.getTime() - 86400_000));
    return { date_from: y, date_to: y };
  }
  if (preset === 'LAST_7_DAYS') {
    const start = formatMytDate(new Date(now.getTime() - 6 * 86400_000));
    return { date_from: start, date_to: today };
  }
  if (preset === 'LAST_30_DAYS') {
    const start = formatMytDate(new Date(now.getTime() - 29 * 86400_000));
    return { date_from: start, date_to: today };
  }
  return { date_from: '', date_to: '' };
}

export function AccessLogsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10));
  const pageSize = [10, 25, 50, 100].includes(parseInt(searchParams.get('page_size') || '25', 10))
    ? parseInt(searchParams.get('page_size') || '25', 10)
    : 25;
  const qParam = searchParams.get('q') || '';
  const status = searchParams.get('status') || 'ALL';
  const roleId = searchParams.get('role_id') || '';
  const datePreset = searchParams.get('date_preset') || (searchParams.get('date_from') || searchParams.get('date_to') ? 'CUSTOM' : 'ALL');
  const dateFrom = searchParams.get('date_from') || '';
  const dateTo = searchParams.get('date_to') || '';

  const [searchInput, setSearchInput] = useState(qParam);
  const [selectedSnapshot, setSelectedSnapshot] = useState(null);

  const updateParams = (patch, resetPage = true) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        Object.entries(patch).forEach(([k, v]) => {
          if (!v || v === 'ALL') next.delete(k);
          else next.set(k, String(v));
        });
        if (resetPage) next.set('page', '1');
        return next;
      },
      { replace: true }
    );
  };

  useEffect(() => {
    const t = setTimeout(() => {
      const trimmed = searchInput.trim();
      if (trimmed !== qParam) {
        updateParams({ q: trimmed });
      }
    }, 250);
    return () => clearTimeout(t);
  }, [searchInput, qParam]);

  const handleDatePresetChange = (preset) => {
    if (preset === 'ALL') {
      updateParams({ date_preset: '', date_from: '', date_to: '' });
    } else if (preset === 'CUSTOM') {
      updateParams({ date_preset: 'CUSTOM' });
    } else {
      const range = getPresetRange(preset);
      updateParams({ date_preset: preset, ...range });
    }
  };

  const { data: roles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: () => cloudApi.get('/api/iam/roles'),
    staleTime: 60_000,
  });

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: ['auth-logs-paginated', page, pageSize, qParam, status, roleId, dateFrom, dateTo],
    queryFn: () =>
      cloudApi.get('/api/infra/auth-logs/paginated', {
        page,
        page_size: pageSize,
        q: qParam,
        status,
        role_id: roleId || undefined,
        date_from: dateFrom,
        date_to: dateTo,
      }),
  });

  const hasActiveFilters = Boolean(qParam || status !== 'ALL' || roleId || dateFrom || dateTo || datePreset !== 'ALL');

  const handleClearFilters = () => {
    setSearchInput('');
    setSearchParams({ page: '1', page_size: String(pageSize) }, { replace: true });
  };

  const columns = useMemo(
    () => [
      {
        id: 'time',
        header: 'Timestamp (MYT)',
        cell: ({ row }) => (
          <span className="text-xs font-mono text-slate-600 dark:text-slate-400 tabular-nums whitespace-nowrap">
            {formatDateTime(row.original.timestamp)}
          </span>
        ),
      },
      {
        id: 'user',
        header: 'User & Role',
        cell: ({ row }) => {
          const r = row.original;
          return (
            <div>
              <div className="flex items-center gap-1.5 flex-wrap">
                <button
                  type="button"
                  onClick={() => r.user_id && navigate(`/dashboard/users/${r.user_id}`)}
                  className="font-semibold text-slate-900 dark:text-slate-100 hover:text-indigo-600 text-left"
                >
                  {r.full_name}
                </button>
                {(r.roles || []).map((roleName) => (
                  <StatusBadge key={roleName} variant="info">
                    {roleName}
                  </StatusBadge>
                ))}
              </div>
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
      {
        id: 'snapshot',
        header: 'Snapshot',
        meta: { align: 'right', stopClick: true },
        cell: ({ row }) => {
          const r = row.original;
          if (!r.has_image) {
            return <span className="text-xs text-slate-400">—</span>;
          }
          return (
            <button
              type="button"
              onClick={() => setSelectedSnapshot(r)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold bg-indigo-50 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-500/30 hover:bg-indigo-100 dark:hover:bg-indigo-500/25"
            >
              <Camera className="w-3.5 h-3.5" /> View
            </button>
          );
        },
      },
    ],
    [navigate]
  );

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">Access Logs</h1>
        {isFetching && !isLoading && (
          <span className="text-xs font-semibold text-indigo-500 animate-pulse">Updating...</span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative flex-1 min-w-[220px] max-w-sm">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                updateParams({ q: searchInput.trim() });
              }
            }}
            placeholder="Search user name, email, device, room, reason..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
        <select
          value={roleId}
          onChange={(e) => updateParams({ role_id: e.target.value })}
          aria-label="Filter by role"
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
        >
          <option value="">All Roles</option>
          {roles.map((r) => (
            <option key={r.role_id} value={String(r.role_id)}>
              {r.role_name}
            </option>
          ))}
        </select>
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
        <div className="inline-flex items-center gap-1.5">
          <Calendar className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <select
            value={datePreset}
            onChange={(e) => handleDatePresetChange(e.target.value)}
            aria-label="Date range preset"
            className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
          >
            <option value="ALL">All Dates</option>
            <option value="TODAY">Today</option>
            <option value="YESTERDAY">Yesterday</option>
            <option value="LAST_7_DAYS">Last 7 Days</option>
            <option value="LAST_30_DAYS">Last 30 Days</option>
            <option value="CUSTOM">Custom Range...</option>
          </select>
        </div>
        {datePreset === 'CUSTOM' && (
          <>
            <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500">
              <span>From</span>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => updateParams({ date_preset: 'CUSTOM', date_from: e.target.value })}
                aria-label="Date from"
                className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-2.5 py-1.5 text-xs font-semibold text-slate-800 dark:text-slate-200 dark:[color-scheme:dark]"
              />
            </label>
            <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500">
              <span>To</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => updateParams({ date_preset: 'CUSTOM', date_to: e.target.value })}
                aria-label="Date to"
                className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-2.5 py-1.5 text-xs font-semibold text-slate-800 dark:text-slate-200 dark:[color-scheme:dark]"
              />
            </label>
          </>
        )}
        {hasActiveFilters && (
          <button
            type="button"
            onClick={handleClearFilters}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="w-3.5 h-3.5" /> Clear
          </button>
        )}
      </div>

      {isError && (
        <div className="p-3.5 rounded-2xl bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-xs font-semibold text-red-700 dark:text-red-300">
          Failed to load access logs: {error?.message || 'Unknown error'}
        </div>
      )}

      <DataTable
        columns={columns}
        data={data?.items ?? []}
        loading={isLoading || isFetching}
        total={data?.total ?? 0}
        page={data?.page ?? page}
        pageSize={data?.page_size ?? pageSize}
        totalPages={data?.total_pages ?? 1}
        onPageChange={(p) => updateParams({ page: p }, false)}
        onPageSizeChange={(sz) => updateParams({ page_size: sz }, true)}
      />

      {selectedSnapshot && (
        <div
          className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4"
          onClick={() => setSelectedSnapshot(null)}
        >
          <div
            className="w-full max-w-lg rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 shadow-2xl space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-extrabold text-slate-900 dark:text-slate-100">
                    {selectedSnapshot.full_name}
                  </h3>
                  <StatusBadge
                    variant={
                      selectedSnapshot.auth_status === 'SUCCESS'
                        ? 'success'
                        : selectedSnapshot.auth_status === 'SPOOFING'
                          ? 'danger'
                          : 'warning'
                    }
                    dot
                  >
                    {selectedSnapshot.auth_status}
                  </StatusBadge>
                </div>
                <p className="text-xs text-slate-500 mt-0.5">
                  {formatDateTime(selectedSnapshot.timestamp)} · {selectedSnapshot.device_name}
                  {selectedSnapshot.node_label ? ` (${selectedSnapshot.node_label})` : ''}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedSnapshot(null)}
                className="p-1 text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="rounded-xl overflow-hidden bg-slate-950 border border-slate-800 flex items-center justify-center min-h-[240px]">
              <img
                src={`/api/infra/auth-logs/${selectedSnapshot.log_id}/image`}
                alt={`Captured snapshot for log #${selectedSnapshot.log_id}`}
                className="max-h-[420px] w-auto object-contain"
              />
            </div>

            <div className="flex items-center justify-between text-xs text-slate-500">
              <span>
                {selectedSnapshot.confidence_score != null
                  ? `Confidence: ${(selectedSnapshot.confidence_score * 100).toFixed(1)}%`
                  : ''}
                {selectedSnapshot.reason ? ` · ${selectedSnapshot.reason}` : ''}
              </span>
              <button
                type="button"
                onClick={() => setSelectedSnapshot(null)}
                className="px-3.5 py-1.5 rounded-xl font-bold bg-indigo-600 hover:bg-indigo-700 text-white"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
