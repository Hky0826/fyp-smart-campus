import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CalendarClock, Search, X } from 'lucide-react';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';

export function AppointmentsPage() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const { data: appointments = [], isLoading } = useQuery({
    queryKey: ['appointments'],
    queryFn: () => cloudApi.get('/api/academics/appointments'),
  });

  const rows = useMemo(() => {
    const list = Array.isArray(appointments) ? appointments : [];
    const q = search.trim().toLowerCase();
    return list.filter((item) => {
      if (statusFilter !== 'ALL' && String(item.status || '').toUpperCase() !== statusFilter) {
        return false;
      }
      if (!q) return true;
      return JSON.stringify(item).toLowerCase().includes(q);
    });
  }, [appointments, search, statusFilter]);

  const statusVariant = (st) => {
    const upper = String(st || '').toUpperCase();
    if (upper === 'CONFIRMED' || upper === 'APPROVED' || upper === 'COMPLETED') return 'success';
    if (upper === 'CANCELLED' || upper === 'REJECTED') return 'danger';
    return 'warning';
  };

  const columns = useMemo(
    () => [
      {
        id: 'id',
        header: 'ID',
        cell: ({ row }) => <span className="font-mono text-xs text-slate-500">#{row.original.appointment_id}</span>,
      },
      {
        id: 'when',
        header: 'Scheduled (MYT)',
        cell: ({ row }) => (
          <span className="text-xs font-mono text-slate-700 dark:text-slate-300 tabular-nums whitespace-nowrap">
            {formatDateTime(row.original.scheduled_at)}
          </span>
        ),
      },
      {
        id: 'participants',
        header: 'Participants',
        cell: ({ row }) => {
          const r = row.original;
          return (
            <div className="text-xs space-y-0.5">
              {r.requester_id != null && (
                <div>
                  <span className="text-slate-500">Requester:</span>{' '}
                  <span className="font-mono font-semibold text-slate-800 dark:text-slate-200">#{r.requester_id}</span>
                </div>
              )}
              {r.host_id != null && (
                <div>
                  <span className="text-slate-500">Host:</span>{' '}
                  <span className="font-mono font-semibold text-slate-800 dark:text-slate-200">#{r.host_id}</span>
                </div>
              )}
            </div>
          );
        },
      },
      {
        id: 'purpose',
        header: 'Purpose',
        cell: ({ row }) => <span className="text-sm text-slate-800 dark:text-slate-200">{row.original.purpose || '—'}</span>,
      },
      {
        id: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <StatusBadge variant={statusVariant(row.original.status)} dot>
            {row.original.status || 'PENDING'}
          </StatusBadge>
        ),
      },
    ],
    []
  );

  const hasFilters = Boolean(search.trim() || statusFilter !== 'ALL');

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <div className="p-2.5 rounded-xl bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400">
          <CalendarClock className="w-5 h-5" />
        </div>
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">Appointments</h1>
          <p className="text-xs text-slate-500">View and filter scheduled campus appointments.</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search purpose, ID, status..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status"
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-1.5 text-xs font-semibold"
        >
          <option value="ALL">All Statuses</option>
          <option value="PENDING">PENDING</option>
          <option value="CONFIRMED">CONFIRMED</option>
          <option value="COMPLETED">COMPLETED</option>
          <option value="CANCELLED">CANCELLED</option>
        </select>
        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              setSearch('');
              setStatusFilter('ALL');
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="w-3.5 h-3.5" /> Clear
          </button>
        )}
      </div>

      <DataTable
        columns={columns}
        data={rows}
        loading={isLoading}
        total={rows.length}
        page={1}
        pageSize={Math.max(rows.length, 25)}
        totalPages={1}
      />
    </div>
  );
}
