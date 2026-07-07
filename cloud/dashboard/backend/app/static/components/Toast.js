const { useEffect } = React;

// Redesigned Toast notification component
        function Toast({ message, type, onClose }) {
            useEffect(() => {
                const timer = setTimeout(() => onClose(), 4500);
                return () => clearTimeout(timer);
            }, [message, onClose]);

            const isError = type === 'error';

            return (
                <div className={`fixed bottom-6 right-6 z-[100] flex items-center gap-3 px-4 py-3.5 rounded-2xl shadow-2xl border max-w-sm animate-in fade-in slide-in-from-bottom-4 backdrop-blur-md ${
                    isError
                        ? 'bg-slate-950/90 border-red-900/50 shadow-red-900/10'
                        : 'bg-slate-950/90 border-emerald-900/50 shadow-emerald-900/10'
                }`}>
                    <div className={`p-1.5 rounded-lg shrink-0 ${isError ? 'bg-red-500/15 text-red-400' : 'bg-emerald-500/15 text-emerald-400'}`}>
                        <Icon name={isError ? "alert-circle" : "check-circle"} className="w-4 h-4" />
                    </div>
                    <p className="text-sm font-semibold text-slate-100 flex-1">{message}</p>
                    <button
                        onClick={onClose}
                        className="p-1 text-slate-500 hover:text-slate-300 rounded-lg hover:bg-slate-800 transition-colors duration-150 ml-1"
                    >
                        <Icon name="x" className="w-3.5 h-3.5" />
                    </button>
                </div>
            );
        }

window.Toast = Toast;
