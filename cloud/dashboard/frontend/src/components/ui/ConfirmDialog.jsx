import { useEffect, useState } from 'react';
import { AlertTriangle, Info } from 'lucide-react';

export function ConfirmDialog({
  open,
  title = 'Confirm Action',
  message = '',
  impactNote = '',
  requireText = '',
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'danger',
  busy = false,
  onConfirm,
  onCancel,
}) {
  const [typed, setTyped] = useState('');

  useEffect(() => {
    if (!open) {
      setTyped('');
      return;
    }
    const onKey = (e) => {
      if (e.key === 'Escape' && !busy) onCancel?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, busy, onCancel]);

  if (!open) return null;

  const isDanger = variant === 'danger';
  const needsTyping = Boolean(requireText);
  const canConfirm = !busy && (!needsTyping || typed.trim() === requireText);

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-900/50 dark:bg-slate-950/75 backdrop-blur-xs p-4"
      onClick={() => !busy && onCancel?.()}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3.5">
          <div
            className={`p-2.5 rounded-xl shrink-0 border ${
              isDanger
                ? 'bg-red-50 border-red-200 text-red-600 dark:bg-red-500/10 dark:border-red-500/20 dark:text-red-400'
                : 'bg-indigo-50 border-indigo-200 text-indigo-600 dark:bg-indigo-500/10 dark:border-indigo-500/20 dark:text-indigo-400'
            }`}
          >
            {isDanger ? <AlertTriangle className="w-5 h-5" /> : <Info className="w-5 h-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">{title}</h3>
            {message && (
              <p className="text-sm text-slate-600 dark:text-slate-400 mt-1.5 leading-relaxed">{message}</p>
            )}
            {impactNote && (
              <div className="mt-3 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 text-xs font-medium text-amber-800 dark:text-amber-300">
                {impactNote}
              </div>
            )}
            {needsTyping && (
              <div className="mt-3">
                <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1">
                  Type <span className="font-mono font-bold text-slate-900 dark:text-slate-100">{requireText}</span> to confirm
                </label>
                <input
                  type="text"
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500"
                />
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center justify-end gap-2.5 mt-6 pt-4 border-t border-slate-200 dark:border-slate-800">
          <button
            type="button"
            disabled={busy}
            onClick={onCancel}
            className="px-4 py-2 rounded-xl text-sm font-semibold text-slate-700 dark:text-slate-300 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            disabled={!canConfirm}
            onClick={onConfirm}
            className={`px-4 py-2 rounded-xl text-sm font-bold text-white transition-all flex items-center gap-2 disabled:opacity-40 ${
              isDanger
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-indigo-600 hover:bg-indigo-700'
            }`}
          >
            {busy && <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />}
            <span>{confirmLabel}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
