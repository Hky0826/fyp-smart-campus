import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  BookOpen,
  Calendar,
  CalendarClock,
  Cpu,
  Grid3x3,
  LayoutDashboard,
  Map,
  ScanFace,
  Search,
  Shield,
  Upload,
  User,
  Users,
  X,
} from 'lucide-react';
import { cloudApi } from '../../lib/cloudApi';
import { useAuthSession } from '../../providers/AuthProvider';

const NAV_COMMANDS = [
  { label: 'Overview & Telemetry', path: '/dashboard/overview', module: 'overview', icon: LayoutDashboard, group: 'Pages' },
  { label: 'Users Directory', path: '/dashboard/users', module: 'iam', icon: Users, group: 'Pages' },
  { label: 'Face ID Enrollment', path: '/dashboard/face-id', module: 'iam', icon: ScanFace, group: 'Pages' },
  { label: 'Access Roles', path: '/dashboard/roles', module: 'iam', icon: Shield, group: 'Pages' },
  { label: 'Edge Devices', path: '/dashboard/devices', module: 'infra', icon: Cpu, group: 'Pages' },
  { label: 'Visual RBAC Matrix', path: '/dashboard/rbac-matrix', module: 'infra', icon: Grid3x3, group: 'Pages' },
  { label: 'Access Logs', path: '/dashboard/access-logs', module: 'infra', icon: Activity, group: 'Pages' },
  { label: 'Knowledge Base Documents', path: '/dashboard/documents', module: 'rag', icon: BookOpen, group: 'Pages' },
  { label: 'Academics & Scheduling', path: '/dashboard/academics', module: 'academics', icon: Calendar, group: 'Pages' },
  { label: 'Appointments', path: '/dashboard/appointments', module: 'academics', icon: CalendarClock, group: 'Pages' },
  { label: 'Campus Map Editor', path: '/dashboard/mapping', module: 'mapping', icon: Map, group: 'Pages' },
  { label: 'Bulk Import Users (CSV)', path: '/dashboard/users?import=1', module: 'iam', icon: Upload, group: 'Actions' },
];

export function CommandPalette({ open, onClose }) {
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const inputRef = useRef(null);
  const navigate = useNavigate();
  const { canAccess } = useAuthSession();

  useEffect(() => {
    if (!open) {
      setQuery('');
      setDebounced('');
      return;
    }
    setTimeout(() => inputRef.current?.focus(), 20);
  }, [open]);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const { data: userResults } = useQuery({
    queryKey: ['cmdk-users', debounced],
    queryFn: () => cloudApi.get('/api/iam/users/paginated', { q: debounced, page: 1, page_size: 5 }),
    enabled: open && debounced.length >= 2 && canAccess('iam'),
    staleTime: 15_000,
  });

  if (!open) return null;

  const qLower = query.toLowerCase();
  const filteredNav = NAV_COMMANDS.filter(
    (c) => canAccess(c.module) && (!qLower || c.label.toLowerCase().includes(qLower))
  );

  const go = (path) => {
    onClose();
    navigate(path);
  };

  return (
    <div
      className="fixed inset-0 z-[95] flex items-start justify-center pt-[12vh] bg-slate-900/45 dark:bg-slate-950/75 backdrop-blur-xs p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-xl rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-slate-200 dark:border-slate-800">
          <Search className="w-4 h-4 text-slate-400 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Jump to page, action, or search users by name, email, or ID..."
            className="flex-1 bg-transparent text-sm text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none"
          />
          <button
            type="button"
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 rounded-lg"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto p-2 space-y-3 scrollbar-thin">
          {userResults?.items?.length > 0 && (
            <div>
              <div className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                Matching Users
              </div>
              {userResults.items.map((u) => (
                <button
                  key={u.user_id}
                  type="button"
                  onClick={() => go(`/dashboard/users/${u.user_id}`)}
                  className="w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-xl text-left hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 flex items-center justify-center shrink-0">
                      <User className="w-3.5 h-3.5" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate">
                        {u.full_name}
                      </div>
                      <div className="text-xs font-mono text-slate-500 truncate">{u.email}</div>
                    </div>
                  </div>
                  <span className="text-[11px] font-mono text-slate-400 shrink-0">#{u.user_id}</span>
                </button>
              ))}
            </div>
          )}

          {filteredNav.length > 0 && (
            <div>
              <div className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                Navigation & Actions
              </div>
              {filteredNav.map((c) => {
                const IconComp = c.icon;
                return (
                  <button
                    key={c.path}
                    type="button"
                    onClick={() => go(c.path)}
                    className="w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-xl text-left hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                  >
                    <div className="flex items-center gap-2.5">
                      <IconComp className="w-4 h-4 text-slate-500 dark:text-slate-400" />
                      <span className="text-sm font-medium text-slate-800 dark:text-slate-200">{c.label}</span>
                    </div>
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      {c.group}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {filteredNav.length === 0 && !(userResults?.items?.length > 0) && (
            <div className="py-10 text-center text-sm text-slate-500">
              No matching pages or users found.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
