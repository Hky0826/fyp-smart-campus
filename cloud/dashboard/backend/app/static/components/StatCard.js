// Stat summary card with color variants and accent top border
        function StatCard({ title, value, icon, changeText, color = "indigo" }) {
            const colorMap = {
                blue:    { bg: 'bg-indigo-500/10',  border: 'border-indigo-500/20',  text: 'text-indigo-400',  accent: 'bg-indigo-600' }, // Map legacy blue to indigo
                indigo:  { bg: 'bg-indigo-500/10',  border: 'border-indigo-500/20',  text: 'text-indigo-400',  accent: 'bg-indigo-600' },
                violet:  { bg: 'bg-violet-500/10',  border: 'border-violet-500/20',  text: 'text-violet-400',  accent: 'bg-violet-600' },
                emerald: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', text: 'text-emerald-400', accent: 'bg-emerald-500' },
                amber:   { bg: 'bg-amber-500/10',   border: 'border-amber-500/20',   text: 'text-amber-400',   accent: 'bg-amber-500'  },
            };
            const c = colorMap[color] || colorMap.indigo;

            return (
                <div className="bg-slate-900/50 backdrop-blur-sm border border-slate-800 rounded-2xl p-5 shadow-xl hover:border-slate-700/80 hover:-translate-y-0.5 transition-all duration-300 relative overflow-hidden group">
                    {/* Top accent border */}
                    <div className={`absolute top-0 left-0 right-0 h-0.5 ${c.accent} rounded-t-2xl`}></div>
                    <div className="flex justify-between items-start pt-1">
                        <div>
                            <p className="text-xs text-slate-500 font-semibold tracking-wide uppercase">{title}</p>
                            <h3 className="text-3xl font-extrabold mt-2 text-slate-100 tracking-tight">{value}</h3>
                        </div>
                        <div className={`p-3 ${c.bg} border ${c.border} ${c.text} rounded-xl group-hover:scale-105 transition-transform duration-300`}>
                            <Icon name={icon} className="w-5 h-5" />
                        </div>
                    </div>
                    {changeText && (
                        <div className="flex items-center gap-1.5 mt-4 pt-3 border-t border-slate-800/60">
                            <span className={`text-xs ${c.text} font-semibold`}>{changeText}</span>
                        </div>
                    )}
                </div>
            );
        }

window.StatCard = StatCard;
