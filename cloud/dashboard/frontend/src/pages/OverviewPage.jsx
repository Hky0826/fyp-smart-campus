import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Cpu,
  GraduationCap,
  Grid3x3,
  ScanFace,
  ShieldAlert,
  Upload,
  Users,
} from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { useAuthSession } from '../providers/AuthProvider';
import { StatusBadge } from '../components/ui/StatusBadge';

function KpiCard({ title, value, subtitle, icon: IconComp, accent = 'indigo', onClick }) {
  const accentMap = {
    indigo: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-400',
    emerald: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400',
    amber: 'bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400',
    violet: 'bg-violet-50 text-violet-600 dark:bg-violet-500/15 dark:text-violet-400',
  };
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-xs transition-all ${
        onClick ? 'hover:border-indigo-400 dark:hover:border-indigo-500 cursor-pointer' : 'cursor-default'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">{title}</p>
          <p className="text-3xl font-extrabold text-slate-900 dark:text-slate-100 mt-2 tabular-nums tracking-tight">
            {value}
          </p>
        </div>
        <div className={`p-2.5 rounded-xl shrink-0 ${accentMap[accent] || accentMap.indigo}`}>
          <IconComp className="w-5 h-5" />
        </div>
      </div>
      {subtitle && (
        <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mt-3 pt-3 border-t border-slate-100 dark:border-slate-800/80">
          {subtitle}
        </p>
      )}
    </button>
  );
}

export function OverviewPage() {
  const { admin, canAccess } = useAuthSession();
  const navigate = useNavigate();

  const { data: stats } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: () => cloudApi.get('/api/infra/dashboard-stats'),
    refetchInterval: 30_000,
  });

  const { data: exceptions } = useQuery({
    queryKey: ['overview-exceptions'],
    queryFn: () => cloudApi.get('/api/infra/overview-exceptions'),
    refetchInterval: 30_000,
  });

  const totalUsers = stats?.users ?? 0;
  const faceEnrolled = stats?.face_enrolled_users ?? 0;
  const facePct = totalUsers > 0 ? Math.round((faceEnrolled / totalUsers) * 100) : 0;
  const alerts = exceptions?.alerts ?? [];
  const series = exceptions?.auth_series_7d ?? [];
  const maxBar = Math.max(1, ...series.map((d) => d.success + d.failed));

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
            Operations Overview
          </h1>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 tabular-nums">
          <StatusBadge variant="success" dot>
            DB {stats?.db_latency_ms ?? 0}ms
          </StatusBadge>
          <span className="hidden sm:inline">
            {new Date().toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}
          </span>
        </div>
      </div>

      {/* KPI Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {canAccess('iam') && (
          <KpiCard
            title="Total Users"
            value={totalUsers.toLocaleString()}
            subtitle={`${(stats?.active_users ?? 0).toLocaleString()} active · ${(stats?.inactive_users ?? 0).toLocaleString()} inactive`}
            icon={Users}
            accent="indigo"
            onClick={() => navigate('/dashboard/users')}
          />
        )}
        {canAccess('iam') && (
          <KpiCard
            title="Face ID Coverage"
            value={`${facePct}%`}
            subtitle={`${faceEnrolled.toLocaleString()} of ${totalUsers.toLocaleString()} users enrolled`}
            icon={ScanFace}
            accent="emerald"
            onClick={() => navigate('/dashboard/face-id')}
          />
        )}
        {canAccess('infra') && (
          <KpiCard
            title="Edge Devices"
            value={(stats?.devices ?? 0).toLocaleString()}
            subtitle={`${stats?.online_devices ?? 0} online · ${stats?.offline_devices ?? 0} offline`}
            icon={Cpu}
            accent="amber"
            onClick={() => navigate('/dashboard/devices')}
          />
        )}
        {canAccess('rag') ? (
          <KpiCard
            title="Knowledge Docs"
            value={(stats?.documents ?? 0).toLocaleString()}
            subtitle={`${(stats?.courses ?? 0).toLocaleString()} active courses`}
            icon={BookOpen}
            accent="violet"
            onClick={() => navigate('/dashboard/documents')}
          />
        ) : (
          <KpiCard
            title="Active Courses"
            value={(stats?.courses ?? 0).toLocaleString()}
            subtitle="Current academic catalog"
            icon={GraduationCap}
            accent="violet"
            onClick={() => navigate('/dashboard/academics')}
          />
        )}
      </div>

      {/* Main Operations Grid: Exceptions + 7-day Access Chart */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Actionable Alerts */}
        <div className="lg:col-span-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-xs">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400">
                <ShieldAlert className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Actionable Alerts</h2>
              </div>
            </div>
            <StatusBadge variant={alerts.length > 0 ? 'warning' : 'success'}>
              {alerts.length} active
            </StatusBadge>
          </div>

          {alerts.length === 0 ? (
            <div className="py-10 flex flex-col items-center justify-center text-center border border-dashed border-slate-200 dark:border-slate-800 rounded-xl">
              <CheckCircle2 className="w-8 h-8 text-emerald-500 mb-2" />
              <p className="text-sm font-bold text-slate-900 dark:text-slate-100">All systems nominal</p>
            </div>
          ) : (
            <div className="space-y-3">
              {alerts.map((a) => (
                <div
                  key={a.id}
                  className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/50"
                >
                  <div className="flex items-start gap-3 min-w-0">
                    <AlertTriangle
                      className={`w-4 h-4 mt-0.5 shrink-0 ${
                        a.severity === 'critical'
                          ? 'text-red-600 dark:text-red-400'
                          : a.severity === 'warning'
                            ? 'text-amber-600 dark:text-amber-400'
                            : 'text-indigo-600 dark:text-indigo-400'
                      }`}
                    />
                    <div className="min-w-0">
                      <div className="text-sm font-bold text-slate-900 dark:text-slate-100">{a.title}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{a.description}</div>
                    </div>
                  </div>
                  {a.action_path && (
                    <button
                      type="button"
                      onClick={() => navigate(a.action_path)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-indigo-600 dark:text-indigo-400 hover:border-indigo-400 shrink-0 self-start sm:self-center"
                    >
                      <span>{a.action_label}</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 7-Day Access Control Activity */}
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
                  <Activity className="w-4 h-4" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">7-Day Gate Activity</h2>
                  <p className="text-xs text-slate-500 tabular-nums">
                    {stats?.auth_attempts_24h ?? 0} attempts · {stats?.auth_failures_24h ?? 0} failed (24h)
                  </p>
                </div>
              </div>
              {canAccess('infra') && (
                <button
                  type="button"
                  onClick={() => navigate('/dashboard/access-logs')}
                  className="text-xs font-bold text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  All Logs
                </button>
              )}
            </div>

            {series.length > 0 ? (
              <div className="mt-4">
                <div className="grid grid-cols-7 gap-2 items-end h-40 pt-4">
                  {series.map((d) => {
                    const total = d.success + d.failed;
                    const hSuccess = Math.round((d.success / maxBar) * 100);
                    const hFailed = Math.round((d.failed / maxBar) * 100);
                    return (
                      <div key={d.date} className="flex flex-col items-center gap-1.5 h-full justify-end">
                        <div className="w-full max-w-[28px] flex flex-col justify-end h-full gap-0.5" title={`${d.label}: ${d.success} granted, ${d.failed} denied`}>
                          {d.failed > 0 && (
                            <div
                              className="w-full rounded-t bg-red-400 dark:bg-red-500/80 transition-all"
                              style={{ height: `${Math.max(6, hFailed)}%` }}
                            />
                          )}
                          <div
                            className={`w-full ${d.failed > 0 ? 'rounded-b' : 'rounded'} bg-indigo-500 dark:bg-indigo-400 transition-all`}
                            style={{ height: `${total === 0 ? 4 : Math.max(8, hSuccess)}%`, opacity: total === 0 ? 0.2 : 1 }}
                          />
                        </div>
                        <span className="text-[10px] font-medium text-slate-500 tabular-nums">{d.label.split(' ')[1]}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="flex items-center gap-4 mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 text-xs text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-xs bg-indigo-500" /> Granted
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-xs bg-red-400" /> Denied / Spoof
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500 py-8 text-center">Activity metrics available for system administrators.</p>
            )}
          </div>

          <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500">
            <span>Signed in as <strong>{admin?.admin_type?.replace(/_/g, ' ')}</strong></span>
            <span className="tabular-nums">{stats?.active_sessions ?? 0} active sessions</span>
          </div>
        </div>
      </div>

      {/* Quick Operational Workflows */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-xs">
        <h2 className="text-sm font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3.5">
          Quick Workflows
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {canAccess('iam') && (
            <button
              type="button"
              onClick={() => navigate('/dashboard/users?import=1')}
              className="flex items-center gap-3 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 hover:border-indigo-400 dark:hover:border-indigo-500 bg-slate-50/60 dark:bg-slate-950/40 text-left transition-colors"
            >
              <div className="p-2 rounded-lg bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400">
                <Upload className="w-4 h-4" />
              </div>
              <div className="text-sm font-bold text-slate-900 dark:text-slate-100">Bulk Import CSV</div>
            </button>
          )}
          {canAccess('infra') && (
            <button
              type="button"
              onClick={() => navigate('/dashboard/rbac-matrix')}
              className="flex items-center gap-3 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 hover:border-indigo-400 dark:hover:border-indigo-500 bg-slate-50/60 dark:bg-slate-950/40 text-left transition-colors"
            >
              <div className="p-2 rounded-lg bg-emerald-50 dark:bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                <Grid3x3 className="w-4 h-4" />
              </div>
              <div className="text-sm font-bold text-slate-900 dark:text-slate-100">RBAC Policy Matrix</div>
            </button>
          )}
          {canAccess('rag') && (
            <button
              type="button"
              onClick={() => navigate('/dashboard/documents')}
              className="flex items-center gap-3 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 hover:border-indigo-400 dark:hover:border-indigo-500 bg-slate-50/60 dark:bg-slate-950/40 text-left transition-colors"
            >
              <div className="p-2 rounded-lg bg-violet-50 dark:bg-violet-500/15 text-violet-600 dark:text-violet-400">
                <BookOpen className="w-4 h-4" />
              </div>
              <div className="text-sm font-bold text-slate-900 dark:text-slate-100">Upload Knowledge Doc</div>
            </button>
          )}
          {canAccess('academics') && (
            <button
              type="button"
              onClick={() => navigate('/dashboard/appointments')}
              className="flex items-center gap-3 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 hover:border-indigo-400 dark:hover:border-indigo-500 bg-slate-50/60 dark:bg-slate-950/40 text-left transition-colors"
            >
              <div className="p-2 rounded-lg bg-amber-50 dark:bg-amber-500/15 text-amber-600 dark:text-amber-400">
                <Activity className="w-4 h-4" />
              </div>
              <div className="text-sm font-bold text-slate-900 dark:text-slate-100">Appointments</div>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
