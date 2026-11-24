import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { cloudApi } from '../../lib/cloudApi';
import { useToast } from '../../providers/ToastProvider';

const inputCls =
  'w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3.5 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20';
const labelCls = 'block text-xs font-bold uppercase tracking-wider text-slate-600 dark:text-slate-400 mb-1.5';

export function UserFormModal({ open, user, refs, onClose, onSaved }) {
  const toast = useToast();
  const isEdit = Boolean(user);

  const [givenName, setGivenName] = useState('');
  const [familyName, setFamilyName] = useState('');
  const [email, setEmail] = useState('');
  const [roleId, setRoleId] = useState('');
  const [isActive, setIsActive] = useState(true);

  const [programmeId, setProgrammeId] = useState('');
  const [facultyId, setFacultyId] = useState('');
  const [intake, setIntake] = useState('202407');
  const [enrolledSince, setEnrolledSince] = useState(new Date().toISOString().slice(0, 10));

  const [departmentId, setDepartmentId] = useState('');
  const [position, setPosition] = useState('');
  const [staffType, setStaffType] = useState('ADMINISTRATIVE');
  const [officeNodeId, setOfficeNodeId] = useState('');

  const [idNumber, setIdNumber] = useState('');
  const [organization, setOrganization] = useState('');
  const [visitPurpose, setVisitPurpose] = useState('');
  const [accessExpiry, setAccessExpiry] = useState(
    new Date(Date.now() + 86_400_000).toISOString().slice(0, 16)
  );

  const [adminType, setAdminType] = useState('SYSTEM_ADMIN');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (user) {
      setGivenName(user.given_name || '');
      setFamilyName(user.family_name || '');
      setEmail(user.email || '');
      setRoleId(String(user.roles?.[0]?.role_id || ''));
      setIsActive(Boolean(user.is_active));
      setProgrammeId(user.student?.programme_id || '');
      setFacultyId(user.student?.faculty_id || user.lecturer?.faculty_id || '');
      setIntake(String(user.student?.intake || '202407'));
      setEnrolledSince(user.student?.enrolled_since || new Date().toISOString().slice(0, 10));
      setDepartmentId(user.staff?.department_id || user.lecturer?.department_id || user.admin?.department_id || '');
      setPosition(user.lecturer?.position || user.staff?.position || '');
      setOfficeNodeId(String(user.lecturer?.office_node_id || user.staff?.office_node_id || user.admin?.office_node_id || ''));
      setIdNumber(user.visitor?.id_number || '');
      setOrganization(user.visitor?.organization || '');
      setVisitPurpose(user.visitor?.visit_purpose || '');
      setAccessExpiry(
        user.visitor?.access_expiry
          ? new Date(user.visitor.access_expiry).toISOString().slice(0, 16)
          : new Date(Date.now() + 86_400_000).toISOString().slice(0, 16)
      );
      setAdminType(user.admin?.admin_type || 'SYSTEM_ADMIN');
      setPassword('');
    } else {
      setGivenName('');
      setFamilyName('');
      setEmail('');
      setRoleId('');
      setIsActive(true);
      setProgrammeId('');
      setFacultyId('');
      setIntake('202407');
      setEnrolledSince(new Date().toISOString().slice(0, 10));
      setDepartmentId('');
      setPosition('');
      setStaffType('ADMINISTRATIVE');
      setOfficeNodeId('');
      setIdNumber('');
      setOrganization('');
      setVisitPurpose('');
      setPassword('');
    }
  }, [open, user]);

  useEffect(() => {
    if (isEdit || !open) return;
    const g = givenName.toLowerCase().replace(/[^a-z0-9]/g, '');
    const f = familyName.toLowerCase().replace(/[^a-z0-9]/g, '');
    if (g || f) setEmail(`${g}.${f}@qiu.edu.my`);
  }, [givenName, familyName, isEdit, open]);

  if (!open) return null;

  const selectedRole = (refs?.roles || []).find((r) => String(r.role_id) === String(roleId));
  const roleName = selectedRole?.role_name || '';

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const userPayload = {
        given_name: givenName.trim(),
        family_name: familyName.trim(),
        email: email.trim(),
        role_id: parseInt(roleId, 10),
        is_active: isActive,
      };

      if (isEdit) {
        await cloudApi.put(`/api/iam/users/${user.user_id}`, userPayload);
        toast.success(`Updated ${givenName} ${familyName}.`);
      } else if (roleName === 'STUDENT') {
        await cloudApi.post('/api/iam/students', {
          programme_id: programmeId,
          faculty_id: facultyId,
          intake: parseInt(intake, 10),
          enrolled_since: enrolledSince,
          user: userPayload,
        });
        toast.success(`Registered student ${givenName} ${familyName}.`);
      } else if (roleName === 'LECTURER') {
        await cloudApi.post('/api/iam/lecturers', {
          department_id: departmentId,
          faculty_id: facultyId,
          position: position || 'Lecturer',
          office_node_id: officeNodeId ? parseInt(officeNodeId, 10) : null,
          user: userPayload,
        });
        toast.success(`Registered lecturer ${givenName} ${familyName}.`);
      } else if (roleName === 'STAFF') {
        await cloudApi.post('/api/iam/staff', {
          department_id: departmentId,
          position: position || 'Staff',
          staff_type: staffType,
          office_node_id: officeNodeId ? parseInt(officeNodeId, 10) : null,
          user: userPayload,
        });
        toast.success(`Registered staff ${givenName} ${familyName}.`);
      } else if (roleName === 'VISITOR') {
        await cloudApi.post('/api/iam/visitors', {
          id_number: idNumber.trim(),
          organization: organization.trim() || null,
          visit_purpose: visitPurpose.trim() || null,
          access_expiry: new Date(accessExpiry).toISOString(),
          registered_by: 1,
          user: userPayload,
        });
        toast.success(`Registered visitor ${givenName} ${familyName}.`);
      } else if (roleName === 'ADMIN') {
        await cloudApi.post('/api/iam/admins', {
          admin_type: adminType,
          department_id: departmentId,
          office_node_id: officeNodeId ? parseInt(officeNodeId, 10) : null,
          password,
          user: userPayload,
        });
        toast.success(`Registered administrator ${givenName} ${familyName}.`);
      } else {
        await cloudApi.post('/api/iam/users', userPayload);
        toast.success(`Registered user ${givenName} ${familyName}.`);
      }

      onSaved?.();
      onClose();
    } catch (err) {
      toast.error(err.message || 'Failed to save user.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-900/50 dark:bg-slate-950/75 backdrop-blur-xs p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-2xl max-h-[88vh] flex flex-col rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">
            {isEdit ? `Edit User — ${user.full_name}` : 'Register New Campus User'}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-4 scrollbar-thin">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>Given Name *</label>
              <input type="text" required value={givenName} onChange={(e) => setGivenName(e.target.value)} className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>Family Name *</label>
              <input type="text" required value={familyName} onChange={(e) => setFamilyName(e.target.value)} className={inputCls} />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>Email Address *</label>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>Role *</label>
              <select required value={roleId} onChange={(e) => setRoleId(e.target.value)} className={inputCls}>
                <option value="">Select role...</option>
                {(refs?.roles || []).map((r) => (
                  <option key={r.role_id} value={r.role_id}>
                    {r.role_name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {!isEdit && roleName === 'STUDENT' && (
            <div className="pt-4 border-t border-slate-200 dark:border-slate-800 space-y-4">
              <div className="text-xs font-extrabold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                Student Profile
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>Programme *</label>
                  <select
                    required
                    value={programmeId}
                    onChange={(e) => {
                      const val = e.target.value;
                      setProgrammeId(val);
                      const p = (refs?.programmes || []).find((x) => x.programme_id === val);
                      if (p?.faculty_id) setFacultyId(p.faculty_id);
                    }}
                    className={inputCls}
                  >
                    <option value="">Select programme...</option>
                    {(refs?.programmes || []).map((p) => (
                      <option key={p.programme_id} value={p.programme_id}>
                        {p.programme_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Faculty *</label>
                  <select required value={facultyId} onChange={(e) => setFacultyId(e.target.value)} className={inputCls}>
                    <option value="">Select faculty...</option>
                    {(refs?.faculties || []).map((f) => (
                      <option key={f.faculty_id} value={f.faculty_id}>
                        {f.faculty_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Intake (6 digits) *</label>
                  <input
                    type="text"
                    required
                    maxLength={6}
                    pattern="\d{6}"
                    value={intake}
                    onChange={(e) => setIntake(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>Enrolled Since *</label>
                  <input type="date" required value={enrolledSince} onChange={(e) => setEnrolledSince(e.target.value)} className={inputCls} />
                </div>
              </div>
            </div>
          )}

          {!isEdit && (roleName === 'LECTURER' || roleName === 'STAFF' || roleName === 'ADMIN') && (
            <div className="pt-4 border-t border-slate-200 dark:border-slate-800 space-y-4">
              <div className="text-xs font-extrabold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                {roleName} Profile
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>Department *</label>
                  <select required value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} className={inputCls}>
                    <option value="">Select department...</option>
                    {(refs?.departments || []).map((d) => (
                      <option key={d.department_id} value={d.department_id}>
                        {d.department_name}
                      </option>
                    ))}
                  </select>
                </div>
                {roleName === 'LECTURER' && (
                  <div>
                    <label className={labelCls}>Faculty *</label>
                    <select required value={facultyId} onChange={(e) => setFacultyId(e.target.value)} className={inputCls}>
                      <option value="">Select faculty...</option>
                      {(refs?.faculties || []).map((f) => (
                        <option key={f.faculty_id} value={f.faculty_id}>
                          {f.faculty_name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {roleName === 'ADMIN' ? (
                  <>
                    <div>
                      <label className={labelCls}>Admin Privilege *</label>
                      <select value={adminType} onChange={(e) => setAdminType(e.target.value)} className={inputCls}>
                        <option value="SYSTEM_ADMIN">SYSTEM_ADMIN</option>
                        <option value="CONTENT_ADMIN">CONTENT_ADMIN</option>
                        <option value="SUPER_ADMIN">SUPER_ADMIN</option>
                      </select>
                    </div>
                    <div className="sm:col-span-2">
                      <label className={labelCls}>Initial Password *</label>
                      <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className={inputCls} />
                    </div>
                  </>
                ) : (
                  <div>
                    <label className={labelCls}>Position Title *</label>
                    <input type="text" required value={position} onChange={(e) => setPosition(e.target.value)} className={inputCls} />
                  </div>
                )}
                <div>
                  <label className={labelCls}>Office Room (Optional)</label>
                  <select value={officeNodeId} onChange={(e) => setOfficeNodeId(e.target.value)} className={inputCls}>
                    <option value="">No assigned office</option>
                    {(refs?.nodes || [])
                      .filter((n) => n.node_type === 'OFFICE')
                      .map((n) => (
                        <option key={n.node_id} value={n.node_id}>
                          {n.room_label || `Node #${n.node_id}`}
                        </option>
                      ))}
                  </select>
                </div>
              </div>
            </div>
          )}

          {!isEdit && roleName === 'VISITOR' && (
            <div className="pt-4 border-t border-slate-200 dark:border-slate-800 space-y-4">
              <div className="text-xs font-extrabold uppercase tracking-wider text-amber-600 dark:text-amber-400">
                Visitor Pass
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>ID / Passport Number *</label>
                  <input type="text" required value={idNumber} onChange={(e) => setIdNumber(e.target.value)} className={inputCls} />
                </div>
                <div>
                  <label className={labelCls}>Organization</label>
                  <input type="text" value={organization} onChange={(e) => setOrganization(e.target.value)} className={inputCls} />
                </div>
                <div>
                  <label className={labelCls}>Access Expiry *</label>
                  <input type="datetime-local" required value={accessExpiry} onChange={(e) => setAccessExpiry(e.target.value)} className={inputCls} />
                </div>
                <div>
                  <label className={labelCls}>Visit Purpose</label>
                  <input type="text" value={visitPurpose} onChange={(e) => setVisitPurpose(e.target.value)} className={inputCls} />
                </div>
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-slate-200 dark:border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-sm font-semibold text-slate-700 dark:text-slate-300 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-5 py-2 rounded-xl text-sm font-bold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
            >
              {submitting ? 'Saving...' : isEdit ? 'Save Changes' : 'Register User'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
