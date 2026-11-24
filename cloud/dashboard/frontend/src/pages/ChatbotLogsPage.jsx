import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Search, X } from 'lucide-react';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';

export function ChatbotLogsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10));
  const pageSize = [10, 25, 50, 100].includes(parseInt(searchParams.get('page_size') || '25', 10))
    ? parseInt(searchParams.get('page_size') || '25', 10)
    : 25;
  const qParam = searchParams.get('q') || '';
  const navFilter = searchParams.get('nav') || 'ALL';

  const [searchInput, setSearchInput] = useState(qParam);
  const [inspectRow, setInspectRow] = useState(null);

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
    queryKey: ['chatbot-queries-paginated', { page, pageSize, qParam, navFilter }],
    queryFn: () =>
      cloudApi.get('/api/rag/chatbot-queries/paginated', {
        page,
        page_size: pageSize,
        q: qParam,
        is_navigational: navFilter === 'NAV' ? true : navFilter === 'INFO' ? false : undefined,
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
            {formatDateTime(row.original.timestamp)}
          </span>
        ),
      },
      {
        id: 'user',
        header: 'Requester',
        cell: ({ row }) => (
          <div>
            <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">{row.original.user_name}</div>
            <div className="text-[11px] font-mono text-slate-500">{row.original.user_role}</div>
          </div>
        ),
      },
      {
        id: 'query',
        header: 'Query',
        cell: ({ row }) => (
          <div className="max-w-md truncate text-sm text-slate-800 dark:text-slate-200">{row.original.query_text}</div>
        ),
      },
      {
        id: 'type',
        header: 'Type',
        cell: ({ row }) => (
          <StatusBadge variant={row.original.is_navigational ? 'info' : 'neutral'}>
            {row.original.is_navigational ? 'Navigation' : 'Info'}
          </StatusBadge>
        ),
      },
    ],
    []
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">Chatbot Logs</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Server-paginated RAG conversation history. Click any row to inspect the full prompt and grounded response.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search queries, responses, users..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
        <select
          value={navFilter}
          onChange={(e) => updateParams({ nav: e.target.value })}
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
        >
          <option value="ALL">All Query Types</option>
          <option value="NAV">Navigational</option>
          <option value="INFO">Informational</option>
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
        onRowClick={(r) => setInspectRow(r)}
      />

      {inspectRow && (
        <div className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-900/50 p-4" onClick={() => setInspectRow(null)}>
          <div className="w-full max-w-2xl max-h-[82vh] flex flex-col rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold">Conversation #{inspectRow.query_id}</h3>
                <p className="text-xs text-slate-500">{inspectRow.user_name} ({inspectRow.user_role}) · {formatDateTime(inspectRow.timestamp)}</p>
              </div>
              <button type="button" onClick={() => setInspectRow(null)} className="p-1 text-slate-400"><X className="w-5 h-5" /></button>
            </div>
            <div className="p-6 overflow-y-auto space-y-4 scrollbar-thin">
              <div>
                <div className="text-xs font-bold uppercase text-slate-500 mb-1">User Query</div>
                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 text-sm whitespace-pre-wrap">
                  {inspectRow.query_text}
                </div>
              </div>
              <div>
                <div className="text-xs font-bold uppercase text-indigo-600 dark:text-indigo-400 mb-1">Assistant Response</div>
                <div className="p-4 rounded-xl bg-indigo-50/40 dark:bg-indigo-500/5 border border-indigo-200 dark:border-indigo-500/20 text-sm whitespace-pre-wrap">
                  {inspectRow.response_text}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
