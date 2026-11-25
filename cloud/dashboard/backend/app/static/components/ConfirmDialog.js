const { useEffect } = React;

function ConfirmDialog({
    open,
    title = "Confirm Action",
    message = "",
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    variant = "danger",
    busy = false,
    onConfirm,
    onCancel,
}) {
    useEffect(() => {
        if (!open) return;
        const onKeyDown = (e) => {
            if (e.key === "Escape" && !busy) onCancel?.();
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [open, busy, onCancel]);

    if (!open) return null;

    const isDanger = variant === "danger";
    const iconName = isDanger ? "alert-triangle" : "info";

    return (
        <div
            className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4"
            onClick={() => { if (!busy) onCancel?.(); }}
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-dialog-title"
        >
            <div
                className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-start gap-4">
                    <div className={`p-2.5 rounded-xl shrink-0 border ${isDanger ? "bg-red-500/10 border-red-500/20 text-red-400" : "bg-indigo-500/10 border-indigo-500/20 text-indigo-400"}`}>
                        <Icon name={iconName} className="w-5 h-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                        <h3 id="confirm-dialog-title" className="text-base font-bold text-slate-100">
                            {title}
                        </h3>
                        {message && (
                            <p className="text-sm text-slate-400 mt-1.5 leading-relaxed">
                                {message}
                            </p>
                        )}
                    </div>
                </div>
                <div className="flex items-center justify-end gap-2.5 mt-6 pt-4 border-t border-slate-800/80">
                    <button
                        type="button"
                        disabled={busy}
                        onClick={onCancel}
                        className="px-4 py-2 rounded-xl text-sm font-semibold text-slate-300 bg-slate-800 hover:bg-slate-700 border border-slate-700/60 transition-colors disabled:opacity-50"
                    >
                        {cancelLabel}
                    </button>
                    <button
                        type="button"
                        disabled={busy}
                        onClick={onConfirm}
                        className={`px-4 py-2 rounded-xl text-sm font-bold text-white transition-all flex items-center gap-2 disabled:opacity-50 ${
                            isDanger
                                ? "bg-red-600 hover:bg-red-500 shadow-md shadow-red-950/30"
                                : "bg-indigo-600 hover:bg-indigo-500 shadow-md shadow-indigo-950/30"
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

window.ConfirmDialog = ConfirmDialog;
