import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity,
  BookOpen,
  Calendar,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  Cpu,
  GraduationCap,
  Grid3x3,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Map,
  Menu,
  MessageSquare,
  Moon,
  ScanFace,
  Search,
  Shield,
  Sun,
  Users,
  Volume2,
} from 'lucide-react';
import { useAuthSession } from '../../providers/AuthProvider';
import { useTheme } from '../../providers/ThemeProvider';
import { CommandPalette } from './CommandPalette';

const NAV_GROUPS = [
  {
    title: 'Operations',
    items: [
      { to: '/dashboard/overview', label: 'Overview', icon: LayoutDashboard, module: 'overview' },
    ],
  },
  {
    title: 'Identity & Access',
    items: [
      { to: '/dashboard/users', label: 'Users Directory', icon: Users, module: 'iam' },
      { to: '/dashboard/face-id', label: 'Face ID', icon: ScanFace, module: 'iam' },
      { to: '/dashboard/roles', label: 'Access Roles', icon: Shield, module: 'iam' },
    ],
  },
  {
    title: 'Physical Security',
    items: [
      { to: '/dashboard/devices', label: 'Edge Devices', icon: Cpu, module: 'infra' },
      { to: '/dashboard/rbac-matrix', label: 'RBAC Matrix', icon: Grid3x3, module: 'infra' },
      { to: '/dashboard/mapping', label: 'Campus Map', icon: Map, module: 'mapping' },
      { to: '/dashboard/access-logs', label: 'Access Logs', icon: Activity, module: 'infra' },
      { to: '/dashboard/sessions', label: 'Active Sessions', icon: KeyRound, module: 'infra' },
    ],
  },
  {
    title: 'Knowledge & Campus',
    items: [
      { to: '/dashboard/documents', label: 'Documents', icon: BookOpen, module: 'rag' },
      { to: '/dashboard/chatbot-logs', label: 'Chatbot Logs', icon: MessageSquare, module: 'rag' },
      { to: '/dashboard/speech-config', label: 'Speech & Acronyms', icon: Volume2, module: 'rag' },
      { to: '/dashboard/academics', label: 'Academics', icon: Calendar, module: 'academics' },
      { to: '/dashboard/appointments', label: 'Appointments', icon: CalendarClock, module: 'academics' },
    ],
  },
];

export function AppShell() {
  const { admin, logout, canAccess } = useAuthSession();
  const { theme, toggleTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCmdOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const initials = (admin?.full_name || 'AD')
    .split(' ')
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  const pathSegments = location.pathname
    .replace(/^\/dashboard\/?/, '')
    .split('/')
    .filter(Boolean);

  const isMapFullBleed = location.pathname.startsWith('/dashboard/mapping');

  return (
    <div className="h-screen overflow-hidden flex bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-slate-900/40 dark:bg-slate-950/75 backdrop-blur-xs lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 lg:static lg:h-full z-40 flex flex-col justify-between bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 transition-all duration-200 shrink-0 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        } ${collapsed ? 'w-[72px]' : 'w-[256px]'}`}
      >
        <div className="flex flex-col min-h-0 flex-1">
          <div className="h-16 px-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2 shrink-0">
            <button
              type="button"
              onClick={() => navigate('/dashboard/overview')}
              className="flex items-center gap-2.5 overflow-hidden text-left"
            >
              <div className="w-9 h-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center shrink-0 shadow-xs">
                <GraduationCap className="w-5 h-5" />
              </div>
              {!collapsed && (
                <div className="min-w-0">
                  <div className="text-sm font-extrabold tracking-tight text-slate-900 dark:text-slate-100 leading-none truncate">
                    Smart Campus
                  </div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-indigo-600 dark:text-indigo-400 mt-1">
                    Admin Console
                  </div>
                </div>
              )}
            </button>
            <button
              type="button"
              onClick={() => setCollapsed((c) => !c)}
              className="hidden lg:inline-flex p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto p-3 space-y-5 scrollbar-thin">
            {NAV_GROUPS.map((group) => {
              const visibleItems = group.items.filter((item) => canAccess(item.module));
              if (visibleItems.length === 0) return null;
              return (
                <div key={group.title}>
                  {!collapsed && (
                    <div className="px-3 mb-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                      {group.title}
                    </div>
                  )}
                  <div className="space-y-0.5">
                    {visibleItems.map((item) => {
                      const IconComp = item.icon;
                      return (
                        <NavLink
                          key={item.to}
                          to={item.to}
                          title={collapsed ? item.label : undefined}
                          className={({ isActive }) =>
                            `flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-semibold transition-colors ${
                              collapsed ? 'justify-center' : ''
                            } ${
                              isActive
                                ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300'
                                : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/70 hover:text-slate-900 dark:hover:text-slate-100'
                            }`
                          }
                        >
                          <IconComp className="w-4 h-4 shrink-0" />
                          {!collapsed && <span className="truncate">{item.label}</span>}
                        </NavLink>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </nav>
        </div>

        {/* Account footer */}
        <div className="p-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/40 shrink-0">
          <div className={`flex items-center gap-2.5 mb-3 ${collapsed ? 'justify-center' : 'px-1'}`}>
            <div className="w-9 h-9 rounded-full bg-indigo-600 text-white font-bold text-xs flex items-center justify-center shrink-0">
              {initials}
            </div>
            {!collapsed && (
              <div className="min-w-0">
                <div className="text-xs font-bold text-slate-900 dark:text-slate-100 truncate">
                  {admin?.full_name}
                </div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 truncate">
                  {(admin?.admin_type || '').replace(/_/g, ' ')}
                </div>
              </div>
            )}
          </div>
          <div className={`flex ${collapsed ? 'flex-col gap-1.5' : 'gap-2'}`}>
            <button
              type="button"
              onClick={toggleTheme}
              title={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 px-2 rounded-xl text-xs font-semibold border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              {theme === 'light' ? <Moon className="w-3.5 h-3.5" /> : <Sun className="w-3.5 h-3.5" />}
              {!collapsed && <span>{theme === 'light' ? 'Dark' : 'Light'}</span>}
            </button>
            <button
              type="button"
              onClick={logout}
              title="Sign Out"
              className="flex-1 flex items-center justify-center gap-1.5 py-2 px-2 rounded-xl text-xs font-semibold border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 hover:text-red-600 dark:hover:text-red-400 hover:border-red-200 dark:hover:border-red-900/50 transition-colors"
            >
              <LogOut className="w-3.5 h-3.5" />
              {!collapsed && <span>Sign Out</span>}
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
        <header className="h-16 shrink-0 bg-white/90 dark:bg-slate-900/90 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 px-4 sm:px-6 flex items-center justify-between gap-4 z-10">
          <div className="flex items-center gap-2.5 min-w-0">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="lg:hidden p-2 rounded-xl border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300"
              aria-label="Open menu"
            >
              <Menu className="w-4 h-4" />
            </button>
            <div className="flex items-center gap-1.5 text-sm min-w-0">
              <span className="text-slate-400 font-medium hidden sm:inline">Console</span>
              {pathSegments.map((seg, i) => (
                <span key={`${seg}-${i}`} className="flex items-center gap-1.5 min-w-0">
                  <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0 hidden sm:inline" />
                  <span
                    className={`truncate capitalize ${
                      i === pathSegments.length - 1
                        ? 'font-bold text-slate-900 dark:text-slate-100'
                        : 'text-slate-500 dark:text-slate-400'
                    }`}
                  >
                    {seg.replace(/-/g, ' ')}
                  </span>
                </span>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setCmdOpen(true)}
              className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-xs text-slate-500 dark:text-slate-400 hover:border-indigo-400 dark:hover:border-indigo-500 transition-colors"
            >
              <Search className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Quick search...</span>
              <kbd className="hidden md:inline-block px-1.5 py-0.5 text-[10px] font-mono font-bold rounded bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-500">
                Ctrl K
              </kbd>
            </button>
          </div>
        </header>

        <main
          className={`flex-1 overflow-y-auto scrollbar-thin ${
            isMapFullBleed ? 'p-0' : 'p-5 sm:p-7'
          }`}
        >
          <div className={isMapFullBleed ? 'h-full w-full' : 'max-w-[1440px] mx-auto'}>
            <Outlet />
          </div>
        </main>
      </div>

      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
    </div>
  );
}
