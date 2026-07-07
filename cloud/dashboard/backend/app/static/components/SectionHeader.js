// Generic section header with title, search, and action button
        function SectionHeader({ title, description, searchVal, onSearchChange, onCreateClick, createLabel, customAction }) {
            return (
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-4 mb-6">
                    <div>
                        <h2 className="text-xl font-bold text-slate-100 tracking-tight">{title}</h2>
                        {description && <p className="text-sm text-slate-500 mt-1 leading-relaxed">{description}</p>}
                    </div>
                    <div className="flex flex-wrap items-center gap-2.5 shrink-0">
                        {onSearchChange !== undefined && (
                            <div className="relative">
                                <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">
                                    <Icon name="search" className="w-4 h-4" />
                                </span>
                                <input
                                    type="text"
                                    value={searchVal}
                                    onChange={(e) => onSearchChange(e.target.value)}
                                    placeholder="Search..."
                                    className="bg-slate-900 border border-slate-800 rounded-xl pl-9 pr-4 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 w-44 sm:w-56 transition-all duration-200 shadow-inner"
                                />
                            </div>
                        )}
                        {customAction}
                        {onCreateClick && (
                            <button
                                onClick={onCreateClick}
                                className="bg-indigo-600 hover:bg-indigo-500 text-white font-bold px-4 py-2 rounded-xl text-sm transition-all duration-200 shadow-md shadow-indigo-900/20 flex items-center gap-2 whitespace-nowrap"
                            >
                                <Icon name="plus" className="w-4 h-4" />
                                <span>{createLabel || "Add New"}</span>
                            </button>
                        )}
                    </div>
                </div>
            );
        }

window.SectionHeader = SectionHeader;
