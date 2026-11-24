import { useState } from 'react';
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ChevronUp,
  ChevronsUpDown,
} from 'lucide-react';

export function DataTable({
  columns,
  data = [],
  loading = false,
  total = 0,
  page = 1,
  pageSize = 25,
  totalPages = 1,
  onPageChange,
  onPageSizeChange,
  sortBy = '',
  sortOrder = 'asc',
  onSortChange,
  density = 'comfortable',
  onRowClick,
  emptyTitle = 'No records found',
  emptyDescription = 'Try adjusting your search or filters.',
  emptyAction = null,
}) {
  const [jumpInput, setJumpInput] = useState('');

  const cellPad = density === 'compact' ? 'py-2 px-3.5' : 'py-3.5 px-4';
  const startIndex = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const endIndex = Math.min(page * pageSize, total);

  const handleJump = (e) => {
    e.preventDefault();
    const n = parseInt(jumpInput, 10);
    if (!Number.isNaN(n) && n >= 1 && n <= totalPages) {
      onPageChange?.(n);
      setJumpInput('');
    }
  };

  if (loading) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-16 flex flex-col items-center justify-center text-slate-500">
        <div className="w-8 h-8 border-2 border-indigo-600 dark:border-indigo-400 border-t-transparent rounded-full animate-spin mb-3" />
        <span className="text-sm font-medium">Loading records...</span>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-dashed border-slate-300 dark:border-slate-800 rounded-2xl py-16 px-6 flex flex-col items-center justify-center text-center">
        <h4 className="text-base font-bold text-slate-900 dark:text-slate-100">{emptyTitle}</h4>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-md">{emptyDescription}</p>
        {emptyAction && <div className="mt-4">{emptyAction}</div>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-xs overflow-hidden">
        <div className="overflow-x-auto max-h-[68vh] overflow-y-auto scrollbar-thin">
          <table className="w-full text-left text-sm border-collapse">
            <thead className="sticky top-0 z-10 bg-slate-50/95 dark:bg-slate-900/95 backdrop-blur-xs border-b border-slate-200 dark:border-slate-800">
              <tr>
                {columns.map((col, cIdx) => {
                  const sortKey = col.meta?.sortKey;
                  const align = col.meta?.align;
                  const isSorted = sortKey && sortBy === sortKey;
                  return (
                    <th
                      key={col.id || cIdx}
                      onClick={() => {
                        if (!sortKey || !onSortChange) return;
                        const nextOrder = isSorted && sortOrder === 'asc' ? 'desc' : 'asc';
                        onSortChange(sortKey, nextOrder);
                      }}
                      className={`py-3 px-4 text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 whitespace-nowrap ${
                        sortKey ? 'cursor-pointer select-none hover:text-slate-900 dark:hover:text-slate-100' : ''
                      } ${align === 'right' ? 'text-right' : ''}`}
                    >
                      <span className={`inline-flex items-center gap-1 ${align === 'right' ? 'justify-end' : ''}`}>
                        {typeof col.header === 'function' ? col.header() : col.header}
                        {sortKey && (
                          isSorted ? (
                            sortOrder === 'asc' ? (
                              <ChevronUp className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
                            ) : (
                              <ChevronDown className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
                            )
                          ) : (
                            <ChevronsUpDown className="w-3.5 h-3.5 opacity-35" />
                          )
                        )}
                      </span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
              {data.map((rowOriginal, rIdx) => (
                <tr
                  key={rowOriginal?.user_id ?? rowOriginal?.device_id ?? rowOriginal?.log_id ?? rowOriginal?.event_id ?? rowOriginal?.document_id ?? rowOriginal?.query_id ?? rowOriginal?.role_id ?? rIdx}
                  onClick={() => onRowClick?.(rowOriginal)}
                  className={`transition-colors ${
                    onRowClick ? 'cursor-pointer' : ''
                  } hover:bg-slate-50/90 dark:hover:bg-slate-800/40`}
                >
                  {columns.map((col, cIdx) => {
                    const align = col.meta?.align;
                    const stopClick = col.meta?.stopClick;
                    return (
                      <td
                        key={col.id || cIdx}
                        onClick={stopClick ? (e) => e.stopPropagation() : undefined}
                        className={`${cellPad} text-slate-700 dark:text-slate-300 ${
                          align === 'right' ? 'text-right' : ''
                        }`}
                      >
                        {typeof col.cell === 'function' ? col.cell({ row: { original: rowOriginal } }) : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {onPageChange && total > 0 && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl px-4 py-3">
          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600 dark:text-slate-400">
            <span className="tabular-nums">
              Showing <strong className="text-slate-900 dark:text-slate-100">{startIndex}</strong>–
              <strong className="text-slate-900 dark:text-slate-100">{endIndex}</strong> of{' '}
              <strong className="text-slate-900 dark:text-slate-100">{total.toLocaleString()}</strong>
            </span>
            {onPageSizeChange && (
              <label className="flex items-center gap-1.5">
                <span className="text-slate-500">Rows</span>
                <select
                  value={pageSize}
                  onChange={(e) => onPageSizeChange(parseInt(e.target.value, 10))}
                  className="bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-2 py-1 text-xs font-semibold text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  {[10, 25, 50, 100].map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
            )}
          </div>

          {totalPages > 1 && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => onPageChange(1)}
                  className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-35"
                  aria-label="First page"
                >
                  <ChevronsLeft className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => onPageChange(page - 1)}
                  className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-35"
                  aria-label="Previous page"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  const pn =
                    page <= 3
                      ? i + 1
                      : page >= totalPages - 2
                        ? totalPages - 4 + i
                        : page - 2 + i;
                  if (pn < 1 || pn > totalPages) return null;
                  return (
                    <button
                      key={pn}
                      type="button"
                      onClick={() => onPageChange(pn)}
                      className={`min-w-[32px] h-8 px-2 rounded-lg text-xs font-bold tabular-nums transition-colors ${
                        pn === page
                          ? 'bg-indigo-600 text-white shadow-xs'
                          : 'border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                      }`}
                    >
                      {pn}
                    </button>
                  );
                })}
                <button
                  type="button"
                  disabled={page >= totalPages}
                  onClick={() => onPageChange(page + 1)}
                  className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-35"
                  aria-label="Next page"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  disabled={page >= totalPages}
                  onClick={() => onPageChange(totalPages)}
                  className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-35"
                  aria-label="Last page"
                >
                  <ChevronsRight className="w-4 h-4" />
                </button>
              </div>
              {totalPages > 5 && (
                <form onSubmit={handleJump} className="flex items-center gap-1.5 pl-2 border-l border-slate-200 dark:border-slate-800">
                  <span className="text-[11px] text-slate-500">Go to</span>
                  <input
                    type="number"
                    min="1"
                    max={totalPages}
                    value={jumpInput}
                    onChange={(e) => setJumpInput(e.target.value)}
                    placeholder={String(page)}
                    className="w-14 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-2 py-1 text-xs tabular-nums text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </form>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
