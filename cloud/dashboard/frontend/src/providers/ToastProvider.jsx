import { createContext, useCallback, useContext, useState } from 'react';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';

const ToastContext = createContext({
  success: () => {},
  error: () => {},
  info: () => {},
});

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (type, message) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      setToasts((prev) => [...prev.slice(-3), { id, type, message }]);
      setTimeout(() => removeToast(id), 4500);
    },
    [removeToast]
  );

  const api = {
    success: (msg) => pushToast('success', msg),
    error: (msg) => pushToast('error', msg),
    info: (msg) => pushToast('info', msg),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed bottom-5 right-5 z-[100] flex flex-col gap-2.5 max-w-sm w-full pointer-events-none">
        {toasts.map((t) => {
          const isError = t.type === 'error';
          const isInfo = t.type === 'info';
          const IconComp = isError ? AlertCircle : isInfo ? Info : CheckCircle2;
          return (
            <div
              key={t.id}
              className={`pointer-events-auto flex items-start gap-3 px-4 py-3.5 rounded-xl border shadow-lg backdrop-blur-md transition-all ${
                isError
                  ? 'bg-white/95 dark:bg-slate-900/95 border-red-200 dark:border-red-900/60 text-slate-900 dark:text-slate-100'
                  : isInfo
                    ? 'bg-white/95 dark:bg-slate-900/95 border-indigo-200 dark:border-indigo-900/60 text-slate-900 dark:text-slate-100'
                    : 'bg-white/95 dark:bg-slate-900/95 border-emerald-200 dark:border-emerald-900/60 text-slate-900 dark:text-slate-100'
              }`}
            >
              <IconComp
                className={`w-4 h-4 mt-0.5 shrink-0 ${
                  isError
                    ? 'text-red-600 dark:text-red-400'
                    : isInfo
                      ? 'text-indigo-600 dark:text-indigo-400'
                      : 'text-emerald-600 dark:text-emerald-400'
                }`}
              />
              <p className="text-sm font-medium flex-1 leading-snug">{t.message}</p>
              <button
                type="button"
                onClick={() => removeToast(t.id)}
                className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 p-0.5 rounded"
                aria-label="Dismiss notification"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
