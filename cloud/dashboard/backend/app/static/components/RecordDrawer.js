const { useState, useEffect } = React;

function DetailField({ label, value, mono = false }) {
    return (
        <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl px-3.5 py-2.5">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
            <div className={`text-sm text-slate-200 mt-1 break-words ${mono ? "font-mono" : "font-medium"}`}>
                {value !== null && value !== undefined && value !== "" ? value : <span className="text-slate-600 italic">Not set</span>}
            </div>
        </div>
    );
}

function formatDateTime(val) {
    if (!val) return "Never";
    try {
        const d = new Date(val);
        if (Number.isNaN(d.getTime())) return String(val);
        return d.toLocaleString();
    } catch {
        return String(val);
    }
}

function RecordDrawer({
    record,
    kind,
    refs = {},
    onClose,
    onEdit,
    onDelete,
    onToggleUserStatus,
    onOpenFaceEnroll,
    onRevokeSession,
    onRotateDeviceSecret,
}) {
    const [activeSection, setActiveSection] = useState("profile");
    const [detailData, setDetailData] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState("");

    useEffect(() => {
        if (!record) return;
        const onKeyDown = (e) => {
            if (e.key === "Escape") onClose?.();
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [record, onClose]);

    useEffect(() => {
        setActiveSection("profile");
        setDetailData(null);
        setDetailError("");
        if (!record || kind !== "user" || !record.user_id) return;

        let cancelled = false;
        setDetailLoading(true);
        fetch(`/api/iam/users/${record.user_id}/detail`)
            .then(async (res) => {
                const payload = await res.json();
                if (!res.ok) throw new Error(payload.detail || "Failed to load user details.");
                if (!cancelled) setDetailData(payload);
            })
            .catch((err) => {
                if (!cancelled) setDetailError(err.message || "Failed to load user details.");
            })
            .finally(() => {
                if (!cancelled) setDetailLoading(false);
            });
        return () => { cancelled = true; };
    }, [record?.user_id, record, kind]);

    useEffect(() => {
        if (record && window.lucide) window.lucide.createIcons();
    }, [record, activeSection, detailData]);

    if (!record) return null;

    const findFacultyName = (fid) =>
        (refs.faculties || []).find((f) => String(f.faculty_id) === String(fid))?.faculty_name || fid;
    const findDeptName = (did) =>
        (refs.departments || []).find((d) => String(d.department_id) === String(did))?.department_name || did;
    const findProgName = (pid) =>
        (refs.programmes || []).find((p) => String(p.programme_id) === String(pid))?.programme_name || pid;
    const findNodeLabel = (nid) => {
        if (!nid) return null;
        const node = (refs.nodes || []).find((n) => Number(n.node_id) === Number(nid));
        return node ? (node.room_label || `Node #${node.node_id}`) : `Node #${nid}`;
    };

    const renderUserInspector = () => {
        const u = detailData?.user || record;
        const biometrics = detailData?.biometrics;
        const logs = detailData?.recent_auth_logs || [];
        const sessions = detailData?.active_sessions || [];
        const enrollments = detailData?.enrollments || [];
        const appointments = detailData?.appointments || [];

        const initials = ((u.given_name?.[0] || "") + (u.family_name?.[0] || "")).toUpperCase() || (u.full_name?.slice(0, 2).toUpperCase() || "U");

        const sections = [
            { id: "profile", label: "Profile" },
            { id: "biometrics", label: "Face ID", count: biometrics ? biometrics.poses?.length : (u.enrolled_poses_count || 0) },
            { id: "activity", label: "Access & Sessions", count: logs.length + sessions.length },
            { id: "academics", label: "Academics", count: enrollments.length + appointments.length },
        ];

        return (
            <div className="flex flex-col h-full">
                {/* Header */}
                <div className="px-6 py-5 border-b border-slate-800 bg-slate-950/60">
                    <div className="flex items-start justify-between gap-4">
                        <div className="flex items-center gap-3.5 min-w-0">
                            <div className="w-12 h-12 rounded-2xl bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 flex items-center justify-center font-bold text-base shrink-0">
                                {initials}
                            </div>
                            <div className="min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <h3 className="text-lg font-bold text-slate-100 truncate">{u.full_name}</h3>
                                    <span className="text-[11px] font-mono px-2 py-0.5 rounded-md bg-slate-800 text-slate-400 border border-slate-700/60 tabular-nums">
                                        #{u.user_id}
                                    </span>
                                </div>
                                <p className="text-xs font-mono text-slate-400 truncate mt-0.5">{u.email}</p>
                                <div className="flex flex-wrap items-center gap-1.5 mt-2">
                                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${
                                        u.is_active
                                            ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                                            : "bg-red-500/10 text-red-400 border-red-500/20"
                                    }`}>
                                        <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? "bg-emerald-400" : "bg-red-400"}`} />
                                        {u.is_active ? "Active" : "Deactivated"}
                                    </span>
                                    {(u.roles || []).map((r, idx) => (
                                        <span key={idx} className="text-[10px] font-bold tracking-wider px-2 py-0.5 bg-indigo-950/80 text-indigo-300 border border-indigo-700/50 rounded-md uppercase">
                                            {r.role_name}
                                        </span>
                                    ))}
                                </div>
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={onClose}
                            aria-label="Close inspector"
                            className="p-2 rounded-xl text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors shrink-0"
                        >
                            <Icon name="x" className="w-5 h-5" />
                        </button>
                    </div>

                    {/* Quick single-user action bar */}
                    <div className="flex flex-wrap gap-2 mt-4">
                        {onEdit && (
                            <button
                                type="button"
                                onClick={() => onEdit(u)}
                                className="px-3 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold transition-colors flex items-center gap-1.5"
                            >
                                <Icon name="edit-3" className="w-3.5 h-3.5" />
                                <span>Edit Profile</span>
                            </button>
                        )}
                        {onOpenFaceEnroll && (
                            <button
                                type="button"
                                onClick={() => onOpenFaceEnroll(u)}
                                className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-indigo-300 text-xs font-bold transition-colors flex items-center gap-1.5"
                            >
                                <Icon name="scan-face" className="w-3.5 h-3.5" />
                                <span>Manage Face ID</span>
                            </button>
                        )}
                        {onToggleUserStatus && (
                            <button
                                type="button"
                                onClick={() => onToggleUserStatus(u)}
                                className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-semibold transition-colors"
                            >
                                {u.is_active ? "Deactivate" : "Activate"}
                            </button>
                        )}
                        {onDelete && (
                            <button
                                type="button"
                                onClick={() => onDelete(u)}
                                className="px-3 py-1.5 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 text-xs font-semibold transition-colors ml-auto flex items-center gap-1.5"
                            >
                                <Icon name="trash-2" className="w-3.5 h-3.5" />
                                <span>Delete</span>
                            </button>
                        )}
                    </div>

                    {/* Section Tabs */}
                    <div className="flex gap-1.5 mt-4 -mb-5 pb-0 overflow-x-auto">
                        {sections.map((s) => (
                            <button
                                key={s.id}
                                type="button"
                                onClick={() => setActiveSection(s.id)}
                                className={`px-3 py-2 text-xs font-bold border-b-2 transition-colors whitespace-nowrap flex items-center gap-1.5 ${
                                    activeSection === s.id
                                        ? "border-indigo-500 text-indigo-400"
                                        : "border-transparent text-slate-400 hover:text-slate-200"
                                }`}
                            >
                                <span>{s.label}</span>
                                {s.count !== undefined && (
                                    <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 tabular-nums">
                                        {s.count}
                                    </span>
                                )}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Body */}
                <div className="flex-1 overflow-y-auto p-6 space-y-5 scrollbar-thin">
                    {detailLoading && (
                        <div className="flex items-center gap-2.5 text-xs text-slate-400 bg-slate-950/60 border border-slate-800 rounded-xl px-4 py-3">
                            <span className="w-3.5 h-3.5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
                            <span>Loading full user telemetry...</span>
                        </div>
                    )}
                    {detailError && (
                        <div className="text-xs text-red-400 bg-red-950/30 border border-red-900/40 rounded-xl px-4 py-3">
                            {detailError}
                        </div>
                    )}

                    {activeSection === "profile" && (
                        <div className="space-y-5">
                            <div>
                                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">Account Overview</h4>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                    <DetailField label="Given Name" value={u.given_name} />
                                    <DetailField label="Family Name" value={u.family_name} />
                                    <DetailField label="Email" value={u.email} mono />
                                    <DetailField label="Last Known Location" value={u.location_label || findNodeLabel(u.last_known_location)} />
                                    <DetailField label="Enrolled At" value={formatDateTime(u.enrolled_at)} />
                                    <DetailField label="Last Seen" value={formatDateTime(u.last_seen)} />
                                </div>
                            </div>

                            {u.student && (
                                <div>
                                    <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400 mb-3">Student Profile</h4>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                        <DetailField label="Student ID" value={u.student.student_id} mono />
                                        <DetailField label="Intake" value={u.student.intake} mono />
                                        <DetailField label="Programme" value={findProgName(u.student.programme_id || u.student.program)} />
                                        <DetailField label="Faculty" value={findFacultyName(u.student.faculty_id || u.student.faculty)} />
                                        <DetailField label="Enrollment Status" value={u.student.enrollment_status} />
                                        <DetailField label="Enrolled Since" value={u.student.enrolled_since} />
                                    </div>
                                </div>
                            )}

                            {u.lecturer && (
                                <div>
                                    <h4 className="text-xs font-bold uppercase tracking-wider text-purple-400 mb-3">Lecturer Profile</h4>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                        <DetailField label="Lecturer ID" value={u.lecturer.lecturer_id} mono />
                                        <DetailField label="Position" value={u.lecturer.position} />
                                        <DetailField label="Department" value={findDeptName(u.lecturer.department_id || u.lecturer.department)} />
                                        <DetailField label="Faculty" value={findFacultyName(u.lecturer.faculty_id || u.lecturer.faculty)} />
                                        <DetailField label="Office" value={findNodeLabel(u.lecturer.office_node_id)} />
                                        <DetailField label="Head of Department" value={u.lecturer.is_head_of_department ? "Yes" : "No"} />
                                    </div>
                                </div>
                            )}

                            {u.staff && (
                                <div>
                                    <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-3">Staff Profile</h4>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                        <DetailField label="Staff ID" value={u.staff.staff_id} mono />
                                        <DetailField label="Staff Type" value={u.staff.staff_type} />
                                        <DetailField label="Department" value={findDeptName(u.staff.department_id || u.staff.department)} />
                                        <DetailField label="Position" value={u.staff.position} />
                                        <DetailField label="Office" value={findNodeLabel(u.staff.office_node_id)} />
                                    </div>
                                </div>
                            )}

                            {u.visitor && (
                                <div>
                                    <h4 className="text-xs font-bold uppercase tracking-wider text-amber-400 mb-3">Visitor Pass</h4>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                        <DetailField label="Visitor ID" value={u.visitor.visitor_id} mono />
                                        <DetailField label="ID Number" value={u.visitor.id_number} mono />
                                        <DetailField label="Organization" value={u.visitor.organization} />
                                        <DetailField label="Purpose" value={u.visitor.visit_purpose} />
                                        <DetailField label="Access Expiry" value={formatDateTime(u.visitor.access_expiry)} />
                                    </div>
                                </div>
                            )}

                            {u.admin && (
                                <div>
                                    <h4 className="text-xs font-bold uppercase tracking-wider text-rose-400 mb-3">Admin Privileges</h4>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                        <DetailField label="Admin ID" value={u.admin.admin_id} mono />
                                        <DetailField label="Admin Type" value={u.admin.admin_type} />
                                        <DetailField label="Department" value={findDeptName(u.admin.department_id || u.admin.department)} />
                                        <DetailField label="Office" value={findNodeLabel(u.admin.office_node_id)} />
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {activeSection === "biometrics" && (
                        <div className="space-y-4">
                            <div className="grid grid-cols-2 gap-3">
                                <DetailField label="Face ID Status" value={(biometrics?.enrolled ?? u.face_enrolled) ? "Enrolled" : "Not Enrolled"} />
                                <DetailField label="Stored Embeddings" value={biometrics ? `${biometrics.embedding_count} vector(s)` : `${u.enrolled_poses_count || 0} pose(s)`} mono />
                            </div>
                            <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4">
                                <div className="flex items-center justify-between mb-3">
                                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Enrolled Poses</h4>
                                    {onOpenFaceEnroll && (
                                        <button
                                            type="button"
                                            onClick={() => onOpenFaceEnroll(u)}
                                            className="text-xs font-bold text-indigo-400 hover:text-indigo-300"
                                        >
                                            + Add / Update Pose
                                        </button>
                                    )}
                                </div>
                                {biometrics?.poses?.length > 0 ? (
                                    <div className="space-y-2">
                                        {biometrics.poses.map((p) => (
                                            <div key={p.pose} className="flex items-center justify-between px-3 py-2 rounded-lg bg-slate-900 border border-slate-800">
                                                <span className="text-xs font-mono font-bold text-slate-200">{p.pose}</span>
                                                <div className="flex gap-1.5 flex-wrap">
                                                    {p.models.map((m) => (
                                                        <span key={m} className="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                                                            {m}
                                                        </span>
                                                    ))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <p className="text-xs text-slate-500">No facial templates enrolled yet for this user.</p>
                                )}
                            </div>
                        </div>
                    )}

                    {activeSection === "activity" && (
                        <div className="space-y-5">
                            <div>
                                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
                                    Active Sessions ({sessions.length})
                                </h4>
                                {sessions.length === 0 ? (
                                    <p className="text-xs text-slate-500 bg-slate-950/50 border border-slate-800 rounded-xl p-4">No active JWT sessions.</p>
                                ) : (
                                    <div className="space-y-2">
                                        {sessions.map((s) => (
                                            <div key={s.session_id} className="flex items-center justify-between gap-3 p-3 rounded-xl bg-slate-950/60 border border-slate-800">
                                                <div className="min-w-0">
                                                    <div className="text-xs font-bold text-slate-200 flex items-center gap-2">
                                                        <span>{s.principal_type}</span>
                                                        {s.device_id && <span className="font-mono text-slate-400">· {s.device_id}</span>}
                                                    </div>
                                                    <div className="text-[11px] text-slate-500 mt-0.5">
                                                        Expires {formatDateTime(s.expires_at)}
                                                    </div>
                                                </div>
                                                {onRevokeSession && (
                                                    <button
                                                        type="button"
                                                        onClick={() => onRevokeSession(s.session_id, u.user_id)}
                                                        className="px-2.5 py-1 rounded-lg text-[11px] font-bold bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 shrink-0"
                                                    >
                                                        Revoke
                                                    </button>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div>
                                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
                                    Recent Access Attempts ({logs.length})
                                </h4>
                                {logs.length === 0 ? (
                                    <p className="text-xs text-slate-500 bg-slate-950/50 border border-slate-800 rounded-xl p-4">No gate/door access logs recorded yet.</p>
                                ) : (
                                    <div className="space-y-2">
                                        {logs.map((log) => (
                                            <div key={log.log_id} className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 flex items-start justify-between gap-3">
                                                <div className="min-w-0">
                                                    <div className="text-xs font-bold text-slate-200">
                                                        {log.device_name || log.device_id}
                                                        {log.node_label && <span className="text-slate-500 font-normal"> · {log.node_label}</span>}
                                                    </div>
                                                    <div className="text-[11px] text-slate-500 mt-0.5">
                                                        {formatDateTime(log.timestamp)}
                                                        {log.confidence_score != null && ` · Score ${(Number(log.confidence_score) * 100).toFixed(1)}%`}
                                                    </div>
                                                    {log.reason && <div className="text-[11px] text-slate-400 mt-1">{log.reason}</div>}
                                                </div>
                                                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border shrink-0 ${
                                                    log.auth_status === "SUCCESS"
                                                        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                                                        : "bg-red-500/10 text-red-400 border-red-500/20"
                                                }`}>
                                                    {log.auth_status}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {activeSection === "academics" && (
                        <div className="space-y-5">
                            <div>
                                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
                                    Course Enrollments ({enrollments.length})
                                </h4>
                                {enrollments.length === 0 ? (
                                    <p className="text-xs text-slate-500 bg-slate-950/50 border border-slate-800 rounded-xl p-4">No course enrollments found.</p>
                                ) : (
                                    <div className="space-y-2">
                                        {enrollments.map((enr) => (
                                            <div key={enr.enrollment_id} className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 flex items-center justify-between gap-3">
                                                <div>
                                                    <div className="text-xs font-bold text-slate-200">
                                                        <span className="font-mono text-indigo-400 mr-1.5">{enr.course_code}</span>
                                                        {enr.course_name}
                                                    </div>
                                                    <div className="text-[11px] text-slate-500 mt-0.5">
                                                        {enr.academic_year} · Sem {enr.semester}
                                                    </div>
                                                </div>
                                                <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700">
                                                    {enr.status}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div>
                                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
                                    Appointments ({appointments.length})
                                </h4>
                                {appointments.length === 0 ? (
                                    <p className="text-xs text-slate-500 bg-slate-950/50 border border-slate-800 rounded-xl p-4">No appointments found.</p>
                                ) : (
                                    <div className="space-y-2">
                                        {appointments.map((apt) => (
                                            <div key={apt.appointment_id} className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className="text-xs font-bold text-slate-200">
                                                        {apt.role_in_meeting === "HOST" ? "With guest" : "With host"} {apt.counterpart}
                                                    </span>
                                                    <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700">
                                                        {apt.status}
                                                    </span>
                                                </div>
                                                <div className="text-[11px] text-slate-500 mt-1">
                                                    {formatDateTime(apt.scheduled_at)} ({apt.duration_minutes} min)
                                                    {apt.location && ` · ${apt.location}`}
                                                </div>
                                                {apt.purpose && <p className="text-xs text-slate-400 mt-1">{apt.purpose}</p>}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        );
    };

    const renderGenericInspector = () => {
        let title = "Record Details";
        let subtitle = "";
        let fields = [];

        if (kind === "device") {
            title = record.device_name || record.device_id;
            subtitle = `Device ID: ${record.device_id}`;
            const roleNames = (record.allowed_role_ids || []).map(
                (rid) => (refs.roles || []).find((r) => Number(r.role_id) === Number(rid))?.role_name || `Role #${rid}`
            );
            fields = [
                { label: "Device ID", value: record.device_id, mono: true },
                { label: "Device Type", value: record.device_type },
                { label: "Location Node", value: findNodeLabel(record.node_id) },
                { label: "Status", value: record.is_active ? "Active" : "Inactive" },
                { label: "IP Address", value: record.ip_address, mono: true },
                { label: "Callback URL", value: record.callback_url, mono: true },
                { label: "Last Heartbeat", value: formatDateTime(record.last_heartbeat) },
                { label: "Allowed Roles", value: roleNames.length > 0 ? roleNames.join(", ") : "Inherits node RBAC" },
            ];
        } else if (kind === "document") {
            title = record.title || "Document";
            subtitle = record.filename || `Document #${record.document_id}`;
            fields = [
                { label: "Document ID", value: `#${record.document_id}`, mono: true },
                { label: "Filename", value: record.filename, mono: true },
                { label: "Access Level", value: (record.allowed_roles && record.allowed_roles.length > 0) ? record.allowed_roles.join(", ") : record.access_level },
                { label: "Status", value: record.is_active ? "Active" : "Archived" },
                { label: "Uploaded At", value: formatDateTime(record.uploaded_at || record.created_at) },
            ];
        } else if (kind === "course") {
            title = record.course_name || record.course_code;
            subtitle = record.course_code || `Course #${record.course_id}`;
            fields = [
                { label: "Course Code", value: record.course_code, mono: true },
                { label: "Course Name", value: record.course_name },
                { label: "Level", value: record.course_level },
                { label: "Credit Hours", value: record.credit_hours, mono: true },
                { label: "Faculty", value: findFacultyName(record.faculty_id || record.faculty) },
                { label: "Programme", value: findProgName(record.programme_id) },
                { label: "Status", value: record.is_active ? "Active" : "Inactive" },
            ];
        } else if (kind === "auth-log") {
            title = `Access Event #${record.log_id}`;
            subtitle = record.email || `User #${record.user_id || "Unknown"}`;
            fields = [
                { label: "Status", value: record.auth_status },
                { label: "Device", value: record.device_id, mono: true },
                { label: "Node", value: findNodeLabel(record.node_id) },
                { label: "Timestamp", value: formatDateTime(record.timestamp) },
                { label: "Confidence", value: record.confidence_score != null ? `${(Number(record.confidence_score) * 100).toFixed(2)}%` : "N/A", mono: true },
                { label: "Spoofing Passed", value: record.spoofing_passed === null || record.spoofing_passed === undefined ? "N/A" : (record.spoofing_passed ? "Yes" : "No") },
                { label: "Reason", value: record.reason || record.decision_reason },
                { label: "Policy Version", value: record.policy_version, mono: true },
            ];
        }

        return (
            <div className="flex flex-col h-full">
                <div className="px-6 py-5 border-b border-slate-800 bg-slate-950/60 flex items-start justify-between gap-4">
                    <div className="min-w-0">
                        <h3 className="text-lg font-bold text-slate-100 truncate">{title}</h3>
                        {subtitle && <p className="text-xs font-mono text-slate-400 mt-0.5 truncate">{subtitle}</p>}
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close inspector"
                        className="p-2 rounded-xl text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors shrink-0"
                    >
                        <Icon name="x" className="w-5 h-5" />
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto p-6 space-y-4 scrollbar-thin">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {fields.map((f, i) => (
                            <DetailField key={i} label={f.label} value={f.value} mono={f.mono} />
                        ))}
                    </div>
                </div>
                {(onEdit || onDelete || (kind === "device" && onRotateDeviceSecret)) && (
                    <div className="px-6 py-4 border-t border-slate-800 bg-slate-950/60 flex flex-wrap gap-2">
                        {onEdit && (
                            <button
                                type="button"
                                onClick={() => onEdit(record)}
                                className="px-3.5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold transition-colors flex items-center gap-1.5"
                            >
                                <Icon name="edit-3" className="w-3.5 h-3.5" />
                                <span>Edit</span>
                            </button>
                        )}
                        {kind === "device" && onRotateDeviceSecret && (
                            <button
                                type="button"
                                onClick={() => onRotateDeviceSecret(record)}
                                className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-amber-300 text-xs font-bold transition-colors flex items-center gap-1.5"
                            >
                                <Icon name="key-round" className="w-3.5 h-3.5" />
                                <span>Rotate Secret</span>
                            </button>
                        )}
                        {onDelete && (
                            <button
                                type="button"
                                onClick={() => onDelete(record)}
                                className="px-3.5 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 text-xs font-semibold transition-colors ml-auto flex items-center gap-1.5"
                            >
                                <Icon name="trash-2" className="w-3.5 h-3.5" />
                                <span>Delete</span>
                            </button>
                        )}
                    </div>
                )}
            </div>
        );
    };

    return (
        <div
            className="fixed inset-0 z-50 flex justify-end bg-slate-950/70 backdrop-blur-xs"
            onClick={onClose}
            role="dialog"
            aria-modal="true"
        >
            <div
                className="w-full max-w-xl h-full bg-slate-900 border-l border-slate-800 shadow-2xl overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                {kind === "user" ? renderUserInspector() : renderGenericInspector()}
            </div>
        </div>
    );
}

window.RecordDrawer = RecordDrawer;
