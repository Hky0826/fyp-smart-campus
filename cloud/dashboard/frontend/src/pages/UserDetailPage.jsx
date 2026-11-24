import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  DoorOpen,
  Edit3,
  KeyRound,
  Lock,
  ScanFace,
  Trash2,
  User,
} from 'lucide-react';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { UserFormModal } from '../components/users/UserFormModal';
import { FaceEnrollModal } from '../components/users/FaceEnrollModal';

function InfoTile({ label, value, mono = false }) {
  return (
    <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/40">
      <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-sm text-slate-900 dark:text-slate-100 mt-1 break-words ${mono ? 'font-mono' : 'font-semibold'}`}>
        {value !== null && value !== undefined && value !== '' ? value : <span className="text-slate-400 italic font-normal">Not set</span>}
      </div>
    </div>
  );
}

export function UserDetailPage() {
  const { userId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [tab, setTab] = useState('profile');
  const [editOpen, setEditOpen] = useState(false);
  const [faceOpen, setFaceOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data: detail, isLoading, error } = useQuery({
    queryKey: ['user-detail', userId],
    queryFn: () => cloudApi.get(`/api/iam/users/${userId}/detail`),
  });

  const { data: effectiveAccess } = useQuery({
    queryKey: ['user-effective-access', userId],
    queryFn: () => cloudApi.get(`/api/iam/users/${userId}/effective-access`),
    enabled: Boolean(userId),
  });

  const { data: refs } = useQuery({
    queryKey: ['iam-refs'],
    queryFn: async () => {
      const [roles, faculties, programmes, departments, nodes] = await Promise.all([
        cloudApi.get('/api/iam/roles'),
        cloudApi.get('/api/refs/faculties'),
        cloudApi.get('/api/refs/programmes'),
        cloudApi.get('/api/refs/departments'),
        cloudApi.get('/api/refs/nodes'),
      ]);
      return { roles, faculties, programmes, departments, nodes };
    },
    staleTime: 60_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['user-detail', userId] });
    queryClient.invalidateQueries({ queryKey: ['user-effective-access', userId] });
    queryClient.invalidateQueries({ queryKey: ['users-paginated'] });
  };

  if (isLoading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center text-slate-500">
        <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mb-3" />
        <span className="text-sm font-medium">Loading user workspace...</span>
      </div>
    );
  }

  if (error || !detail?.user) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-10 text-center">
        <p className="text-base font-bold text-slate-900 dark:text-slate-100">User not found</p>
        <p className="text-sm text-slate-500 mt-1">{error?.message || 'This account may have been deleted.'}</p>
        <button
          type="button"
          onClick={() => navigate('/dashboard/users')}
          className="mt-4 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 text-white"
        >
          Back to Users
        </button>
      </div>
    );
  }

  const u = detail.user;
  const biometrics = detail.biometrics || { enrolled: false, poses: [], embedding_count: 0 };
  const logs = detail.recent_auth_logs || [];
  const sessions = detail.active_sessions || [];
  const enrollments = detail.enrollments || [];
  const appointments = detail.appointments || [];

  const handleToggleActive = async () => {
    try {
      await cloudApi.post(`/api/iam/users/${u.user_id}/toggle-active`, {});
      toast.success(`User ${u.is_active ? 'deactivated' : 'activated'}.`);
      invalidate();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleRevokeSession = async (sessionId) => {
    try {
      await cloudApi.delete(`/api/infra/jwt-sessions/${sessionId}`);
      toast.success('Session revoked.');
      invalidate();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDelete = async () => {
    try {
      await cloudApi.delete(`/api/iam/users/${u.user_id}`);
      toast.success(`Deleted ${u.full_name}.`);
      navigate('/dashboard/users');
    } catch (err) {
      toast.error(err.message);
    }
  };

  const tabs = [
    { id: 'profile', label: 'Profile', icon: User },
    { id: 'access', label: 'Effective Door Access', icon: DoorOpen, count: effectiveAccess?.allowed_devices },
    { id: 'biometrics', label: 'Face ID', icon: ScanFace, count: biometrics.poses?.length || 0 },
    { id: 'activity', label: 'Activity & Sessions', icon: Activity, count: logs.length + sessions.length },
    { id: 'academics', label: 'Academics', icon: BookOpen, count: enrollments.length + appointments.length },
  ];

  const initials = ((u.given_name?.[0] || '') + (u.family_name?.[0] || '')).toUpperCase() || 'U';

  return (
    <div className="space-y-6">
      <button
        type="button"
        onClick={() => navigate('/dashboard/users')}
        className="inline-flex items-center gap-1.5 text-xs font-bold text-slate-500 hover:text-indigo-600 dark:hover:text-indigo-400"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Back to Users Directory
      </button>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 shadow-xs">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <div className="w-14 h-14 rounded-2xl bg-indigo-600 text-white font-extrabold text-lg flex items-center justify-center shrink-0 shadow-xs">
              {initials}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2.5 flex-wrap">
                <h1 className="text-xl font-extrabold text-slate-900 dark:text-slate-100 truncate">
                  {u.full_name}
                </h1>
                <span className="text-xs font-mono px-2 py-0.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-500 tabular-nums">
                  #{u.user_id}
                </span>
                <StatusBadge variant={u.is_active ? 'success' : 'danger'} dot>
                  {u.is_active ? 'Active' : 'Deactivated'}
                </StatusBadge>
              </div>
              <p className="text-sm font-mono text-slate-500 mt-0.5 truncate">{u.email}</p>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {(u.roles || []).map((r) => (
                  <StatusBadge key={r.role_id} variant="info">
                    {r.role_name}
                  </StatusBadge>
                ))}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setFaceOpen(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              <ScanFace className="w-3.5 h-3.5" /> Manage Face ID
            </button>
            <button
              type="button"
              onClick={() => setEditOpen(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 hover:bg-slate-50"
            >
              <Edit3 className="w-3.5 h-3.5" /> Edit
            </button>
            <button
              type="button"
              onClick={handleToggleActive}
              className="px-3.5 py-2 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 hover:bg-slate-50"
            >
              {u.is_active ? 'Deactivate' : 'Activate'}
            </button>
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400"
            >
              <Trash2 className="w-3.5 h-3.5" /> Delete
            </button>
          </div>
        </div>

        <div className="flex gap-1 mt-6 -mb-6 border-t border-slate-100 dark:border-slate-800 pt-2 overflow-x-auto">
          {tabs.map((t) => {
            const IconComp = t.icon;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`px-3.5 py-2.5 text-xs font-bold border-b-2 transition-colors whitespace-nowrap flex items-center gap-1.5 ${
                  tab === t.id
                    ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 dark:border-indigo-400'
                    : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <IconComp className="w-3.5 h-3.5" />
                <span>{t.label}</span>
                {t.count !== undefined && (
                  <span className="px-1.5 py-0.2 rounded-md bg-slate-100 dark:bg-slate-800 text-[10px] font-mono tabular-nums">
                    {t.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {tab === 'profile' && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-6">
          <div>
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Core Identity</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              <InfoTile label="Given Name" value={u.given_name} />
              <InfoTile label="Family Name" value={u.family_name} />
              <InfoTile label="Email" value={u.email} mono />
              <InfoTile label="Last Known Location" value={u.location_label} />
              <InfoTile label="Enrolled At" value={formatDateTime(u.enrolled_at)} />
              <InfoTile label="Last Seen" value={formatDateTime(u.last_seen)} />
            </div>
          </div>

          {u.student && (
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400 mb-3">Student Record</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <InfoTile label="Student ID" value={u.student.student_id} mono />
                <InfoTile label="Intake" value={u.student.intake} mono />
                <InfoTile label="Programme" value={u.student.program || u.student.programme_id} />
                <InfoTile label="Faculty" value={u.student.faculty || u.student.faculty_id} />
                <InfoTile label="Status" value={u.student.enrollment_status} />
                <InfoTile label="Enrolled Since" value={u.student.enrolled_since} />
              </div>
            </div>
          )}

          {u.lecturer && (
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-violet-600 dark:text-violet-400 mb-3">Lecturer Record</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <InfoTile label="Lecturer ID" value={u.lecturer.lecturer_id} mono />
                <InfoTile label="Position" value={u.lecturer.position} />
                <InfoTile label="Department" value={u.lecturer.department || u.lecturer.department_id} />
                <InfoTile label="Faculty" value={u.lecturer.faculty || u.lecturer.faculty_id} />
              </div>
            </div>
          )}

          {u.staff && (
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400 mb-3">Staff Record</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <InfoTile label="Staff ID" value={u.staff.staff_id} mono />
                <InfoTile label="Position" value={u.staff.position} />
                <InfoTile label="Department" value={u.staff.department || u.staff.department_id} />
              </div>
            </div>
          )}

          {u.visitor && (
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400 mb-3">Visitor Pass</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <InfoTile label="Visitor ID" value={u.visitor.visitor_id} mono />
                <InfoTile label="ID Number" value={u.visitor.id_number} mono />
                <InfoTile label="Organization" value={u.visitor.organization} />
                <InfoTile label="Purpose" value={u.visitor.visit_purpose} />
                <InfoTile label="Access Expiry" value={formatDateTime(u.visitor.access_expiry)} />
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'access' && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Effective Physical Door Access</h2>
              <p className="text-xs text-slate-500">
                Computed live from roles, Device RBAC overrides, Node RBAC inheritance, Face ID status, and pass validity.
              </p>
            </div>
            <StatusBadge variant={(effectiveAccess?.allowed_devices ?? 0) > 0 ? 'success' : 'warning'}>
              {effectiveAccess?.allowed_devices ?? 0} / {effectiveAccess?.total_devices ?? 0} doors unlockable
            </StatusBadge>
          </div>

          {(effectiveAccess?.blockers?.length ?? 0) > 0 && (
            <div className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 flex items-start gap-2.5 text-xs text-amber-800 dark:text-amber-300">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <strong>Access Blockers:</strong> {effectiveAccess.blockers.join(' · ')}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {(effectiveAccess?.doors || []).map((door) => (
              <div
                key={door.device_id}
                onClick={() => navigate(`/dashboard/devices/${door.device_id}`)}
                className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 hover:border-indigo-400 cursor-pointer flex items-start justify-between gap-3 transition-colors"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {door.can_unlock ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
                    ) : (
                      <Lock className="w-4 h-4 text-slate-400 shrink-0" />
                    )}
                    <span className="text-sm font-bold text-slate-900 dark:text-slate-100 truncate">
                      {door.device_name}
                    </span>
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    {door.building_name || 'Campus'} {door.floor_level ? `· ${door.floor_level}` : ''} · {door.room_label}
                  </div>
                  <div className="text-xs text-slate-600 dark:text-slate-400 mt-1.5">{door.reason}</div>
                </div>
                <StatusBadge variant={door.can_unlock ? 'success' : 'neutral'}>
                  {door.can_unlock ? 'Allowed' : 'Blocked'}
                </StatusBadge>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'biometrics' && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Biometric Templates</h2>
              <p className="text-xs text-slate-500">{biometrics.embedding_count} stored embeddings across {biometrics.poses?.length || 0} pose(s)</p>
            </div>
            <button
              type="button"
              onClick={() => setFaceOpen(true)}
              className="px-3.5 py-2 rounded-xl text-xs font-bold bg-indigo-600 text-white"
            >
              + Add / Update Pose
            </button>
          </div>
          {biometrics.poses?.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {biometrics.poses.map((p) => (
                <div key={p.pose} className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/40">
                  <div className="text-sm font-mono font-bold text-slate-900 dark:text-slate-100">{p.pose}</div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {p.models.map((m) => (
                      <StatusBadge key={m} variant="info">{m}</StatusBadge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500 py-8 text-center border border-dashed border-slate-200 dark:border-slate-800 rounded-xl">
              No facial templates enrolled yet.
            </p>
          )}
        </div>
      )}

      {tab === 'activity' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-3">
            <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Recent Gate & Door Events</h2>
            {logs.length === 0 ? (
              <p className="text-sm text-slate-500 py-6">No physical access events recorded.</p>
            ) : (
              logs.map((l) => (
                <div key={l.log_id} className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-bold text-slate-900 dark:text-slate-100">
                      {l.device_name} {l.node_label && <span className="font-normal text-slate-500">· {l.node_label}</span>}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      {formatDateTime(l.timestamp)}
                      {l.confidence_score != null && ` · Score ${(l.confidence_score * 100).toFixed(1)}%`}
                    </div>
                    {l.reason && <div className="text-xs text-slate-600 dark:text-slate-400 mt-1">{l.reason}</div>}
                  </div>
                  <StatusBadge variant={l.auth_status === 'SUCCESS' ? 'success' : 'danger'}>
                    {l.auth_status}
                  </StatusBadge>
                </div>
              ))
            )}
          </div>

          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-3">
            <h2 className="text-base font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <KeyRound className="w-4 h-4 text-indigo-500" /> Active Sessions
            </h2>
            {sessions.length === 0 ? (
              <p className="text-sm text-slate-500 py-6">No active JWT sessions.</p>
            ) : (
              sessions.map((s) => (
                <div key={s.session_id} className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-xs font-bold text-slate-900 dark:text-slate-100">{s.principal_type}</div>
                    <div className="text-[11px] text-slate-500">Expires {formatDateTime(s.expires_at)}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRevokeSession(s.session_id)}
                    className="px-2.5 py-1 rounded-lg text-xs font-bold text-red-600 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20"
                  >
                    Revoke
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {tab === 'academics' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-3">
            <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Course Enrollments</h2>
            {enrollments.length === 0 ? (
              <p className="text-sm text-slate-500 py-6">No course enrollments.</p>
            ) : (
              enrollments.map((e) => (
                <div key={e.enrollment_id} className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-bold text-slate-900 dark:text-slate-100">
                      <span className="font-mono text-indigo-600 dark:text-indigo-400 mr-1.5">{e.course_code}</span>
                      {e.course_name}
                    </div>
                    <div className="text-xs text-slate-500">{e.academic_year} · Semester {e.semester}</div>
                  </div>
                  <StatusBadge variant="info">{e.status}</StatusBadge>
                </div>
              ))
            )}
          </div>

          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-3">
            <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Appointments</h2>
            {appointments.length === 0 ? (
              <p className="text-sm text-slate-500 py-6">No scheduled appointments.</p>
            ) : (
              appointments.map((a) => (
                <div key={a.appointment_id} className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{a.counterpart}</span>
                    <StatusBadge variant="neutral">{a.status}</StatusBadge>
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    {formatDateTime(a.scheduled_at)} ({a.duration_minutes}m) {a.location ? `· ${a.location}` : ''}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      <UserFormModal open={editOpen} user={u} refs={refs} onClose={() => setEditOpen(false)} onSaved={invalidate} />
      <FaceEnrollModal open={faceOpen} user={u} onClose={() => setFaceOpen(false)} onEnrolled={invalidate} />
      <ConfirmDialog
        open={confirmDelete}
        title="Delete User Account"
        message={`Permanently delete ${u.full_name} (${u.email})? This cannot be undone.`}
        confirmLabel="Delete User"
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
