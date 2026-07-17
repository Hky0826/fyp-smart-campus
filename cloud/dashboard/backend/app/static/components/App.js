const { useState, useEffect, useRef, useMemo } = React;

const DASHBOARD_SUB_TABS = {
    iam: ["users", "roles", "facial-recognition"],
    rag: ["documents", "chatbot-queries"],
    infra: ["devices", "node-rbac", "edge-rbac", "auth-logs", "jwt-sessions"],
    academics: ["courses", "enrollments", "timetables", "appointments", "notifications", "faculties", "departments", "programmes"]
};
const DASHBOARD_DEFAULT_SUB_TAB = { iam: "users", rag: "documents", infra: "devices", academics: "courses" };
const DASHBOARD_TABS = ["overview", "iam", "rag", "infra", "academics", "mapping"];

function readDashboardRoute() {
    const parts = window.location.pathname.replace(/^\/dashboard\/?/, "").split("/").filter(Boolean);
    const storedTab = localStorage.getItem("dashboard_current_tab");
    const storedSubTab = localStorage.getItem("dashboard_current_sub_tab");
    const candidateTab = parts[0] || storedTab || "overview";
    const tab = DASHBOARD_TABS.includes(candidateTab) ? candidateTab : "overview";
    const allowedSubTabs = DASHBOARD_SUB_TABS[tab] || [];
    const candidateSubTab = parts[1] || storedSubTab || DASHBOARD_DEFAULT_SUB_TAB[tab] || "";
    const subTab = allowedSubTabs.includes(candidateSubTab) ? candidateSubTab : (DASHBOARD_DEFAULT_SUB_TAB[tab] || "");
    return { tab, subTab };
}

function dashboardPath(tab, subTab) {
    if (!tab || tab === "overview") return "/dashboard/overview";
    return subTab ? `/dashboard/${tab}/${subTab}` : `/dashboard/${tab}`;
}

// ============================================================
// MAIN APP COMPONENT
// ============================================================
        function App() {
            const initialRoute = useMemo(() => readDashboardRoute(), []);
            // ── Core auth state ──────────────────────────────
            const [token, setToken] = useState(localStorage.getItem("access_token") || "");
            const [adminType, setAdminType] = useState(localStorage.getItem("admin_type") || "");
            const [username, setUsername] = useState(localStorage.getItem("username") || "");
            const [fullName, setFullName] = useState(localStorage.getItem("full_name") || "");
            const [adminId, setAdminId] = useState(localStorage.getItem("admin_id") || "");

            // ── Navigation ───────────────────────────────────
            const [currentTab, setCurrentTab] = useState(initialRoute.tab);
            const [subTab, setSubTab] = useState(initialRoute.subTab);
            const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

            // ── UI ────────────────────────────────────────────
            const [toast, setToast] = useState(null);
            const [reembedding, setReembedding] = useState(false);
            const [formSubmitting, setFormSubmitting] = useState(false);
            const [pendingActionKey, setPendingActionKey] = useState("");

            // ── Theme State & Effect ──────────────────────────
            const [theme, setTheme] = useState(localStorage.getItem("theme") || "dark");

            useEffect(() => {
                if (theme === "light") {
                    document.documentElement.classList.add("light");
                    document.documentElement.classList.remove("dark");
                } else {
                    document.documentElement.classList.add("dark");
                    document.documentElement.classList.remove("light");
                }
                localStorage.setItem("theme", theme);
            }, [theme]);

            const toggleTheme = () => {
                setTheme(prev => prev === "dark" ? "light" : "dark");
            };

            // ── Login form state ──────────────────────────────
            const [loginUser, setLoginUser] = useState("");
            const [loginPass, setLoginPass] = useState("");
            const [loginLoading, setLoginLoading] = useState(false);
            const [loginError, setLoginError] = useState("");

            // ── Dashboard data ────────────────────────────────
            const [dashboardStats, setDashboardStats] = useState({ users: 0, devices: 0, documents: 0, courses: 0 });
            const [listData, setListData] = useState([]);
            const [listLoading, setListLoading] = useState(false);
            const [searchQuery, setSearchQuery] = useState("");

            // ── Filter state ──────────────────────────────────
            const [roleFilter, setRoleFilter] = useState("ALL");
            const [statusFilter, setStatusFilter] = useState("ALL");
            const [accessLevelFilter, setAccessLevelFilter] = useState("ALL");
            const [faceStatusFilter, setFaceStatusFilter] = useState("ALL");
            const [faceRoleFilter, setFaceRoleFilter] = useState("ALL");

            // ── Face enrollment modal ─────────────────────────
            const [showFaceModal, setShowFaceModal] = useState(false);
            const [selectedPhotoFile, setSelectedPhotoFile] = useState(null);
            const [uploadedPhoto, setUploadedPhoto] = useState(null);
            const [scanning, setScanning] = useState(false);
            const [scanStep, setScanStep] = useState(0);
            const [confidence, setConfidence] = useState(0);
            const [scanLogs, setScanLogs] = useState([]);
            const logEndRef = useRef(null);
            const [enrollMethod, setEnrollMethod] = useState("photo");
            const [activeCameraPoseIndex, setActiveCameraPoseIndex] = useState(0);
            const [liveFeedback, setLiveFeedback] = useState("Align your face in the center of the camera.");
            const [liveScanActive, setLiveScanActive] = useState(false);
            const [cameraStream, setCameraStream] = useState(null);
            const [selectedVideoFile, setSelectedVideoFile] = useState(null);
            const [videoProcessing, setVideoProcessing] = useState(false);
            const [videoError, setVideoError] = useState("");
            const videoRef = useRef(null);
            const canvasRef = useRef(null);
            // ── Guided recording state ────────────────────────────
            const [recordingPhase, setRecordingPhase] = useState('idle'); // idle|countdown|recording|embedding|success|failed
            const [recordingCountdown, setRecordingCountdown] = useState(3);
            const [guidePoseIndex, setGuidePoseIndex] = useState(0);
            const [enrollFeedback, setEnrollFeedback] = useState('');
            const [recordingProgress, setRecordingProgress] = useState(0);
            const [embeddingProgress, setEmbeddingProgress] = useState(0);
            const guidedCaptureRef = useRef({ active: false });

            // ── Record modal ──────────────────────────────────
            const [showModal, setShowModal] = useState(false);
            const [modalType, setModalType] = useState("");
            const [selectedItem, setSelectedItem] = useState(null);

            // ── Sorting & Pagination ──────────────────────────
            const [sortKey, setSortKey] = useState("");
            const [sortOrder, setSortOrder] = useState("asc");
            const [currentPage, setCurrentPage] = useState(1);
            const [itemsPerPage] = useState(10);

            // ── Reference data for forms ──────────────────────
            const [refs, setRefs] = useState({
                buildings: [], floorplans: [], nodes: [], edges: [],
                roles: [], faculties: [], programmes: [], departments: [],
                staff: []
            });
            const refsLoadedRef = useRef(false);
            const refsLoadingRef = useRef(false);
            const tabRequestIdRef = useRef(0);

            // ── Friendly sub-tab label map ────────────────────
            const subTabLabel = (t) => ({
                'users': 'Users',
                'roles': 'Access Roles',
                'facial-recognition': 'Face ID',
                'documents': 'Documents',
                'chunks': 'Content Chunks',
                'chatbot-queries': 'Chatbot Logs',
                'devices': 'Devices',
                'node-rbac': 'Room Access',
                'edge-rbac': 'Path Access',
                'auth-logs': 'Access Logs',
                'jwt-sessions': 'Active Sessions',
                'courses': 'Courses',
                'enrollments': 'Enrollments',
                'timetables': 'Timetables',
                'appointments': 'Appointments',
                'notifications': 'Notifications',
                'faculties': 'Faculties',
                'departments': 'Departments',
                'programmes': 'Programmes',
            }[t] || t);

            // ── Lucide icon refresh ───────────────────────────
            useEffect(() => { if (window.lucide) window.lucide.createIcons(); }, [currentTab, subTab, listData, showModal, showFaceModal, toast]);

            // ── Auto-scroll scan logs ─────────────────────────
            useEffect(() => { if (logEndRef.current) logEndRef.current.scrollIntoView({ behavior: 'smooth' }); }, [scanLogs]);

            // ── Helpers ───────────────────────────────────────
            const showErrorToast = (msg) => setToast({ message: msg, type: 'error' });
            const showSuccessToast = (msg) => setToast({ message: msg, type: 'success' });

            const getRecordKey = (item, tab = currentTab, activeSubTab = subTab) => {
                if (!item) return "";
                const keyMap = {
                    iam: { users: "user_id", roles: "role_id", "facial-recognition": "user_id" },
                    rag: { documents: "document_id", "chatbot-queries": "query_id" },
                    infra: { devices: "device_id", "auth-logs": "log_id", "jwt-sessions": "session_id" },
                    academics: {
                        courses: "course_id", enrollments: "enrollment_id", timetables: "timetable_id",
                        appointments: "appointment_id", notifications: "notification_id",
                        faculties: "faculty_id", departments: "department_id", programmes: "programme_id"
                    }
                };
                if (tab === "infra" && activeSubTab === "node-rbac") return `${item.node_id}:${item.role_id}`;
                if (tab === "infra" && activeSubTab === "edge-rbac") return `${item.edge_id}:${item.role_id}`;
                const key = keyMap[tab]?.[activeSubTab];
                return key ? String(item[key] ?? "") : "";
            };

            const mergeRecordIntoList = (record) => {
                const recordKey = getRecordKey(record);
                if (!recordKey) return;
                setListData(prev => {
                    const index = prev.findIndex(item => getRecordKey(item) === recordKey);
                    if (index === -1) return modalType === "create" ? [record, ...prev] : prev;
                    const next = [...prev];
                    next[index] = { ...next[index], ...record };
                    return next;
                });
            };

            const removeRecordFromList = (record) => {
                const recordKey = getRecordKey(record);
                if (!recordKey) return;
                setListData(prev => prev.filter(item => getRecordKey(item) !== recordKey));
            };

            const userHasRole = (item, roleId) => {
                const targetRoleId = Number(roleId);
                if (!targetRoleId) return false;
                if (Array.isArray(item?.roles) && item.roles.some(role => Number(role.role_id) === targetRoleId)) return true;
                return Number(item?.role_id) === targetRoleId;
            };

            const primaryRoleName = (item) => {
                if (Array.isArray(item?.roles) && item.roles.length > 0) return item.roles[0].role_name;
                return refs.roles.find(r => r.role_id === item?.role_id)?.role_name || "USER";
            };

            const refreshAfterMutation = async ({ refreshRefs = false } = {}) => {
                if (refreshRefs) await fetchReferences(true);
                await fetchTabData();
                if (currentTab === "overview") await fetchOverviewStats();
            };

            useEffect(() => {
                const nextSubTab = DASHBOARD_SUB_TABS[currentTab]?.includes(subTab)
                    ? subTab
                    : (DASHBOARD_DEFAULT_SUB_TAB[currentTab] || "");
                if (nextSubTab !== subTab) {
                    setSubTab(nextSubTab);
                    return;
                }
                localStorage.setItem("dashboard_current_tab", currentTab);
                if (nextSubTab) localStorage.setItem("dashboard_current_sub_tab", nextSubTab);
                else localStorage.removeItem("dashboard_current_sub_tab");
                const nextPath = dashboardPath(currentTab, nextSubTab);
                if (window.location.pathname !== nextPath) window.history.pushState({}, "", nextPath);
            }, [currentTab, subTab]);

            useEffect(() => {
                const handlePopState = () => {
                    const route = readDashboardRoute();
                    setCurrentTab(route.tab);
                    setSubTab(route.subTab);
                };
                window.addEventListener("popstate", handlePopState);
                return () => window.removeEventListener("popstate", handlePopState);
            }, []);

            // ── Login ─────────────────────────────────────────
            const handleLogin = async (e) => {
                e.preventDefault();
                setLoginLoading(true);
                setLoginError("");
                try {
                    const formData = new URLSearchParams();
                    formData.append("username", loginUser);
                    formData.append("password", loginPass);
                    const response = await fetch("/api/auth/login", {
                        method: "POST",
                        headers: { "Content-Type": "application/x-www-form-urlencoded" },
                        body: formData
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Authentication failed. Please check your credentials.");
                    localStorage.setItem("access_token", data.access_token);
                    localStorage.setItem("admin_type", data.admin_type);
                    localStorage.setItem("username", data.username);
                    localStorage.setItem("full_name", data.full_name);
                    localStorage.setItem("admin_id", data.admin_id);
                    setToken(data.access_token);
                    setAdminType(data.admin_type);
                    setUsername(data.username);
                    setFullName(data.full_name);
                    setAdminId(data.admin_id);
                    showSuccessToast("Welcome back! You are now signed in.");
                } catch (err) {
                    showErrorToast(err.message);
                    setLoginError(err.message);
                } finally {
                    setLoginLoading(false);
                }
            };

            // ── Logout ────────────────────────────────────────
            const handleLogout = async () => {
                try {
                    await fetch("/api/auth/logout", { method: "POST", headers: { "Authorization": `Bearer ${token}` } });
                } catch (e) {}
                localStorage.clear();
                setToken(""); setAdminType(""); setUsername(""); setFullName(""); setAdminId("");
                setSelectedPhotoFile(null);
                if (uploadedPhoto) { URL.revokeObjectURL(uploadedPhoto); setUploadedPhoto(null); }
                setCurrentTab("overview");
                setSubTab("");
                window.history.replaceState({}, "", "/dashboard/overview");
            };

            // ── 401 auto-logout interceptor ───────────────────
            useEffect(() => {
                const originalFetch = window.fetch;
                window.fetch = async (...args) => {
                    const response = await originalFetch(...args);
                    if (response.status === 401) {
                        const url = args[0];
                        if (!(typeof url === "string" && url.includes("/api/auth/login"))) handleLogout();
                    }
                    return response;
                };
                return () => { window.fetch = originalFetch; };
            }, [token, uploadedPhoto]);

            // ── Re-embed all vectors ──────────────────────────
            const handleReembedAll = async () => {
                if (!window.confirm("Re-embed all facial vectors from disk? This may take a moment.")) return;
                setReembedding(true);
                try {
                    const response = await fetch("/api/iam/users/reembed-all", { method: "POST", headers: { "Authorization": `Bearer ${token}` } });
                    const resData = await response.json();
                    if (response.ok) showSuccessToast(resData.detail || "Re-embedded all facial vectors successfully!");
                    else showErrorToast(resData.detail || "Failed to re-embed vectors.");
                } catch (err) {
                    showErrorToast("Error: " + err.message);
                } finally {
                    setReembedding(false);
                }
            };

            // ── Fetch reference lookups ───────────────────────
            const fetchReferences = async (force = false) => {
                if (!token) return;
                if (!force && (refsLoadedRef.current || refsLoadingRef.current)) return;
                refsLoadingRef.current = true;
                try {
                    const headers = { "Authorization": `Bearer ${token}` };
                    const [resBuildings, resFloorplans, resNodes, resRoles, resFaculties, resProgrammes, resDepartments, resStaff] = await Promise.all([
                        fetch("/api/refs/buildings", { headers }),
                        fetch("/api/refs/floorplans", { headers }),
                        fetch("/api/refs/nodes", { headers }),
                        fetch("/api/iam/roles", { headers }),
                        fetch("/api/refs/faculties", { headers }),
                        fetch("/api/refs/programmes", { headers }),
                        fetch("/api/refs/departments", { headers }),
                        fetch("/api/iam/staff", { headers })
                    ]);
                    const [dBuildings, dFloorplans, dNodes, dRoles, dFaculties, dProgrammes, dDepartments, dStaff] = await Promise.all([
                        resBuildings.ok ? resBuildings.json() : [],
                        resFloorplans.ok ? resFloorplans.json() : [],
                        resNodes.ok ? resNodes.json() : [],
                        resRoles.ok ? resRoles.json() : [],
                        resFaculties.ok ? resFaculties.json() : [],
                        resProgrammes.ok ? resProgrammes.json() : [],
                        resDepartments.ok ? resDepartments.json() : [],
                        resStaff.ok ? resStaff.json() : []
                    ]);
                    setRefs({
                        buildings: Array.isArray(dBuildings) ? dBuildings : [],
                        floorplans: Array.isArray(dFloorplans) ? dFloorplans : [],
                        nodes: Array.isArray(dNodes) ? dNodes : [],
                        roles: Array.isArray(dRoles) ? dRoles : [],
                        faculties: Array.isArray(dFaculties) ? dFaculties : [],
                        programmes: Array.isArray(dProgrammes) ? dProgrammes : [],
                        departments: Array.isArray(dDepartments) ? dDepartments : [],
                        staff: Array.isArray(dStaff) ? dStaff : [],
                        edges: []
                    });
                    refsLoadedRef.current = true;
                } catch (err) {
                    console.error("Failed to fetch references:", err);
                } finally {
                    refsLoadingRef.current = false;
                }
            };

            // ── Fetch overview stats ──────────────────────────
            const fetchOverviewStats = async () => {
                if (!token) return;
                try {
                    const headers = { "Authorization": `Bearer ${token}` };
                    const response = await fetch("/api/infra/dashboard-stats", { headers });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Failed to load overview stats.");
                    setDashboardStats({
                        users: Number(data.users) || 0,
                        devices: Number(data.devices) || 0,
                        documents: Number(data.documents) || 0,
                        courses: Number(data.courses) || 0
                    });
                } catch (err) { console.error("Overview stats failed:", err); }
            };

            // ── Fetch current tab data ────────────────────────
            const fetchTabData = async () => {
                if (!token) return;
                const requestId = ++tabRequestIdRef.current;
                setListLoading(true);
                try {
                    const headers = { "Authorization": `Bearer ${token}` };
                    const endpointMap = {
                        iam: { users: "/api/iam/users", roles: "/api/iam/roles", "facial-recognition": "/api/iam/users" },
                        rag: { documents: "/api/rag/documents", "chatbot-queries": "/api/rag/chatbot-queries" },
                        infra: { devices: "/api/infra/devices", "node-rbac": "/api/infra/node-rbac", "edge-rbac": "/api/infra/edge-rbac", "auth-logs": "/api/infra/auth-logs", "jwt-sessions": "/api/infra/jwt-sessions" },
                        academics: { courses: "/api/academics/courses", enrollments: "/api/academics/enrollments", timetables: "/api/academics/timetables", appointments: "/api/academics/appointments", notifications: "/api/academics/notifications", faculties: "/api/refs/faculties", departments: "/api/refs/departments", programmes: "/api/refs/programmes" }
                    };
                    const endpoint = endpointMap[currentTab]?.[subTab];
                    if (!endpoint) {
                        setListData([]);
                        return;
                    }
                    const response = await fetch(endpoint, { headers });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Failed to load data.");
                    if (requestId === tabRequestIdRef.current) setListData(Array.isArray(data) ? data : []);
                } catch (err) {
                    showErrorToast(err.message);
                } finally {
                    if (requestId === tabRequestIdRef.current) setListLoading(false);
                }
            };

            // ── Effects: data loading ─────────────────────────
            useEffect(() => {
                if (token) {
                    fetchReferences();
                    if (currentTab === "overview") fetchOverviewStats();
                    else if (subTab || !DASHBOARD_DEFAULT_SUB_TAB[currentTab]) fetchTabData();
                }
            }, [token, currentTab, subTab]);

            // ── Default sub-tab per main tab ──────────────────
            useEffect(() => {
                const allowed = DASHBOARD_SUB_TABS[currentTab];
                if (!allowed) {
                    if (subTab) setSubTab("");
                    return;
                }
                if (!allowed.includes(subTab)) setSubTab(DASHBOARD_DEFAULT_SUB_TAB[currentTab]);
            }, [currentTab, subTab]);

            // ── Reset filters on tab change ───────────────────
            useEffect(() => {
                setSearchQuery(""); setRoleFilter("ALL"); setStatusFilter("ALL");
                setAccessLevelFilter("ALL"); setFaceStatusFilter("ALL"); setFaceRoleFilter("ALL");
            }, [currentTab, subTab]);

            // ── Reset pagination on filter change ─────────────
            useEffect(() => { setCurrentPage(1); }, [searchQuery, currentTab, subTab, roleFilter, statusFilter, faceStatusFilter, faceRoleFilter]);

            // ── Form submit ───────────────────────────────────
            const handleFormSubmit = async (e, payload) => {
                e.preventDefault();
                if (formSubmitting) return;
                setFormSubmitting(true);
                try {
                    const headers = { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" };
                    let endpoint = "", method = "POST", finalBody = null, createdUser = null, savedRecord = null;

                    if (currentTab === "iam") {
                        if (subTab === "users") {
                            const { roleName, isEdit, user_id, user_payload, profile_payload } = payload;
                            if (!isEdit) {
                                const endpointMap = { STUDENT: "/api/iam/students", LECTURER: "/api/iam/lecturers", STAFF: "/api/iam/staff", VISITOR: "/api/iam/visitors", ADMIN: "/api/iam/admins" };
                                endpoint = endpointMap[roleName] || "/api/iam/users";
                                finalBody = endpointMap[roleName] ? { ...profile_payload, user: user_payload } : user_payload;
                                const res = await fetch(endpoint, { method: "POST", headers, body: JSON.stringify(finalBody) });
                                const data = await res.json();
                                if (!res.ok) throw new Error(data.detail || "Operation Failed");
                                createdUser = data.user || data;
                                savedRecord = createdUser;
                            } else {
                                const ur = await fetch(`/api/iam/users/${user_id}`, { method: "PUT", headers, body: JSON.stringify(user_payload) });
                                const updatedUser = await ur.json();
                                if (!ur.ok) { throw new Error(updatedUser.detail || "Failed to update user."); }
                                savedRecord = updatedUser;
                                const profileMap = {
                                    STUDENT: { hasProfile: !!selectedItem.student, idKey: 'student_id', base: '/api/iam/students' },
                                    LECTURER: { hasProfile: !!selectedItem.lecturer, idKey: 'lecturer_id', base: '/api/iam/lecturers' },
                                    STAFF: { hasProfile: !!selectedItem.staff, idKey: 'staff_id', base: '/api/iam/staff' },
                                    VISITOR: { hasProfile: !!selectedItem.visitor, idKey: 'visitor_id', base: '/api/iam/visitors' },
                                    ADMIN: { hasProfile: !!selectedItem.admin, idKey: 'admin_id', base: '/api/iam/admins' }
                                };
                                const pm = profileMap[roleName];
                                if (pm) {
                                    endpoint = pm.hasProfile ? `${pm.base}/${selectedItem[roleName.toLowerCase()][pm.idKey]}` : pm.base;
                                    method = pm.hasProfile ? "PUT" : "POST";
                                    finalBody = pm.hasProfile ? profile_payload : { ...profile_payload, user_id };
                                    const pr = await fetch(endpoint, { method, headers, body: JSON.stringify(finalBody) });
                                    if (!pr.ok) { const d = await pr.json(); throw new Error(d.detail || "Failed to update profile."); }
                                }
                            }
                            endpoint = ""; finalBody = null;
                        } else if (subTab === "roles") {
                            endpoint = modalType === "create" ? "/api/iam/roles" : `/api/iam/roles/${selectedItem.role_id}`;
                            method = modalType === "create" ? "POST" : "PUT";
                            finalBody = payload;
                        }
                    } else if (currentTab === "rag" && subTab === "documents") {
                        endpoint = modalType === "create" ? "/api/rag/documents" : `/api/rag/documents/${selectedItem.document_id}`;
                        method = modalType === "create" ? "POST" : "PUT"; finalBody = payload;
                    } else if (currentTab === "infra") {
                        if (subTab === "devices") {
                            endpoint = modalType === "create" ? "/api/infra/devices" : `/api/infra/devices/${selectedItem.device_id}`;
                            method = modalType === "create" ? "POST" : "PUT"; finalBody = payload;
                        } else if (subTab === "node-rbac") { endpoint = "/api/infra/node-rbac"; method = "POST"; finalBody = payload; }
                        else if (subTab === "edge-rbac") { endpoint = "/api/infra/edge-rbac"; method = "POST"; finalBody = payload; }
                    } else if (currentTab === "academics") {
                        if (subTab === "courses") {
                            endpoint = modalType === "create" ? "/api/academics/courses" : `/api/academics/courses/${selectedItem.course_id}`;
                            method = modalType === "create" ? "POST" : "PUT";
                            finalBody = payload;
                        } else if (subTab === "enrollments") {
                            endpoint = modalType === "create" ? "/api/academics/enrollments" : `/api/academics/enrollments/${selectedItem.enrollment_id}`;
                            method = modalType === "create" ? "POST" : "PUT";
                            finalBody = payload;
                        } else if (subTab === "timetables") {
                            endpoint = modalType === "create" ? "/api/academics/timetables" : `/api/academics/timetables/${selectedItem.timetable_id}`;
                            method = modalType === "create" ? "POST" : "PUT";
                            finalBody = payload;
                        } else if (subTab === "faculties") {
                            endpoint = modalType === "create" ? "/api/refs/faculties" : `/api/refs/faculties/${selectedItem.faculty_id}`;
                            method = modalType === "create" ? "POST" : "PUT";
                            finalBody = payload;
                        } else if (subTab === "departments") {
                            endpoint = modalType === "create" ? "/api/refs/departments" : `/api/refs/departments/${selectedItem.department_id}`;
                            method = modalType === "create" ? "POST" : "PUT";
                            finalBody = payload;
                        } else if (subTab === "programmes") {
                            endpoint = modalType === "create" ? "/api/refs/programmes" : `/api/refs/programmes/${selectedItem.programme_id}`;
                            method = modalType === "create" ? "POST" : "PUT";
                            finalBody = payload;
                        } else if (subTab === "appointments") {
                            endpoint = modalType === "create" ? "/api/academics/appointments" : `/api/academics/appointments/${selectedItem?.appointment_id}`;
                            method = modalType === "create" ? "POST" : "PUT";
                            finalBody = payload;
                        }
                    }

                    if (finalBody && endpoint) {
                        let fetchOptions = { method, headers };
                        if (finalBody instanceof FormData) {
                            delete headers["Content-Type"];
                            fetchOptions.body = finalBody;
                        } else {
                            fetchOptions.body = JSON.stringify(finalBody);
                        }
                        const response = await fetch(endpoint, fetchOptions);
                        const data = await response.json();
                        if (!response.ok) throw new Error(data.detail || "Operation Failed");
                        savedRecord = data;
                    }

                    mergeRecordIntoList(savedRecord);
                    showSuccessToast(`Record ${modalType === 'create' ? 'created' : 'updated'} successfully!`);
                    setShowModal(false);
                    refreshAfterMutation({ refreshRefs: currentTab === "academics" && ["faculties", "departments", "programmes"].includes(subTab) });

                    if (currentTab === "iam" && subTab === "users" && modalType === "create" && createdUser) {
                        setSelectedItem(createdUser);
                        setConfidence(0); setScanStep(0); setScanning(false);
                        setUploadedPhoto(null); setSelectedPhotoFile(null);
                        setEnrollMethod("video");
                        setShowFaceModal(true);
                    }
                } catch (err) { showErrorToast(err.message); }
                finally { setFormSubmitting(false); }
            };

            // ── Delete ────────────────────────────────────────
            const handleDeleteItem = async (item) => {
                if (!confirm("Are you sure you want to delete this record? This cannot be undone.")) return;
                const actionKey = `delete:${getRecordKey(item)}`;
                if (pendingActionKey) return;
                setPendingActionKey(actionKey);
                try {
                    const headers = { "Authorization": `Bearer ${token}` };
                    const epMap = {
                        iam: { users: `/api/iam/users/${item.user_id}`, roles: `/api/iam/roles/${item.role_id}` },
                        rag: { documents: `/api/rag/documents/${item.document_id}` },
                        infra: { devices: `/api/infra/devices/${item.device_id}`, "node-rbac": `/api/infra/node-rbac/${item.node_id}/${item.role_id}`, "edge-rbac": `/api/infra/edge-rbac/${item.edge_id}/${item.role_id}` },
                        academics: { courses: `/api/academics/courses/${item.course_id}`, enrollments: `/api/academics/enrollments/${item.enrollment_id}`, timetables: `/api/academics/timetables/${item.timetable_id}`, appointments: `/api/academics/appointments/${item.appointment_id}`, faculties: `/api/refs/faculties/${item.faculty_id}`, departments: `/api/refs/departments/${item.department_id}`, programmes: `/api/refs/programmes/${item.programme_id}` }
                    };
                    const endpoint = epMap[currentTab]?.[subTab];
                    if (!endpoint) return;
                    const response = await fetch(endpoint, { method: "DELETE", headers });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Delete failed.");
                    removeRecordFromList(item);
                    showSuccessToast("Record deleted successfully.");
                    refreshAfterMutation({ refreshRefs: currentTab === "academics" && ["faculties", "departments", "programmes"].includes(subTab) });
                } catch (err) { showErrorToast(err.message); }
                finally { setPendingActionKey(""); }
            };

            // ── Toggle active status ──────────────────────────
            const handleToggleStatus = async (item) => {
                const actionKey = `toggle:${getRecordKey(item)}`;
                if (pendingActionKey) return;
                setPendingActionKey(actionKey);
                try {
                    const headers = { "Authorization": `Bearer ${token}` };
                    const epMap = { iam: { users: `/api/iam/users/${item.user_id}/toggle-active` }, rag: { documents: `/api/rag/documents/${item.document_id}/toggle-active` } };
                    const endpoint = epMap[currentTab]?.[subTab];
                    if (!endpoint) return;
                    const response = await fetch(endpoint, { method: "POST", headers });
                    if (!response.ok) { const d = await response.json(); throw new Error(d.detail || "Toggle failed."); }
                    mergeRecordIntoList({ ...item, is_active: !item.is_active });
                    showSuccessToast("Status updated.");
                    refreshAfterMutation();
                } catch (err) { showErrorToast(err.message); }
                finally { setPendingActionKey(""); }
            };

            const handlePingDevice = async (item) => {
                const actionKey = `ping:${item.device_id}`;
                if (pendingActionKey) return;
                setPendingActionKey(actionKey);
                try {
                    const response = await fetch(`/api/infra/devices/${item.device_id}/heartbeat`, {
                        method: "POST",
                        headers: { "Authorization": `Bearer ${token}` }
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Device did not respond.");
                    mergeRecordIntoList({ ...item, last_heartbeat: data.last_heartbeat });
                    showSuccessToast("Ping successful.");
                    fetchTabData();
                } catch (err) {
                    showErrorToast(err.message);
                } finally {
                    setPendingActionKey("");
                }
            };

            // ── Face scan simulation ──────────────────────────
            const startPhotoAnalysis = () => {
                setScanning(true); setScanStep(1); setConfidence(15);
                setScanLogs(["Initializing face analysis module...", "Image loaded and decoded."]);
                setTimeout(() => { setConfidence(38); setScanLogs(p => [...p, "Loading detection network...", "Adjusting image contrast..."]); }, 500);
                setTimeout(() => { setConfidence(62); setScanLogs(p => [...p, "Face region detected.", "Extracting 68 facial landmarks..."]); }, 1000);
                setTimeout(() => { setConfidence(85); setScanLogs(p => [...p, "Building 512-dimension embedding..."]); }, 1500);
                setTimeout(() => {
                    setConfidence(100);
                    setScanLogs(p => [...p, "Embedding complete.", "Quality check: PASSED.", "Confidence: 99%."]);
                    setScanning(false); setScanStep(2);
                }, 2000);
            };

            const handlePhotoUpload = (e) => {
                const file = e.target.files[0]; if (!file) return;
                setSelectedPhotoFile(file);
                if (uploadedPhoto) URL.revokeObjectURL(uploadedPhoto);
                setUploadedPhoto(URL.createObjectURL(file));
                setScanning(false); setConfidence(0); setScanStep(1);
                setScanLogs(["Loading image..."]);
                startPhotoAnalysis();
            };

            const saveFacialEnrollment = async () => {
                try {
                    if (!selectedPhotoFile) throw new Error("No photo selected. Please upload a face photo first.");
                    const formData = new FormData(); formData.append("file", selectedPhotoFile);
                    const response = await fetch(`/api/iam/users/${selectedItem.user_id}/upload-photo`, {
                        method: "POST", headers: { "Authorization": `Bearer ${token}` }, body: formData
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Failed to save Face ID.");
                    showSuccessToast(`Face ID enrolled for ${selectedItem.full_name}!`);
                    setShowFaceModal(false); setSelectedPhotoFile(null);
                    if (uploadedPhoto) { URL.revokeObjectURL(uploadedPhoto); setUploadedPhoto(null); }
                    fetchTabData();
                } catch (err) { showErrorToast(err.message); }
            };

            const stopCamera = () => {
                guidedCaptureRef.current.active = false;
                if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); setCameraStream(null); }
                setLiveScanActive(false);
            };

            // ── Guided video recording flow ───────────────────────
            const GUIDE_POSES = [
                { id: 'front',       dir: null,    label: 'Face the camera — stay still' },
                { id: 'left_30',     dir: 'left',  label: 'Slowly turn your head LEFT →' },
                { id: 'left_60',     dir: 'left',  label: 'Turn your head further LEFT →' },
                { id: 'front',       dir: null,    label: 'Come back to center' },
                { id: 'right_30',    dir: 'right', label: 'Slowly turn your head RIGHT ←' },
                { id: 'right_60',    dir: 'right', label: 'Turn your head further RIGHT ←' },
                { id: 'front',       dir: null,    label: 'Come back to center' },
                { id: 'slightly_up', dir: 'up',    label: 'Gently tilt your chin UP ↑' }
            ];

            const startCamera = async () => {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' } });
                    setCameraStream(stream);
                    setRecordingPhase('idle');
                    setGuidePoseIndex(0);
                    setEnrollFeedback('');
                    setRecordingProgress(0);
                    setEmbeddingProgress(0);
                    if (videoRef.current) videoRef.current.srcObject = stream;
                } catch (err) {
                    setEnrollFeedback('Could not access camera: ' + err.message);
                }
            };

            const completeLiveEnrollment = async () => {
                setRecordingPhase('embedding');
                setEmbeddingProgress(8);
                setEnrollFeedback('');

                let progress = 8;
                const progressTimer = setInterval(() => {
                    progress = Math.min(92, progress + (progress < 60 ? 8 : progress < 84 ? 4 : 2));
                    setEmbeddingProgress(progress);
                }, 350);

                try {
                    const response = await fetch(`/api/iam/users/${selectedItem.user_id}/enroll-live/complete`, {
                        method: "POST",
                        headers: { "Authorization": `Bearer ${token}` }
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Face embedding failed.");
                    setEmbeddingProgress(100);
                    setRecordingPhase('success');
                    showSuccessToast(`Face ID enrolled for ${selectedItem.full_name}!`);
                    setTimeout(() => { stopCamera(); setShowFaceModal(false); fetchTabData(); }, 1200);
                } catch (err) {
                    setRecordingPhase('failed');
                    setEnrollFeedback(err.message);
                } finally {
                    clearInterval(progressTimer);
                }
            };

            const startGuidedRecording = async () => {
                if (!cameraStream) return;
                try {
                    const startResponse = await fetch(`/api/iam/users/${selectedItem.user_id}/enroll-live/start`, {
                        method: "POST",
                        headers: { "Authorization": `Bearer ${token}` }
                    });
                    const startData = await startResponse.json();
                    if (!startResponse.ok) throw new Error(startData.detail || "Could not start live enrollment.");
                } catch (err) {
                    setRecordingPhase('failed');
                    setEnrollFeedback(err.message);
                    return;
                }

                // Countdown 3-2-1 then start
                setRecordingPhase('countdown');
                setRecordingCountdown(3);
                setRecordingProgress(0);
                setEmbeddingProgress(0);
                setEnrollFeedback('');
                guidedCaptureRef.current.active = true;
                let c = 3;
                const cdTimer = setInterval(() => {
                    c--;
                    setRecordingCountdown(c);
                    if (c <= 0) {
                        clearInterval(cdTimer);
                        setRecordingPhase('recording');
                        setGuidePoseIndex(0);
                        setRecordingProgress(0);

                        // Advance guide arrow through poses
                        let pIdx = 0;

                        const pollVideoFrame = async () => {
                            if (!guidedCaptureRef.current.active) return;
                            if (pIdx >= GUIDE_POSES.length) return;

                            if (videoRef.current && canvasRef.current) {
                                const ctx = canvasRef.current.getContext('2d');
                                ctx.drawImage(videoRef.current, 0, 0, canvasRef.current.width, canvasRef.current.height);
                                canvasRef.current.toBlob(async (blob) => {
                                    if (blob) {
                                        const fd = new FormData();
                                        fd.append("file", new File([blob], "frame.jpg", { type: "image/jpeg" }));
                                        try {
                                            const r = await fetch(`/api/iam/users/${selectedItem.user_id}/enroll-live/frame?target_pose=${GUIDE_POSES[pIdx].id}`, { method: "POST", headers: { "Authorization": `Bearer ${token}` }, body: fd });
                                            const d = await r.json();
                                            if (d.success) {
                                                pIdx++;
                                                setRecordingProgress(Math.round((pIdx / GUIDE_POSES.length) * 100));
                                                if (pIdx < GUIDE_POSES.length) {
                                                    setGuidePoseIndex(pIdx);
                                                    setTimeout(pollVideoFrame, 500); // small delay before next pose
                                                } else {
                                                    guidedCaptureRef.current.active = false;
                                                    setRecordingProgress(100);
                                                    await completeLiveEnrollment();
                                                }
                                                return; // advanced, exit callback
                                            }
                                            setEnrollFeedback(d.guidance || "Adjust your pose and try again.");
                                        } catch (e) { console.error("Poll error:", e); }
                                    }
                                    if (guidedCaptureRef.current.active) setTimeout(pollVideoFrame, 300);
                                }, "image/jpeg", 0.78);
                            } else {
                                if (guidedCaptureRef.current.active) setTimeout(pollVideoFrame, 300);
                            }
                        };
                        
                        pollVideoFrame();
                    }
                }, 1000);
            };

            const retryRecording = () => {
                guidedCaptureRef.current.active = false;
                setRecordingPhase('idle');
                setGuidePoseIndex(0);
                setEnrollFeedback('');
                setRecordingProgress(0);
                setEmbeddingProgress(0);
            };

            const handleVideoFileChange = (e) => { setSelectedVideoFile(e.target.files[0]); setVideoError(""); };

            const uploadVideoEnrollment = async () => {
                if (!selectedVideoFile) { setVideoError("Please select a video file first."); return; }
                setVideoProcessing(true); setVideoError("");
                try {
                    const formData = new FormData(); formData.append("file", selectedVideoFile);
                    const response = await fetch(`/api/iam/users/${selectedItem.user_id}/enroll-video`, { method: "POST", headers: { "Authorization": `Bearer ${token}` }, body: formData });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Video processing failed.");
                    showSuccessToast(`Face ID enrolled for ${selectedItem.full_name}!`);
                    setShowFaceModal(false); setSelectedVideoFile(null); fetchTabData();
                } catch (err) { setVideoError(err.message); } finally { setVideoProcessing(false); }
            };

            // ── Sorting helpers ───────────────────────────────
            const handleSort = (key) => { if (sortKey === key) setSortOrder(o => o === "asc" ? "desc" : "asc"); else { setSortKey(key); setSortOrder("asc"); } };
            const renderSortIcon = (key) => {
                if (sortKey !== key) return <Icon name="chevrons-up-down" className="w-3 h-3 ml-1 opacity-30" />;
                return sortOrder === "asc" ? <Icon name="chevron-up" className="w-3 h-3 ml-1 text-blue-400" /> : <Icon name="chevron-down" className="w-3 h-3 ml-1 text-blue-400" />;
            };

            // ── Filtering / Sorting ───────────────────────────
            const getFilteredSortedData = () => {
                let items = [...listData];
                const q = searchQuery.toLowerCase().trim();
                items = items.filter(item => {
                    if (currentTab === "iam") {
                        if (subTab === "roles") return q === "" || item.role_name?.toLowerCase().includes(q) || item.description?.toLowerCase().includes(q);
                        if (subTab === "facial-recognition") {
                            const mQ = q === "" || item.full_name?.toLowerCase().includes(q) || item.username?.toLowerCase().includes(q) || item.email?.toLowerCase().includes(q);
                            const mR = faceRoleFilter === "ALL" || userHasRole(item, faceRoleFilter);
                            const mS = faceStatusFilter === "ALL" || (faceStatusFilter === "ENROLLED" ? !!item.face_vector : !item.face_vector);
                            return mQ && mR && mS;
                        }
                        if (subTab === "users") {
                            const mQ = q === "" || item.full_name?.toLowerCase().includes(q) || item.username?.toLowerCase().includes(q) || item.email?.toLowerCase().includes(q) || item.student?.student_id?.toLowerCase().includes(q) || item.lecturer?.lecturer_id?.toLowerCase().includes(q) || item.staff?.staff_id?.toLowerCase().includes(q);
                            const mR = roleFilter === "ALL" || userHasRole(item, roleFilter);
                            const mS = statusFilter === "ALL" || (statusFilter === "ACTIVE" ? item.is_active : !item.is_active);
                            return mQ && mR && mS;
                        }
                    }
                    if (currentTab === "rag") {
                        if (subTab === "documents") return (q === "" || item.title?.toLowerCase().includes(q) || item.filename?.toLowerCase().includes(q)) && (accessLevelFilter === "ALL" || item.access_level === accessLevelFilter);
                        if (subTab === "chunks") return (q === "" || item.chunk_text?.toLowerCase().includes(q)) && (accessLevelFilter === "ALL" || item.access_level === accessLevelFilter);
                        if (subTab === "chatbot-queries") return q === "" || item.query_text?.toLowerCase().includes(q);
                    }
                    if (currentTab === "infra") {
                        if (subTab === "devices") return q === "" || item.device_name?.toLowerCase().includes(q) || item.device_id?.toLowerCase().includes(q);
                        if (subTab === "auth-logs") return q === "" || item.username?.toLowerCase().includes(q) || item.auth_status?.toLowerCase().includes(q);
                        if (subTab === "jwt-sessions") return q === "" || item.user?.username?.toLowerCase().includes(q) || item.ip_address?.toLowerCase().includes(q);
                    }
                    if (currentTab === "academics") {
                        if (subTab === "courses") return q === "" || item.course_name?.toLowerCase().includes(q) || item.course_code?.toLowerCase().includes(q);
                        if (subTab === "enrollments") return q === "" || item.student_id?.toLowerCase().includes(q);
                        if (subTab === "appointments") return q === "" || item.purpose?.toLowerCase().includes(q) || item.status?.toLowerCase().includes(q);
                        if (subTab === "notifications") return q === "" || item.title?.toLowerCase().includes(q) || item.body?.toLowerCase().includes(q);
                        if (subTab === "faculties") return q === "" || item.faculty_name?.toLowerCase().includes(q) || item.faculty_id?.toLowerCase().includes(q);
                        if (subTab === "departments") return q === "" || item.department_name?.toLowerCase().includes(q) || item.department_id?.toLowerCase().includes(q);
                        if (subTab === "programmes") return q === "" || item.programme_name?.toLowerCase().includes(q) || item.programme_id?.toLowerCase().includes(q);
                    }
                    return true;
                });
                if (sortKey) {
                    items.sort((a, b) => {
                        let vA = a[sortKey] ?? "", vB = b[sortKey] ?? "";
                        if (typeof vA === "string") vA = vA.toLowerCase();
                        if (typeof vB === "string") vB = vB.toLowerCase();
                        if (vA < vB) return sortOrder === "asc" ? -1 : 1;
                        if (vA > vB) return sortOrder === "asc" ? 1 : -1;
                        return 0;
                    });
                }
                return items;
            };

            const processedData = useMemo(
                () => getFilteredSortedData(),
                [listData, searchQuery, currentTab, subTab, roleFilter, statusFilter, accessLevelFilter, faceStatusFilter, faceRoleFilter, sortKey, sortOrder]
            );
            const totalItems = processedData.length;
            const totalPages = Math.ceil(totalItems / itemsPerPage) || 1;
            const pageToRender = Math.min(currentPage, totalPages);
            const startIndex = (pageToRender - 1) * itemsPerPage;
            const paginatedData = processedData.slice(startIndex, startIndex + itemsPerPage);

            // ── Pagination render ─────────────────────────────
            const renderPagination = () => {
                if (totalItems <= itemsPerPage) return null;
                return (
                    <div className="flex flex-col sm:flex-row justify-between items-center gap-4 mt-6 bg-slate-900/30 border border-slate-800 p-4 rounded-2xl">
                        <span className="text-xs text-slate-500">
                            Showing <span className="text-white font-bold">{startIndex + 1}</span>–<span className="text-white font-bold">{Math.min(startIndex + itemsPerPage, totalItems)}</span> of <span className="text-white font-bold">{totalItems}</span> records
                        </span>
                        <div className="flex items-center gap-1">
                            {[["chevrons-left", 1], ["chevron-left", Math.max(pageToRender - 1, 1)]].map(([ic, pg], i) => (
                                <button key={i} onClick={() => setCurrentPage(pg)} disabled={pageToRender === 1}
                                    className="p-2 rounded-xl bg-slate-800 border border-slate-700/50 hover:bg-slate-700 text-slate-300 disabled:opacity-30 disabled:cursor-not-allowed transition-all">
                                    <Icon name={ic} className="w-4 h-4" />
                                </button>
                            ))}
                            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                                let pn = pageToRender <= 3 ? i + 1 : pageToRender >= totalPages - 2 ? totalPages - 4 + i : pageToRender - 2 + i;
                                if (pn < 1 || pn > totalPages) return null;
                                return (
                                    <button key={pn} onClick={() => setCurrentPage(pn)}
                                        className={`w-9 h-9 rounded-xl text-xs font-bold transition-all ${pageToRender === pn ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/30' : 'bg-slate-800 border border-slate-700/50 text-slate-400 hover:bg-slate-700 hover:text-white'}`}>
                                        {pn}
                                    </button>
                                );
                            })}
                            {[["chevron-right", Math.min(pageToRender + 1, totalPages)], ["chevrons-right", totalPages]].map(([ic, pg], i) => (
                                <button key={i} onClick={() => setCurrentPage(pg)} disabled={pageToRender === totalPages}
                                    className="p-2 rounded-xl bg-slate-800 border border-slate-700/50 hover:bg-slate-700 text-slate-300 disabled:opacity-30 disabled:cursor-not-allowed transition-all">
                                    <Icon name={ic} className="w-4 h-4" />
                                </button>
                            ))}
                        </div>
                    </div>
                );
            };

            // ── Camera frame polling ──────────────────────────
            useEffect(() => {
                let active = true, timerId = null;
                const validPoses = ["front","left_30","right_30","left_60","right_60","slightly_up"];
                async function pollFrame() {
                    if (!active || enrollMethod !== 'live' || !liveScanActive || !cameraStream || !selectedItem) return;
                    if (!videoRef.current || !canvasRef.current) { timerId = setTimeout(pollFrame, 500); return; }
                    const ctx = canvasRef.current.getContext('2d');
                    ctx.drawImage(videoRef.current, 0, 0, canvasRef.current.width, canvasRef.current.height);
                    canvasRef.current.toBlob(async (blob) => {
                        if (!blob) { if (active) timerId = setTimeout(pollFrame, 500); return; }
                        const fd = new FormData(); fd.append("file", new File([blob], "frame.jpg", { type: "image/jpeg" }));
                        try {
                            const r = await fetch(`/api/iam/users/${selectedItem.user_id}/enroll-live/frame?target_pose=${validPoses[activeCameraPoseIndex]}`, { method: "POST", headers: { "Authorization": `Bearer ${token}` }, body: fd });
                            const d = await r.json();
                            if (!active) return;
                            if (d.success) {
                                setLiveFeedback("Pose captured!");
                                if (activeCameraPoseIndex < validPoses.length - 1) setActiveCameraPoseIndex(p => p + 1);
                                else { setLiveScanActive(false); await completeLiveEnrollment(); }
                            } else { setLiveFeedback(d.guidance || "Adjust your pose and try again."); }
                        } catch (e) { console.error("Poll error:", e); }
                        finally { if (active) timerId = setTimeout(pollFrame, 800); }
                    }, "image/jpeg", 0.85);
                }
                if (enrollMethod === 'live' && liveScanActive && cameraStream && selectedItem) timerId = setTimeout(pollFrame, 200);
                return () => { active = false; if (timerId) clearTimeout(timerId); };
            }, [enrollMethod, liveScanActive, cameraStream, activeCameraPoseIndex, selectedItem]);

            useEffect(() => { if (cameraStream && videoRef.current) videoRef.current.srcObject = cameraStream; }, [cameraStream]);

            // ── Render modal form ─────────────────────────────
            const renderModalForm = () => {
                if (subTab === "users") return <UserForm item={selectedItem} roles={refs.roles} nodes={refs.nodes} programmes={refs.programmes} faculties={refs.faculties} departments={refs.departments} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (subTab === "roles") return <RoleForm item={selectedItem} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "rag" && subTab === "documents") return <DocumentForm item={selectedItem} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "infra" && subTab === "devices") return <DeviceForm item={selectedItem} nodes={refs.nodes} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "academics" && subTab === "courses") return <CourseForm item={selectedItem} programmes={refs.programmes} faculties={refs.faculties} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "academics" && subTab === "enrollments") return <EnrollmentForm item={selectedItem} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "academics" && subTab === "timetables") return <TimetableForm item={selectedItem} nodes={refs.nodes} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "academics" && subTab === "appointments") return <AppointmentForm item={selectedItem} nodes={refs.nodes} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "academics" && subTab === "faculties") return <FacultyForm item={selectedItem} staff={refs.staff} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "academics" && subTab === "departments") return <DepartmentForm item={selectedItem} staff={refs.staff} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "academics" && subTab === "programmes") return <ProgrammeForm item={selectedItem} staff={refs.staff} faculties={refs.faculties} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                return <div className="text-slate-400 text-sm py-4 text-center">Form not configured for this section.</div>;
            };

            // ============================================================
            // UNAUTHENTICATED: LOGIN PAGE
            // ============================================================
            if (!token) {
                return (
                    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4 relative overflow-hidden">
                        {/* Ambient blobs */}
                        <div className="absolute inset-0 pointer-events-none overflow-hidden">
                            <div className="absolute top-[-15%] left-[-10%] w-[55%] h-[55%] bg-blue-900/10 rounded-full blur-[120px]"></div>
                            <div className="absolute bottom-[-15%] right-[-10%] w-[55%] h-[55%] bg-indigo-900/10 rounded-full blur-[120px]"></div>
                        </div>

                        <div className="w-full max-w-md relative z-10">
                            {/* Branding */}
                            <div className="text-center mb-8">
                                <div className="inline-flex p-4 bg-blue-600/10 border border-blue-500/20 text-blue-400 rounded-2xl mb-5 shadow-lg shadow-blue-900/10">
                                    <Icon name="graduation-cap" className="w-10 h-10" />
                                </div>
                                <h1 className="text-3xl font-extrabold text-slate-100 tracking-tight">Smart Campus</h1>
                                <p className="text-slate-400 text-sm mt-2 font-medium">Admin Management Portal</p>
                            </div>

                            {/* Card */}
                            <div className="bg-slate-900 border border-slate-800 rounded-3xl p-8 shadow-2xl">
                                <h2 className="text-lg font-bold text-slate-100 mb-0.5">Welcome back</h2>
                                <p className="text-slate-500 text-sm mb-6">Sign in to manage your campus systems</p>

                                <form onSubmit={handleLogin} className="space-y-5">
                                    <div>
                                        <label className="block text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">Username</label>
                                        <div className="relative">
                                            <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-600">
                                                <Icon name="user" className="w-4 h-4" />
                                            </span>
                                            <input type="text" required value={loginUser} onChange={e => setLoginUser(e.target.value)} placeholder="Enter your username"
                                                className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-10 pr-4 py-3 text-slate-100 focus:outline-none focus:border-blue-500 placeholder-slate-700 text-sm transition-all duration-200" />
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">Password</label>
                                        <div className="relative">
                                            <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-600">
                                                <Icon name="lock" className="w-4 h-4" />
                                            </span>
                                            <input type="password" required value={loginPass} onChange={e => setLoginPass(e.target.value)} placeholder="Enter your password"
                                                className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-10 pr-4 py-3 text-slate-100 focus:outline-none focus:border-blue-500 placeholder-slate-700 text-sm transition-all duration-200" />
                                        </div>
                                        {loginError && (
                                            <div className="mt-2.5 flex items-center gap-2 text-red-400 text-xs bg-red-900/10 border border-red-900/20 rounded-xl px-3 py-2.5">
                                                <Icon name="alert-circle" className="w-3.5 h-3.5 shrink-0" />
                                                <span>{loginError}</span>
                                            </div>
                                        )}
                                    </div>
                                    <button type="submit" disabled={loginLoading}
                                        className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 px-4 rounded-xl transition-all duration-200 shadow-lg shadow-blue-900/30 flex justify-center items-center gap-2 text-sm mt-2">
                                        {loginLoading ? (
                                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                                        ) : (
                                            <>
                                                <Icon name="log-in" className="w-4 h-4" />
                                                <span>Sign In</span>
                                            </>
                                        )}
                                    </button>
                                </form>

                                {/* Feature icons */}
                                <div className="mt-6 pt-5 border-t border-slate-800">
                                    <div className="grid grid-cols-3 gap-3">
                                        {[
                                            { icon: "shield-check", label: "Secure Access" },
                                            { icon: "users", label: "User Management" },
                                            { icon: "cpu", label: "IoT Monitoring" }
                                        ].map((f, i) => (
                                            <div key={i} className="flex flex-col items-center gap-1.5">
                                                <div className="p-2 bg-slate-800 border border-slate-700/50 rounded-xl text-slate-400">
                                                    <Icon name={f.icon} className="w-4 h-4" />
                                                </div>
                                                <span className="text-[10px] text-slate-600 font-medium text-center leading-tight">{f.label}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </div>
                        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
                    </div>
                );
            }

            // ── Privilege check ───────────────────────────────
            const isTabDisabled = (tabName) => {
                if (adminType !== 'SUPER_ADMIN' && (tabName === 'infra' || tabName === 'mapping')) return true;
                if (adminType === 'CONTENT_ADMIN' && tabName !== 'rag' && tabName !== 'overview') return true;
                if (adminType === 'SYSTEM_ADMIN' && tabName === 'rag') return true;
                return false;
            };

            const navItems = [
                { id: "overview",  label: "Overview",           icon: "layout-dashboard", section: "main"   },
                { id: "iam",       label: "User Management",    icon: "users",            section: "manage" },
                { id: "rag",       label: "Knowledge Base",     icon: "book-open",        section: "manage" },
                { id: "infra",     label: "Devices & Security", icon: "shield",           section: "manage" },
                { id: "academics", label: "Scheduling",         icon: "calendar",         section: "manage" },
                { id: "mapping",   label: "Campus Map",         icon: "map",              section: "manage" },
            ];

            // ============================================================
            // AUTHENTICATED: MAIN LAYOUT
            // ============================================================
            return (
                <div className="min-h-screen flex bg-slate-900 text-slate-100 font-sans selection:bg-indigo-500/30">

                    {/* ─── SIDEBAR ──────────────────────────────────────── */}
                    <aside className={`bg-slate-950 border-r border-slate-800 flex flex-col justify-between shrink-0 z-20 transition-all duration-300 ${sidebarCollapsed ? 'w-[72px]' : 'w-[280px]'}`}>
                        <div>
                            {/* Logo row */}
                            <div className="h-[72px] px-4 border-b border-slate-800 flex items-center justify-between gap-3">
                                <div className="flex items-center gap-3 overflow-hidden">
                                    <div className="w-10 h-10 bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 rounded-xl flex items-center justify-center shrink-0">
                                        <Icon name="graduation-cap" className="w-5 h-5" />
                                    </div>
                                    {!sidebarCollapsed && (
                                        <div className="overflow-hidden flex flex-col justify-center">
                                            <h1 className="font-extrabold text-[14px] text-slate-100 tracking-wide leading-none whitespace-nowrap">Smart Campus</h1>
                                            <span className="text-[10px] text-indigo-400 font-bold tracking-widest uppercase mt-1">Admin Portal</span>
                                        </div>
                                    )}
                                </div>
                                {!sidebarCollapsed && (
                                    <button onClick={() => setSidebarCollapsed(true)}
                                        className="p-1.5 hover:bg-slate-800 rounded-lg text-slate-500 hover:text-slate-300 transition-colors shrink-0">
                                        <Icon name="chevron-left" className="w-4 h-4" />
                                    </button>
                                )}
                            </div>

                            {/* Nav */}
                            <nav className="p-4 space-y-1 mt-2">
                                {sidebarCollapsed && (
                                    <div className="flex justify-center mb-6">
                                        <button onClick={() => setSidebarCollapsed(false)} className="p-1.5 hover:bg-slate-800 rounded-lg text-slate-500 hover:text-slate-300 transition-colors">
                                            <Icon name="chevron-right" className="w-4 h-4" />
                                        </button>
                                    </div>
                                )}
                                {!sidebarCollapsed && (
                                    <p className="text-[11px] font-bold text-slate-500 uppercase tracking-wider px-3 pb-2">Main</p>
                                )}
                                {navItems.filter(n => n.section === 'main').map(n =>
                                    !isTabDisabled(n.id) && (
                                        <button key={n.id} onClick={() => setCurrentTab(n.id)} title={sidebarCollapsed ? n.label : ""}
                                            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 group relative ${sidebarCollapsed ? 'justify-center' : ''} ${currentTab === n.id ? 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20' : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 border border-transparent'}`}>
                                            {currentTab === n.id && <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-indigo-500 rounded-r-full"></div>}
                                            <Icon name={n.icon} className={`w-5 h-5 shrink-0 ${currentTab === n.id ? 'text-indigo-400' : 'text-slate-500 group-hover:text-slate-300'}`} />
                                            {!sidebarCollapsed && <span>{n.label}</span>}
                                        </button>
                                    )
                                )}

                                {!sidebarCollapsed
                                    ? <p className="text-[11px] font-bold text-slate-500 uppercase tracking-wider px-3 pt-6 pb-2">Manage</p>
                                    : <div className="border-t border-slate-800/80 my-4 mx-2"></div>
                                }
                                {navItems.filter(n => n.section === 'manage').map(n =>
                                    !isTabDisabled(n.id) && (
                                        <button key={n.id} onClick={() => setCurrentTab(n.id)} title={sidebarCollapsed ? n.label : ""}
                                            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 group relative ${sidebarCollapsed ? 'justify-center' : ''} ${currentTab === n.id ? 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20' : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 border border-transparent'}`}>
                                            {currentTab === n.id && <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-indigo-500 rounded-r-full"></div>}
                                            <Icon name={n.icon} className={`w-5 h-5 shrink-0 ${currentTab === n.id ? 'text-indigo-400' : 'text-slate-500 group-hover:text-slate-300'}`} />
                                            {!sidebarCollapsed && <span>{n.label}</span>}
                                        </button>
                                    )
                                )}
                            </nav>
                        </div>

                        {/* User footer */}
                        <div className="p-4 border-t border-slate-800 bg-slate-950/50">
                            <div className={`flex items-center gap-3 mb-4 ${sidebarCollapsed ? 'justify-center' : 'px-2'}`}>
                                <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white text-sm shrink-0 shadow-md border-2 border-slate-800">
                                    {fullName ? fullName.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase() : "AD"}
                                </div>
                                {!sidebarCollapsed && (
                                    <div className="overflow-hidden flex flex-col justify-center">
                                        <p className="text-sm font-bold text-slate-200 truncate">{fullName || "Admin User"}</p>
                                        <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">{adminType.replace("_", " ")}</span>
                                    </div>
                                )}
                            </div>
                            <div className={`flex ${sidebarCollapsed ? 'flex-col' : 'gap-2'}`}>
                                <button onClick={toggleTheme} title={sidebarCollapsed ? (theme === 'dark' ? "Light Mode" : "Dark Mode") : ""}
                                    className={`flex-1 bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 py-2.5 rounded-xl text-xs flex justify-center items-center transition-all border border-slate-800 ${sidebarCollapsed ? 'mb-2' : ''}`}>
                                    <Icon name={theme === 'dark' ? "sun" : "moon"} className="w-4 h-4" />
                                </button>
                                <button onClick={handleLogout} title={sidebarCollapsed ? "Sign Out" : ""}
                                    className="flex-1 bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-red-400 py-2.5 rounded-xl text-xs flex justify-center items-center transition-all border border-slate-800">
                                    <Icon name="log-out" className="w-4 h-4" />
                                </button>
                            </div>
                        </div>
                    </aside>

                    {/* ─── MAIN WRAPPER ─────────────────────────────────── */}
                    <div className="flex-1 flex flex-col min-w-0 h-screen overflow-hidden bg-slate-900 relative">
                        
                        {/* ─── TOPBAR ─────────────────────────────────────── */}
                        <header className="h-[72px] shrink-0 border-b border-slate-800/60 bg-slate-900/80 backdrop-blur-md px-8 flex items-center justify-between z-10">
                            <div className="flex items-center gap-3 text-sm">
                                <span className="text-slate-500 font-medium">{navItems.find(n => n.id === currentTab)?.section === 'main' ? 'Main' : 'Manage'}</span>
                                <Icon name="chevron-right" className="w-3.5 h-3.5 text-slate-600" />
                                <span className="text-slate-200 font-bold">{navItems.find(n => n.id === currentTab)?.label}</span>
                            </div>
                            <div className="flex items-center gap-4">
                                <div className="hidden md:flex items-center gap-2 text-xs bg-slate-800/50 border border-slate-700/50 px-3 py-1.5 rounded-full text-slate-400">
                                    <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                                    <span>System Online</span>
                                </div>
                                <button className="relative p-2 text-slate-400 hover:text-slate-200 transition-colors">
                                    <Icon name="bell" className="w-5 h-5" />
                                    <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-indigo-500 rounded-full border-2 border-slate-900"></span>
                                </button>
                            </div>
                        </header>

                        {/* ─── SCROLLABLE CONTENT ─────────────────────────── */}
                        <main className="flex-1 overflow-y-auto p-6 md:p-8 relative scrollbar-thin">
                            <div className="max-w-[1600px] mx-auto">

                                {/* ══ OVERVIEW ══════════════════════════════════════ */}
                                {currentTab === "overview" && (
                                    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out">
                                        {/* Welcome */}
                                        <div className="flex flex-col sm:flex-row justify-between sm:items-end gap-4">
                                            <div>
                                                <h1 className="text-3xl font-extrabold text-slate-100 tracking-tight">Overview</h1>
                                                <p className="text-slate-400 text-sm mt-1">Here's a summary of your Smart Campus today.</p>
                                            </div>
                                            <div className="text-right">
                                                <p className="text-xs text-slate-500 font-medium mb-1">Today's Date</p>
                                                <p className="text-sm text-slate-300 font-bold">{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}</p>
                                            </div>
                                        </div>

                                        {/* Stat cards */}
                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
                                            {adminType !== 'CONTENT_ADMIN' && <StatCard title="Total Users" value={dashboardStats.users} icon="users" changeText="+12 this week" color="blue" />}
                                            {adminType !== 'CONTENT_ADMIN' && <StatCard title="IoT Devices" value={dashboardStats.devices} icon="cpu" changeText="1 offline" color="indigo" />}
                                            {adminType !== 'SYSTEM_ADMIN' && <StatCard title="Knowledge Docs" value={dashboardStats.documents} icon="book-open" changeText="+3 this month" color="violet" />}
                                            {adminType !== 'CONTENT_ADMIN' && <StatCard title="Active Courses" value={dashboardStats.courses} icon="graduation-cap" changeText="Ongoing semester" color="emerald" />}
                                        </div>

                                        {/* System status + permissions */}
                                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                                            {/* System status */}
                                            <div className="lg:col-span-2 bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6 shadow-sm">
                                                <div className="flex items-center justify-between mb-6">
                                                    <div className="flex items-center gap-3">
                                                        <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-xl"><Icon name="activity" className="w-5 h-5" /></div>
                                                        <h3 className="text-lg font-bold text-slate-100">System Status</h3>
                                                    </div>
                                                    <button className="text-xs text-indigo-400 font-semibold hover:text-indigo-300 transition-colors">View Logs</button>
                                                </div>
                                                <div className="space-y-4">
                                                    {[
                                                        { status: "ok", title: "Database Connection", desc: "MySQL server is online and responding normally.", ping: "12ms" },
                                                        { status: "ok", title: "Security Check", desc: "JWT token integrity and session logs are verified.", ping: "8ms" },
                                                        { status: "ok", title: "API Services", desc: "All backend routes are healthy and responding.", ping: "24ms" },
                                                    ].map((s, i) => (
                                                        <div key={i} className="flex items-center justify-between p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 hover:bg-slate-700/30 transition-colors">
                                                            <div className="flex gap-4 items-start">
                                                                <span className={`w-2.5 h-2.5 rounded-full mt-1.5 shrink-0 ${s.status === 'ok' ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
                                                                <div>
                                                                    <p className="text-sm font-bold text-slate-200">{s.title}</p>
                                                                    <p className="text-xs text-slate-400 mt-0.5">{s.desc}</p>
                                                                </div>
                                                            </div>
                                                            <span className="text-[10px] font-mono text-slate-500 bg-slate-900 px-2 py-1 rounded-md">{s.ping}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>

                                            {/* My permissions */}
                                            <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6 shadow-sm">
                                                <div className="flex items-center gap-3 mb-6">
                                                    <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-xl"><Icon name="shield-check" className="w-5 h-5" /></div>
                                                    <h3 className="text-lg font-bold text-slate-100">My Access</h3>
                                                </div>
                                                <p className="text-xs text-slate-400 mb-6 leading-relaxed">Your assigned role determines which modules you can view and edit.</p>
                                                <div className="space-y-3">
                                                    {[
                                                        { label: "User Management",    granted: adminType !== 'CONTENT_ADMIN' },
                                                        { label: "Knowledge Base",     granted: adminType !== 'SYSTEM_ADMIN' },
                                                        { label: "Devices & Security", granted: adminType === 'SUPER_ADMIN' },
                                                        { label: "Scheduling",         granted: adminType !== 'CONTENT_ADMIN' },
                                                    ].map((p, i) => (
                                                        <div key={i} className="flex justify-between items-center py-3 border-b border-slate-700/50 last:border-0 last:pb-0">
                                                            <span className="text-sm text-slate-300 font-medium">{p.label}</span>
                                                            <span className={`text-[10px] font-bold px-2.5 py-1 rounded-lg ${p.granted ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                                                                {p.granted ? "Allowed" : "Restricted"}
                                                            </span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        </div>

                                        {/* Quick actions */}
                                        <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6 shadow-sm">
                                            <div className="flex items-center gap-3 mb-6">
                                                <div className="p-2 bg-amber-500/10 text-amber-400 rounded-xl"><Icon name="zap" className="w-5 h-5" /></div>
                                                <h3 className="text-lg font-bold text-slate-100">Quick Actions</h3>
                                            </div>
                                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                                                {[
                                                    { tab: "iam",       label: "Add User",         icon: "user-plus",   color: "blue",    disabled: adminType === 'CONTENT_ADMIN' },
                                                    { tab: "rag",       label: "Upload Document",  icon: "upload",      color: "violet",  disabled: adminType === 'SYSTEM_ADMIN' },
                                                    { tab: "infra",     label: "View Devices",     icon: "cpu",         color: "indigo",  disabled: adminType !== 'SUPER_ADMIN' },
                                                    { tab: "academics", label: "Manage Courses",   icon: "book-open",   color: "emerald", disabled: adminType === 'CONTENT_ADMIN' },
                                                ].map((a, i) => (
                                                    <button key={i} onClick={() => !a.disabled && setCurrentTab(a.tab)} disabled={a.disabled}
                                                        className={`flex items-center gap-3 p-4 rounded-xl border text-left transition-all duration-200 ${a.disabled ? 'opacity-30 cursor-not-allowed border-slate-800 bg-slate-900/50' : 'border-slate-700 bg-slate-800 hover:bg-slate-700 hover:border-slate-600 cursor-pointer shadow-sm hover:shadow-md'}`}>
                                                        <div className={`p-2.5 rounded-lg bg-${a.color}-500/20 text-${a.color}-400 shrink-0`}>
                                                            <Icon name={a.icon} className="w-5 h-5" />
                                                        </div>
                                                        <span className="text-sm font-bold text-slate-200 leading-tight">{a.label}</span>
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                )}

                        {/* ══ USER MANAGEMENT (IAM) ═════════════════════════ */}
                        {currentTab === "iam" && (
                            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out">
                                {/* Sub-tab bar */}
                                <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-4 mb-6">
                                    {["users", "roles", "facial-recognition"].map(t => (
                                        <button key={t} onClick={() => setSubTab(t)}
                                            className={`px-5 py-2.5 rounded-xl text-sm font-bold transition-all duration-200 border ${subTab === t ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20 shadow-sm' : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-slate-200 hover:bg-slate-800/80 hover:border-slate-700'}`}>
                                            {subTabLabel(t)}
                                        </button>
                                    ))}
                                </div>

                                <SectionHeader
                                    title={subTab === "facial-recognition" ? "Face ID Enrollment" : subTab === "roles" ? "Access Roles" : "Users"}
                                    description={
                                        subTab === "roles" ? "Manage campus access roles and their permission levels." :
                                        subTab === "facial-recognition" ? "Set up facial recognition so users can unlock doors automatically." :
                                        "Manage all registered users, their profiles, and campus access."
                                    }
                                    searchVal={searchQuery}
                                    onSearchChange={setSearchQuery}
                                    onCreateClick={subTab === "facial-recognition" ? null : () => { setSelectedItem(null); setModalType("create"); setShowModal(true); }}
                                    createLabel={subTab === "roles" ? "Add Role" : "Register User"}
                                    customAction={
                                        subTab === "users" ? (
                                            <div className="flex gap-2 flex-wrap">
                                                <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)}
                                                    className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-sm text-slate-300 focus:outline-none focus:border-indigo-500 hover:border-slate-600 transition-colors cursor-pointer">
                                                    <option value="ALL">All Roles</option>
                                                    {refs.roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)}
                                                </select>
                                                <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
                                                    className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-sm text-slate-300 focus:outline-none focus:border-indigo-500 hover:border-slate-600 transition-colors cursor-pointer">
                                                    <option value="ALL">All Status</option>
                                                    <option value="ACTIVE">Active</option>
                                                    <option value="DEACTIVATED">Deactivated</option>
                                                </select>
                                            </div>
                                        ) : subTab === "facial-recognition" ? (
                                            <div className="flex gap-2 flex-wrap">
                                                <select value={faceStatusFilter} onChange={e => setFaceStatusFilter(e.target.value)}
                                                    className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-sm text-slate-300 focus:outline-none focus:border-indigo-500 hover:border-slate-600 transition-colors cursor-pointer">
                                                    <option value="ALL">All Users</option>
                                                    <option value="ENROLLED">Face ID Enrolled</option>
                                                    <option value="NOT_ENROLLED">Not Enrolled</option>
                                                </select>
                                                <select value={faceRoleFilter} onChange={e => setFaceRoleFilter(e.target.value)}
                                                    className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-sm text-slate-300 focus:outline-none focus:border-indigo-500 hover:border-slate-600 transition-colors cursor-pointer">
                                                    <option value="ALL">All Roles</option>
                                                    {refs.roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)}
                                                </select>
                                                {adminType === "SUPER_ADMIN" && (
                                                    <button onClick={handleReembedAll} disabled={reembedding}
                                                        className="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700/50 px-4 py-2 rounded-xl text-sm font-bold transition-all flex items-center gap-2 disabled:opacity-50">
                                                        {reembedding ? <><span className="w-3.5 h-3.5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin"></span><span>Processing...</span></>
                                                            : <><Icon name="refresh-cw" className="w-4 h-4" /><span>Re-process All</span></>}
                                                    </button>
                                                )}
                                            </div>
                                        ) : null
                                    }
                                />

                                {listLoading ? (
                                    <div className="flex flex-col items-center justify-center py-24 text-slate-500 bg-slate-900/50 rounded-2xl border border-slate-800">
                                        <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-4"></div>
                                        <span className="text-sm font-semibold">Loading data...</span>
                                    </div>
                                ) : listData.length === 0 ? (
                                    <div className="flex flex-col items-center justify-center border-2 border-dashed border-slate-800 bg-slate-900/30 rounded-3xl py-24">
                                        <div className="p-4 bg-slate-800 border border-slate-700 text-slate-400 rounded-2xl mb-5"><Icon name="users" className="w-8 h-8" /></div>
                                        <h4 className="text-base font-bold text-slate-200">No records found</h4>
                                        <p className="text-sm text-slate-500 mt-1 max-w-sm text-center">Try adjusting your filters or search query, or add a new record to get started.</p>
                                    </div>
                                ) : (
                                    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl shadow-sm overflow-hidden backdrop-blur-sm">
                                        <div className="overflow-x-auto">
                                            <table className="w-full text-left text-sm">
                                                <thead>
                                                    {subTab === "roles" && (
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Role Name</th>
                                                            <th className="p-4 font-semibold">Description</th>
                                                            <th className="p-4 font-semibold">Role ID</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    )}
                                                    {subTab === "facial-recognition" && (
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">User Profile</th>
                                                            <th className="p-4 font-semibold">Face ID Status</th>
                                                            <th className="p-4 font-semibold">Data Sample</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    )}
                                                    {subTab === "users" && (
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">User Profile</th>
                                                            <th className="p-4 font-semibold">Identity Details</th>
                                                            <th className="p-4 font-semibold">Status</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    )}
                                                </thead>
                                                <tbody className="divide-y divide-slate-800/50">
                                                    {paginatedData.map((item, idx) => {
                                                        if (subTab === "roles") return (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6">
                                                                    <div className="inline-flex px-2 py-1 rounded-md bg-slate-800 border border-slate-700/50 text-slate-200 uppercase font-mono text-xs font-bold tracking-wider">
                                                                        {item.role_name}
                                                                    </div>
                                                                </td>
                                                                <td className="p-4 text-sm text-slate-400 max-w-xs">{item.description || "—"}</td>
                                                                <td className="p-4 text-xs font-mono text-slate-500">#{item.role_id}</td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Role"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Remove Role"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        );
                                                        if (subTab === "facial-recognition") return (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6">
                                                                    <div className="flex items-center gap-4">
                                                                        <div className="w-10 h-10 rounded-full bg-slate-800 border-2 border-slate-700 flex items-center justify-center font-bold text-slate-300 text-xs shrink-0 shadow-sm">
                                                                            {item.full_name?.split(' ').map(w => w[0]).slice(0,2).join('').toUpperCase() || "??"}
                                                                        </div>
                                                                        <div>
                                                                            <p className="font-bold text-slate-200 text-sm">{item.full_name}</p>
                                                                            <p className="text-xs text-slate-500 mt-0.5">{item.email}</p>
                                                                        </div>
                                                                    </div>
                                                                </td>
                                                                <td className="p-4">
                                                                    {item.face_vector ? (
                                                                        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>Enrolled
                                                                        </span>
                                                                    ) : (
                                                                        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>Not Enrolled
                                                                        </span>
                                                                    )}
                                                                </td>
                                                                <td className="p-4 text-xs font-mono text-slate-600 max-w-[160px] truncate">
                                                                    {item.face_vector ? `${item.face_vector.slice(0, 30)}…` : "—"}
                                                                </td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    {!item.face_vector && (
                                                                        <button onClick={() => { setSelectedItem(item); setConfidence(0); setScanStep(0); setScanning(false); setShowFaceModal(true); }}
                                                                            className="bg-indigo-600 hover:bg-indigo-500 text-white font-bold px-4 py-2 rounded-xl text-xs inline-flex items-center gap-2 transition-all shadow-sm shadow-indigo-900/20">
                                                                            <Icon name="camera" className="w-4 h-4" />
                                                                            <span>Enroll Face ID</span>
                                                                        </button>
                                                                    )}
                                                                </td>
                                                            </tr>
                                                        );

                                                        // Users sub-tab
                                                        const userObj = item.user || item;
                                                        const studentObj = item.student || null;
                                                        const lecturerObj = item.lecturer || null;
                                                        const staffObj = item.staff || null;
                                                        const visitorObj = item.visitor || null;
                                                        const adminObj = item.admin || null;
                                                        return (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6">
                                                                    <div className="flex items-center gap-4">
                                                                        <div className="w-10 h-10 rounded-full bg-slate-800 border-2 border-slate-700 flex items-center justify-center font-bold text-slate-300 text-xs shrink-0 shadow-sm">
                                                                            {userObj.full_name?.split(' ').map(w => w[0]).slice(0,2).join('').toUpperCase() || "??"}
                                                                        </div>
                                                                        <div>
                                                                            <p className="font-bold text-slate-200 text-sm">{userObj.full_name}</p>
                                                                            <p className="text-xs text-slate-500 mt-0.5">{userObj.email}</p>
                                                                        </div>
                                                                    </div>
                                                                </td>
                                                                <td className="p-4">
                                                                    <div className="space-y-2">
                                                                        <div className="flex items-center gap-2">
                                                                            <span className="text-[10px] font-bold tracking-widest bg-slate-800 text-slate-400 px-2.5 py-0.5 rounded-md uppercase border border-slate-700/50">
                                                                                {primaryRoleName(userObj)}
                                                                            </span>
                                                                            <span className="text-xs text-slate-500 font-mono bg-slate-900 px-1.5 py-0.5 rounded">#{userObj.user_id}</span>
                                                                        </div>
                                                                        {studentObj && <div className="text-xs text-slate-400 flex items-center gap-1.5"><Icon name="book" className="w-3 h-3 text-slate-500"/> <span className="text-indigo-400 font-mono">{studentObj.student_id}</span> · {studentObj.program}</div>}
                                                                        {lecturerObj && <div className="text-xs text-slate-400 flex items-center gap-1.5"><Icon name="briefcase" className="w-3 h-3 text-slate-500"/> <span className="text-indigo-400 font-mono">{lecturerObj.lecturer_id}</span> · {lecturerObj.position}</div>}
                                                                        {staffObj && <div className="text-xs text-slate-400 flex items-center gap-1.5"><Icon name="briefcase" className="w-3 h-3 text-slate-500"/> <span className="text-indigo-400 font-mono">{staffObj.staff_id}</span> · {staffObj.position}</div>}
                                                                        {visitorObj && <div className="text-xs text-slate-400 flex items-center gap-1.5"><Icon name="user-check" className="w-3 h-3 text-slate-500"/> <span className="text-indigo-400 font-mono">{visitorObj.id_number}</span> · Exp {new Date(visitorObj.access_expiry).toLocaleDateString()}</div>}
                                                                        {adminObj && <div className="text-xs text-slate-400 flex items-center gap-1.5"><Icon name="shield" className="w-3 h-3 text-slate-500"/> <span className="text-indigo-400 font-mono">{adminObj.admin_id}</span> · {adminObj.admin_type}</div>}
                                                                    </div>
                                                                </td>
                                                                <td className="p-4">
                                                                    {(subTab === "admins" && adminType !== "SUPER_ADMIN") ? (
                                                                        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold border ${userObj.is_active ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'}`}>
                                                                            <span className={`w-1.5 h-1.5 rounded-full ${userObj.is_active ? 'bg-emerald-400' : 'bg-red-400'}`}></span>
                                                                            {userObj.is_active ? 'Active' : 'Deactivated'}
                                                                        </span>
                                                                    ) : (
                                                                        <button onClick={() => handleToggleStatus(item)}
                                                                            className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold border transition-all ${userObj.is_active ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500 hover:text-white hover:border-emerald-500' : 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500 hover:text-white hover:border-red-500'}`}>
                                                                            <span className={`w-1.5 h-1.5 rounded-full ${userObj.is_active ? 'bg-emerald-400' : 'bg-red-400'}`}></span>
                                                                            {userObj.is_active ? 'Active' : 'Deactivated'}
                                                                        </button>
                                                                    )}
                                                                </td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    {(subTab === "admins" && adminType !== "SUPER_ADMIN") ? (
                                                                        <span className="text-xs text-slate-600 italic">Restricted</span>
                                                                    ) : (
                                                                        <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                            <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit User"
                                                                                className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                                <Icon name="edit-3" className="w-4 h-4" />
                                                                            </button>
                                                                            <button onClick={() => handleDeleteItem(item)} title="Remove User"
                                                                                className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                                <Icon name="trash-2" className="w-4 h-4" />
                                                                            </button>
                                                                        </div>
                                                                    )}
                                                                </td>
                                                            </tr>
                                                        );
                                                    })}
                                                </tbody>
                                            </table>
                                        </div>
                                    </div>
                                )}
                                {renderPagination()}
                            </div>
                        )}

                        {/* ══ KNOWLEDGE BASE (RAG) ══════════════════════════ */}
                        {currentTab === "rag" && (
                            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out">
                                <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-4 mb-6">
                                    {DASHBOARD_SUB_TABS.rag.map(t => (
                                        <button key={t} onClick={() => setSubTab(t)}
                                            className={`px-5 py-2.5 rounded-xl text-sm font-bold transition-all duration-200 border ${subTab === t ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20 shadow-sm' : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-slate-200 hover:bg-slate-800/80 hover:border-slate-700'}`}>
                                            {subTabLabel(t)}
                                        </button>
                                    ))}
                                </div>

                                <SectionHeader
                                    title={subTab === 'documents' ? "Uploaded Documents" : "Chatbot Conversations"}
                                    description={
                                        subTab === 'documents' ? "Upload and manage documents that the campus chatbot uses to answer questions." :
                                        "Review chatbot conversation history and response quality."
                                    }
                                    searchVal={searchQuery}
                                    onSearchChange={setSearchQuery}
                                    onCreateClick={subTab === 'documents' ? () => { setSelectedItem(null); setModalType("create"); setShowModal(true); } : null}
                                    createLabel="Upload Document"
                                    customAction={subTab === 'documents' ? (
                                        <select value={accessLevelFilter} onChange={e => setAccessLevelFilter(e.target.value)}
                                            className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-sm text-slate-300 focus:outline-none focus:border-indigo-500 hover:border-slate-600 transition-colors cursor-pointer">
                                            <option value="ALL">All Access Levels</option>
                                            <option value="PUBLIC">Public</option>
                                            <option value="STUDENT">Students Only</option>
                                            <option value="LECTURER">Lecturers Only</option>
                                            <option value="ADMIN">Admins Only</option>
                                        </select>
                                    ) : null}
                                />

                                {listLoading ? (
                                    <div className="flex flex-col items-center justify-center py-24 text-slate-500 bg-slate-900/50 rounded-2xl border border-slate-800">
                                        <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-4"></div>
                                        <span className="text-sm font-semibold">Loading knowledge base...</span>
                                    </div>
                               ) : listData.length === 0 ? (
                                    <div className="flex flex-col items-center justify-center border-2 border-dashed border-slate-800 bg-slate-900/30 rounded-3xl py-24">
                                        <div className="p-4 bg-slate-800 border border-slate-700 text-slate-400 rounded-2xl mb-5"><Icon name="book-open" className="w-8 h-8" /></div>
                                        <h4 className="text-base font-bold text-slate-200">No content yet</h4>
                                        <p className="text-sm text-slate-500 mt-1 max-w-sm text-center">Upload documents to build the knowledge base.</p>
                                    </div>
                                ) : (
                                    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl shadow-sm overflow-hidden backdrop-blur-sm">
                                        <div className="overflow-x-auto">
                                            {subTab === 'documents' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Document</th>
                                                            <th className="p-4 font-semibold">Who Can Access</th>
                                                            <th className="p-4 font-semibold">Uploaded On</th>
                                                            <th className="p-4 font-semibold">Chunked Status</th>
                                                            <th className="p-4 font-semibold">Status</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6">
                                                                    <div className="flex items-center gap-4">
                                                                        <div className="w-10 h-10 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-xl flex items-center justify-center shrink-0 shadow-sm"><Icon name="file-text" className="w-5 h-5" /></div>
                                                                        <div>
                                                                            <p className="font-bold text-slate-200 text-sm">{item.title}</p>
                                                                            <p className="text-xs text-slate-500 mt-0.5">{item.filename}</p>
                                                                        </div>
                                                                    </div>
                                                                </td>
                                                                <td className="p-4">
                                                                    <span className="text-[10px] font-bold tracking-widest px-2.5 py-1 bg-slate-800 text-slate-300 border border-slate-700/50 rounded-md uppercase">{item.access_level}</span>
                                                                </td>
                                                                <td className="p-4 text-xs font-mono text-slate-400">{item.uploaded_at}</td>
                                                                <td className="p-4">
                                                                    {item.is_chunked ? (
                                                                        <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full text-xs font-bold">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                                                                            Chunked
                                                                        </span>
                                                                    ) : (
                                                                        <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-full text-xs font-bold">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
                                                                            Processing
                                                                        </span>
                                                                    )}
                                                                </td>
                                                                <td className="p-4">
                                                                    <button onClick={() => handleToggleStatus(item)}
                                                                        className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold border transition-all ${item.is_active ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500 hover:text-white hover:border-emerald-500' : 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500 hover:text-white'}`}>
                                                                        <span className={`w-1.5 h-1.5 rounded-full ${item.is_active ? 'bg-emerald-400' : 'bg-red-400'}`}></span>
                                                                        {item.is_active ? 'Active' : 'Disabled'}
                                                                    </button>
                                                                </td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Document"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Remove Document"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}

                                            {subTab === 'chatbot-queries' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Question Asked</th>
                                                            <th className="p-4 font-semibold">Response</th>
                                                            <th className="p-4 w-36 font-semibold">Response Time</th>
                                                            <th className="p-4 pr-6 w-36 text-right font-semibold">Type</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors">
                                                                <td className="p-4 pl-6">
                                                                    <p className="font-bold text-slate-200 text-sm">{item.query_text}</p>
                                                                    <span className="text-[10px] text-slate-500 font-mono mt-1 block">{item.timestamp}</span>
                                                                </td>
                                                                <td className="p-4 text-xs text-slate-400 leading-relaxed max-w-lg">{item.response_text || "No response recorded."}</td>
                                                                <td className="p-4 text-xs font-mono text-indigo-400 font-semibold">{item.response_time_ms ? `${item.response_time_ms}ms` : 'N/A'}</td>
                                                                <td className="p-4 pr-6 text-right text-xs">
                                                                    {item.is_navigational
                                                                        ? <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 font-bold uppercase tracking-wider text-[10px]"><Icon name="map" className="w-3 h-3"/> Navigation</span>
                                                                        : <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 border border-slate-700/50 text-slate-400 font-bold uppercase tracking-wider text-[10px]"><Icon name="info" className="w-3 h-3"/> Information</span>}
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                        </div>
                                    </div>
                                )}
                                {renderPagination()}
                            </div>
                        )}

                        {/* ══ DEVICES & SECURITY (INFRA) ════════════════════ */}
                        {currentTab === "infra" && (
                            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out">
                                <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-4 mb-6">
                                    {["devices", "auth-logs", "jwt-sessions"].map(t => (
                                        <button key={t} onClick={() => setSubTab(t)}
                                            className={`px-5 py-2.5 rounded-xl text-sm font-bold transition-all duration-200 border ${subTab === t ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20 shadow-sm' : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-slate-200 hover:bg-slate-800/80 hover:border-slate-700'}`}>
                                            {subTabLabel(t)}
                                        </button>
                                    ))}
                                </div>

                                <SectionHeader
                                    title={subTab === 'devices' ? "Hardware Devices" : subTab === 'node-rbac' ? "Room Access Rules" : subTab === 'edge-rbac' ? "Path Access Rules" : subTab === 'auth-logs' ? "Access Logs" : "Active Sessions"}
                                    description={
                                        subTab === 'devices' ? "Monitor all IoT devices on the campus network." :
                                        subTab === 'node-rbac' ? "Control which roles can enter which rooms or locations." :
                                        subTab === 'edge-rbac' ? "Control which roles can use which paths between locations." :
                                        subTab === 'auth-logs' ? "History of all door/gate access attempts." :
                                        "View all currently active admin login sessions."
                                    }
                                    searchVal={subTab === 'devices' || subTab === 'auth-logs' ? searchQuery : undefined}
                                    onSearchChange={subTab === 'devices' || subTab === 'auth-logs' ? setSearchQuery : undefined}
                                    onCreateClick={['devices'].includes(subTab) ? () => { setSelectedItem(null); setModalType("create"); setShowModal(true); } : null}
                                    createLabel={subTab === 'devices' ? "Add Device" : "Create Rule"}
                                />

                                {listLoading ? (
                                    <div className="flex flex-col items-center justify-center py-24 text-slate-500 bg-slate-900/50 rounded-2xl border border-slate-800">
                                        <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-4"></div>
                                        <span className="text-sm font-semibold">Loading data...</span>
                                    </div>
                                ) : listData.length === 0 ? (
                                    <div className="flex flex-col items-center justify-center border-2 border-dashed border-slate-800 bg-slate-900/30 rounded-3xl py-24">
                                        <div className="p-4 bg-slate-800 border border-slate-700 text-slate-400 rounded-2xl mb-5"><Icon name="cpu" className="w-8 h-8" /></div>
                                        <h4 className="text-base font-bold text-slate-200">No records found</h4>
                                        <p className="text-sm text-slate-500 mt-1 max-w-sm text-center">Add devices or create access rules to get started.</p>
                                    </div>
                                ) : (
                                    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl shadow-sm overflow-hidden backdrop-blur-sm">
                                        <div className="overflow-x-auto">
                                            {subTab === 'devices' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Device</th>
                                                            <th className="p-4 font-semibold">IP Address</th>
                                                            <th className="p-4 font-semibold">Type</th>
                                                            <th className="p-4 font-semibold">Last Seen</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6">
                                                                    <div className="flex items-center gap-4">
                                                                        <div className="w-10 h-10 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-xl flex items-center justify-center shrink-0 shadow-sm"><Icon name="cpu" className="w-5 h-5" /></div>
                                                                        <div>
                                                                            <p className="font-bold text-slate-200 text-sm">{item.device_name}</p>
                                                                            <p className="text-xs font-mono text-slate-500 mt-0.5">{item.device_id}</p>
                                                                        </div>
                                                                    </div>
                                                                </td>
                                                                <td className="p-4 text-xs font-mono text-slate-400">{item.ip_address || 'N/A'}</td>
                                                                <td className="p-4">
                                                                    <span className="px-2.5 py-1 bg-slate-800 border border-slate-700/50 text-slate-300 rounded-md font-bold text-[10px] tracking-wider uppercase">{item.device_type}</span>
                                                                </td>
                                                                <td className="p-4">
                                                                    {(() => {
                                                                        if (!item.last_heartbeat) {
                                                                            return (
                                                                                <div className="inline-flex items-center gap-2 bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg">
                                                                                    <span className="w-2 h-2 rounded-full shrink-0 shadow-sm bg-red-500 shadow-red-500/50"></span>
                                                                                    <span className="text-xs font-semibold text-slate-300">Offline</span>
                                                                                </div>
                                                                            );
                                                                        }
                                                                        const lastSeenStr = item.last_heartbeat.endsWith('Z') ? item.last_heartbeat : item.last_heartbeat + 'Z';
                                                                        const dateObj = new Date(lastSeenStr);
                                                                        const isOnline = (() => {
                                                                            if (!item.is_active) return false;
                                                                            const diffMs = new Date() - dateObj;
                                                                            // 60 seconds threshold (1 minute)
                                                                            return diffMs >= 0 && diffMs <= 60000;
                                                                        })();
                                                                        const localTimeStr = `${String(dateObj.getHours()).padStart(2, '0')}:${String(dateObj.getMinutes()).padStart(2, '0')}`;
                                                                        return (
                                                                            <div className="inline-flex items-center gap-2 bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg">
                                                                                <span className={`w-2 h-2 rounded-full shrink-0 shadow-sm ${isOnline ? 'bg-emerald-400 shadow-emerald-500/50 animate-pulse' : 'bg-red-500 shadow-red-500/50'}`}></span>
                                                                                <span className="text-xs font-semibold text-slate-300">
                                                                                    {isOnline ? `Active ${localTimeStr}` : 'Offline'}
                                                                                </span>
                                                                            </div>
                                                                        );
                                                                    })()}
                                                                </td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => handlePingDevice(item)} disabled={pendingActionKey === `ping:${item.device_id}`} title="Ping Device" className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl border border-slate-700/50 transition-all hover:text-indigo-400 hover:border-indigo-500/30 disabled:opacity-50 disabled:cursor-not-allowed">
                                                                            {pendingActionKey === `ping:${item.device_id}` ? <span className="block w-4 h-4 border-2 border-indigo-400/30 border-t-indigo-400 rounded-full animate-spin"></span> : <Icon name="radio" className="w-4 h-4" />}
                                                                        </button>
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Device"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Remove Device"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'node-rbac' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Room / Location</th>
                                                            <th className="p-4 font-semibold">Allowed Role</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6 font-mono text-slate-200 text-sm font-bold">Node <span className="text-indigo-400">#{item.node_id}</span></td>
                                                                <td className="p-4">
                                                                    <span className="text-xs font-bold px-3 py-1 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-lg">
                                                                        {refs.roles.find(r => r.role_id === item.role_id)?.role_name || `Role #${item.role_id}`}
                                                                    </span>
                                                                </td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <button onClick={() => handleDeleteItem(item)} title="Remove Rule"
                                                                        className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all opacity-0 group-hover:opacity-100">
                                                                        <Icon name="trash-2" className="w-4 h-4" />
                                                                    </button>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'edge-rbac' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Path / Route</th>
                                                            <th className="p-4 font-semibold">Allowed Role</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6 font-mono text-slate-200 text-sm font-bold">Path <span className="text-indigo-400">#{item.edge_id}</span></td>
                                                                <td className="p-4">
                                                                    <span className="text-xs font-bold px-3 py-1 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-lg">
                                                                        {refs.roles.find(r => r.role_id === item.role_id)?.role_name || `Role #${item.role_id}`}
                                                                    </span>
                                                                </td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <button onClick={() => handleDeleteItem(item)} title="Remove Rule"
                                                                        className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all opacity-0 group-hover:opacity-100">
                                                                        <Icon name="trash-2" className="w-4 h-4" />
                                                                    </button>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'auth-logs' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">User</th>
                                                            <th className="p-4 font-semibold">Device</th>
                                                            <th className="p-4 font-semibold">Result</th>
                                                            <th className="p-4 pr-6 font-semibold">When</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors">
                                                                <td className="p-4 pl-6 font-mono text-slate-200 text-sm font-semibold">{item.username || "Unknown"}</td>
                                                                <td className="p-4 text-xs font-mono text-slate-500">{item.device_id || "—"}</td>
                                                                <td className="p-4 text-xs font-bold">
                                                                    {(item.auth_status === 'SUCCESS' || item.auth_status === 'GRANTED')
                                                                        ? <span className="inline-flex items-center gap-1.5 text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-3 py-1 rounded-lg"><Icon name="check-circle" className="w-3.5 h-3.5"/> {item.auth_status}</span>
                                                                        : <span className="inline-flex items-center gap-1.5 text-red-400 bg-red-500/10 border border-red-500/20 px-3 py-1 rounded-lg"><Icon name="x-circle" className="w-3.5 h-3.5"/> {item.auth_status}</span>}
                                                                </td>
                                                                <td className="p-4 pr-6 text-xs text-slate-400 font-mono">{item.timestamp || item.created_at || "—"}</td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'jwt-sessions' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Admin User</th>
                                                            <th className="p-4 font-semibold">IP Address</th>
                                                            <th className="p-4 font-semibold">Expires</th>
                                                            <th className="p-4 pr-6 font-semibold">Status</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors">
                                                                <td className="p-4 pl-6 font-mono text-slate-200 text-sm font-bold"><Icon name="shield" className="inline-block w-4 h-4 mr-2 text-indigo-400"/>{item.user?.username || item.admin_id || "—"}</td>
                                                                <td className="p-4 text-xs font-mono text-slate-500">{item.ip_address || "—"}</td>
                                                                <td className="p-4 text-xs font-mono text-slate-400">{item.expires_at}</td>
                                                                <td className="p-4 pr-6 text-xs font-bold">
                                                                    {item.is_revoked
                                                                        ? <span className="inline-flex items-center gap-1.5 text-red-400 bg-red-500/10 border border-red-500/20 px-3 py-1 rounded-lg"><Icon name="x-circle" className="w-3.5 h-3.5"/> Revoked</span>
                                                                        : <span className="inline-flex items-center gap-1.5 text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-3 py-1 rounded-lg"><Icon name="check-circle" className="w-3.5 h-3.5"/> Active</span>}
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                        </div>
                                    </div>
                                )}
                                {renderPagination()}
                            </div>
                        )}

                        {/* ══ SCHEDULING (ACADEMICS) ════════════════════════ */}
                        {currentTab === "academics" && (
                            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out">
                                <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-4 mb-6">
                                    {["courses", "enrollments", "timetables", "faculties", "departments", "programmes", "appointments", "notifications"].map(t => (
                                        <button key={t} onClick={() => setSubTab(t)}
                                            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all duration-200 border ${subTab === t ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20 shadow-sm' : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-slate-200 hover:bg-slate-800/80 hover:border-slate-700'}`}>
                                            {subTabLabel(t)}
                                        </button>
                                    ))}
                                </div>

                                <SectionHeader
                                    title={subTabLabel(subTab)}
                                    description={
                                        subTab === 'courses' ? "Manage the course catalog and academic programs." :
                                        subTab === 'enrollments' ? "View and manage student course enrollments." :
                                        subTab === 'timetables' ? "Schedule class sessions and manage time slots." :
                                        subTab === 'appointments' ? "Manage student-lecturer appointment bookings." :
                                        "System notification announcements sent to users."
                                    }
                                    onCreateClick={subTab !== "notifications" ? () => { setSelectedItem(null); setModalType("create"); setShowModal(true); } : null}
                                    createLabel={`Add ${subTabLabel(subTab).replace(/s$/, '')}`}
                                />

                                {listLoading ? (
                                    <div className="flex flex-col items-center justify-center py-24 text-slate-500 bg-slate-900/50 rounded-2xl border border-slate-800">
                                        <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-4"></div>
                                        <span className="text-sm font-semibold">Loading scheduling data...</span>
                                    </div>
                                ) : listData.length === 0 ? (
                                    <div className="flex flex-col items-center justify-center border-2 border-dashed border-slate-800 bg-slate-900/30 rounded-3xl py-24">
                                        <div className="p-4 bg-slate-800 border border-slate-700 text-slate-400 rounded-2xl mb-5"><Icon name="calendar" className="w-8 h-8" /></div>
                                        <h4 className="text-base font-bold text-slate-200">No records found</h4>
                                        <p className="text-sm text-slate-500 mt-1 max-w-sm text-center">Add items to get started.</p>
                                    </div>
                                ) : (
                                    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl shadow-sm overflow-hidden backdrop-blur-sm">
                                        <div className="overflow-x-auto">
                                            {subTab === 'courses' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Course Name</th>
                                                            <th className="p-4 font-semibold">Credits</th>
                                                            <th className="p-4 font-semibold">Level</th>
                                                            <th className="p-4 font-semibold">Faculty</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6">
                                                                    <p className="font-bold text-slate-200 text-sm">{item.course_name}</p>
                                                                    <p className="text-xs font-mono text-indigo-400 mt-0.5">{item.course_code}</p>
                                                                </td>
                                                                <td className="p-4 font-mono text-slate-400 text-xs font-semibold">{item.credit_hours} cr.</td>
                                                                <td className="p-4">
                                                                    <span className="px-2.5 py-1 bg-slate-800 border border-slate-700/50 text-slate-300 rounded-md text-[10px] font-bold tracking-widest uppercase">{item.course_level}</span>
                                                                </td>
                                                                <td className="p-4 text-xs text-slate-400 font-medium">{item.faculty}</td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Course"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Remove Course"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'enrollments' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Student ID</th>
                                                            <th className="p-4 font-semibold">Course</th>
                                                            <th className="p-4 font-semibold">Semester</th>
                                                            <th className="p-4 font-semibold">Status</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6 font-mono font-bold text-slate-200 text-sm">{item.student_id}</td>
                                                                <td className="p-4 text-xs font-semibold text-slate-400">Course <span className="text-indigo-400">#{item.course_id}</span></td>
                                                                <td className="p-4 text-xs font-medium text-slate-400">{item.semester} ({item.academic_year})</td>
                                                                <td className="p-4 text-xs">
                                                                    <span className="px-3 py-1 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-lg font-bold tracking-wider uppercase text-[10px]">{item.status}</span>
                                                                </td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Enrollment"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Remove Enrollment"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'timetables' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Course</th>
                                                            <th className="p-4 font-semibold">Lecturer</th>
                                                            <th className="p-4 font-semibold">Day &amp; Time</th>
                                                            <th className="p-4 font-semibold">Room</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6 font-mono text-slate-200 text-sm font-semibold">Course <span className="text-indigo-400">#{item.course_id}</span></td>
                                                                <td className="p-4 text-xs font-mono text-slate-400">{item.lecturer_id}</td>
                                                                <td className="p-4">
                                                                    <div className="flex flex-col">
                                                                        <span className="font-bold text-slate-200 text-xs tracking-wider uppercase">{item.day_of_week}</span>
                                                                        <span className="text-slate-500 font-mono text-[10px] mt-0.5">{item.start_time} – {item.end_time}</span>
                                                                    </div>
                                                                </td>
                                                                <td className="p-4 text-xs font-mono font-semibold text-slate-300">Node <span className="text-emerald-400">#{item.node_id}</span></td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Timetable"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Remove Timetable"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'appointments' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Guest</th>
                                                            <th className="p-4 font-semibold">Host</th>
                                                            <th className="p-4 font-semibold">Scheduled</th>
                                                            <th className="p-4 font-semibold">Status</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6 font-mono font-bold text-slate-200 text-sm">User <span className="text-indigo-400">#{item.guest_user_id}</span></td>
                                                                <td className="p-4 text-xs font-mono font-semibold text-slate-400">User <span className="text-emerald-400">#{item.host_user_id}</span></td>
                                                                <td className="p-4 text-xs font-medium text-slate-300">{item.scheduled_at} <span className="text-slate-500 ml-1">({item.duration_minutes}m)</span></td>
                                                                <td className="p-4">
                                                                    <span className={`px-2.5 py-1 rounded-md text-[10px] font-bold tracking-wider uppercase border ${
                                                                        item.status === 'CONFIRMED' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                                                                        item.status === 'PENDING' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' :
                                                                        'bg-slate-800 text-slate-400 border-slate-700/50'
                                                                    }`}>{item.status}</span>
                                                                </td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Appointment"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Cancel Appointment"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'notifications' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Title</th>
                                                            <th className="p-4 font-semibold">Message</th>
                                                            <th className="p-4 pr-6 font-semibold">Sent</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors">
                                                                <td className="p-4 pl-6 font-bold text-slate-200">{item.title}</td>
                                                                <td className="p-4 text-xs font-medium text-slate-400">{item.body}</td>
                                                                <td className="p-4 pr-6 text-xs font-mono text-slate-500">{item.sent_at}</td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'faculties' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Faculty ID</th>
                                                            <th className="p-4 font-semibold">Faculty Name</th>
                                                            <th className="p-4 font-semibold">Dean ID</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6 font-mono font-bold text-indigo-400 text-sm">FAC <span className="text-slate-300">#{item.faculty_id}</span></td>
                                                                <td className="p-4 text-sm font-semibold text-slate-200">{item.faculty_name}</td>
                                                                <td className="p-4 text-xs font-mono font-semibold text-slate-400">User <span className="text-emerald-400">#{item.dean_id}</span></td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Faculty"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Remove Faculty"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'departments' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Department ID</th>
                                                            <th className="p-4 font-semibold">Department Name</th>
                                                            <th className="p-4 font-semibold">Manager ID</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6 font-mono font-bold text-indigo-400 text-sm">DEPT <span className="text-slate-300">#{item.department_id}</span></td>
                                                                <td className="p-4 text-sm font-semibold text-slate-200">{item.department_name}</td>
                                                                <td className="p-4 text-xs font-mono font-semibold text-slate-400">User <span className="text-emerald-400">#{item.manager_id}</span></td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Department"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Remove Department"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                            {subTab === 'programmes' && (
                                                <table className="w-full text-left text-sm">
                                                    <thead>
                                                        <tr className="bg-slate-800/50 text-slate-400 font-bold text-xs tracking-wider uppercase border-b-2 border-slate-800/80">
                                                            <th className="p-4 pl-6 font-semibold">Programme ID</th>
                                                            <th className="p-4 font-semibold">Programme Name</th>
                                                            <th className="p-4 font-semibold">Faculty ID</th>
                                                            <th className="p-4 font-semibold">HOP ID</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6 font-mono font-bold text-indigo-400 text-sm">PROG <span className="text-slate-300">#{item.programme_id}</span></td>
                                                                <td className="p-4 text-sm font-semibold text-slate-200">{item.programme_name}</td>
                                                                <td className="p-4 text-xs font-mono font-semibold text-slate-400">FAC <span className="text-emerald-400">#{item.faculty_id}</span></td>
                                                                <td className="p-4 text-xs font-mono font-semibold text-slate-400">User <span className="text-emerald-400">#{item.hop_id}</span></td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Programme"
                                                                            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="edit-3" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => handleDeleteItem(item)} title="Remove Programme"
                                                                            className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                            <Icon name="trash-2" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            )}
                                        </div>
                                    </div>
                                )}
                                {renderPagination()}
                            </div>
                        )}

                        {/* ══ CAMPUS MAP ════════════════════════════════════ */}
                        {currentTab === "mapping" && (
                            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out space-y-7">
                                <div>
                                    <h1 className="text-2xl font-extrabold text-slate-100 tracking-tight">Campus Map</h1>
                                    <p className="text-slate-400 text-sm mt-1">Interactive campus layout with access zones and live navigation paths.</p>
                                </div>
                                <div className="flex flex-col items-center justify-center bg-slate-900/50 border-2 border-dashed border-slate-800 rounded-3xl py-32 text-center px-8 shadow-inner">
                                    <div className="p-6 bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 rounded-3xl mb-6 shadow-lg shadow-indigo-500/5">
                                        <Icon name="map" className="w-12 h-12" />
                                    </div>
                                    <h3 className="text-xl font-bold text-slate-200">Interactive Map — Coming Soon</h3>
                                    <p className="text-slate-500 text-sm max-w-md mt-3 leading-relaxed">
                                        The campus map module is under development. It will display building floorplans, IoT device locations, room access zones, and real-time navigation.
                                    </p>
                                    <div className="mt-8 inline-flex items-center gap-2.5 text-xs bg-slate-900/80 border border-slate-700 text-indigo-400 font-mono px-5 py-2.5 rounded-full shadow-sm">
                                        <span className="w-2.5 h-2.5 rounded-full bg-indigo-400 animate-ping"></span>
                                        <span className="font-semibold tracking-wide">Integration in progress...</span>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* ══ MODAL: CREATE / EDIT ══════════════════════════ */}
                        {showModal && (
                            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-md p-4 overflow-y-auto animate-in fade-in duration-200">
                                <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl p-6 md:p-8 shadow-2xl relative my-4 animate-in zoom-in-95 duration-200 ease-out">
                                    <div className="flex justify-between items-start mb-6">
                                        <div>
                                            <h3 className="text-xl font-bold text-slate-100 tracking-tight">
                                                {modalType === "create" ? "Add New Record" : "Edit Record"}
                                            </h3>
                                            <p className="text-xs text-slate-400 mt-1">Fill in the details below and save your changes.</p>
                                        </div>
                                        <button onClick={() => setShowModal(false)} disabled={formSubmitting}
                                            className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-xl transition-all ml-4 shrink-0 bg-slate-900/50 border border-transparent hover:border-slate-700 disabled:opacity-50 disabled:cursor-not-allowed">
                                            <Icon name="x" className="w-5 h-5" />
                                        </button>
                                    </div>
                                    <div className="max-h-[70vh] overflow-y-auto pr-2 custom-scrollbar">
                                        {renderModalForm()}
                                    </div>
                                    {formSubmitting && (
                                        <div className="absolute inset-0 bg-slate-950/70 backdrop-blur-sm rounded-3xl flex flex-col items-center justify-center gap-3 z-10">
                                            <div className="w-10 h-10 border-4 border-emerald-400/30 border-t-emerald-400 rounded-full animate-spin"></div>
                                            <p className="text-sm font-bold text-slate-100">Saving changes...</p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* ══ MODAL: FACE ID ENROLLMENT ═════════════════════ */}
                        {showFaceModal && selectedItem && (
                            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-md p-4 overflow-y-auto animate-in fade-in duration-200">
                                <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl p-6 md:p-8 shadow-2xl relative overflow-hidden my-4 animate-in zoom-in-95 duration-200 ease-out">
                                    <style>{`
                                        @keyframes scanline-anim {
                                            0% { top: 0%; }
                                            50% { top: 100%; }
                                            100% { top: 0%; }
                                        }
                                        .scanner-scanline {
                                            position: absolute;
                                            left: 0; right: 0; height: 2px;
                                            background: rgba(99, 102, 241, 0.8);
                                            box-shadow: 0 0 10px rgba(99, 102, 241, 0.8);
                                            animation: scanline-anim 2.5s linear infinite;
                                        }
                                    `}</style>

                                    <div className="flex justify-between items-start mb-6">
                                        <div>
                                            <h3 className="text-xl font-bold text-slate-100 tracking-tight">Face ID Enrollment</h3>
                                            <p className="text-xs text-slate-400 mt-1">Setting up for: <span className="text-indigo-400 font-semibold">{selectedItem.full_name}</span></p>
                                        </div>
                                        <button onClick={() => {
                                            stopCamera(); setShowFaceModal(false); setScanning(false);
                                            setScanStep(0); setConfidence(0); setSelectedPhotoFile(null);
                                            setSelectedVideoFile(null); setVideoError("");
                                            setEmbeddingProgress(0); setRecordingProgress(0); setRecordingPhase('idle');
                                            if (uploadedPhoto) { URL.revokeObjectURL(uploadedPhoto); setUploadedPhoto(null); }
                                        }} className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-xl transition-all ml-4 shrink-0 bg-slate-900/50 border border-transparent hover:border-slate-700">
                                            <Icon name="x" className="w-5 h-5" />
                                        </button>
                                    </div>

                                    {/* Method picker */}
                                    <div className="flex bg-slate-950 p-1 rounded-xl mb-6 border border-slate-800 shadow-inner">
                                        {[{ id: "photo", label: "📷 Photo" }, { id: "live", label: "🎥 Live Camera" }, { id: "video", label: "🎞️ Video" }].map(m => (
                                            <button key={m.id} onClick={() => {
                                                stopCamera(); setEnrollMethod(m.id);
                                                setScanStep(0); setConfidence(0); setSelectedPhotoFile(null);
                                                setSelectedVideoFile(null); setVideoError("");
                                                setEmbeddingProgress(0); setRecordingProgress(0); setRecordingPhase('idle');
                                            }} className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all ${enrollMethod === m.id ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-500 hover:text-slate-200 hover:bg-slate-900'}`}>
                                                {m.label}
                                            </button>
                                        ))}
                                    </div>

                                    {/* PHOTO UPLOAD */}
                                    {enrollMethod === "photo" && (
                                        <div className="space-y-5">
                                            <div className="relative aspect-video bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden flex items-center justify-center shadow-inner">
                                                {uploadedPhoto && <img src={uploadedPhoto} className="absolute inset-0 w-full h-full object-cover opacity-60" alt="Face" />}
                                                <div className="absolute top-3 left-3 flex items-center gap-1.5 bg-slate-900/80 border border-slate-800 px-2.5 py-1 rounded-lg text-[10px] font-bold">
                                                    {scanning ? (
                                                        <><span className="w-2 h-2 rounded-full bg-indigo-500 animate-ping"></span><span className="text-indigo-400">ANALYZING...</span></>
                                                    ) : (
                                                        <><span className="w-2 h-2 rounded-full bg-emerald-500"></span><span className="text-emerald-400">READY</span></>
                                                    )}
                                                </div>
                                                <div className="absolute inset-8 border border-transparent pointer-events-none">
                                                    <div className="absolute top-0 left-0 w-6 h-6 border-t-2 border-l-2 border-indigo-500/70"></div>
                                                    <div className="absolute top-0 right-0 w-6 h-6 border-t-2 border-r-2 border-indigo-500/70"></div>
                                                    <div className="absolute bottom-0 left-0 w-6 h-6 border-b-2 border-l-2 border-indigo-500/70"></div>
                                                    <div className="absolute bottom-0 right-0 w-6 h-6 border-b-2 border-r-2 border-indigo-500/70"></div>
                                                </div>
                                                {scanning && <div className="scanner-scanline"></div>}
                                                <div className="text-slate-800 flex flex-col items-center">
                                                    {scanStep === 2 ? (
                                                        <div className="p-4 bg-emerald-600/10 border border-emerald-500/20 text-emerald-400 rounded-full animate-bounce">
                                                            <Icon name="check" className="w-10 h-10" />
                                                        </div>
                                                    ) : (
                                                        <Icon name="user" className={`w-16 h-16 ${scanning ? 'text-indigo-500/40 animate-pulse' : 'text-slate-800'}`} />
                                                    )}
                                                </div>
                                                {scanning && <div className="absolute bottom-3 right-3 bg-slate-900/80 border border-slate-800 px-2 py-1 rounded-lg font-mono text-xs text-indigo-400 font-bold">{confidence}%</div>}
                                            </div>

                                            {scanStep === 0 && (
                                                <label className="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-3 px-4 rounded-xl transition-all flex justify-center items-center gap-2 cursor-pointer text-sm shadow-md shadow-indigo-900/20">
                                                    <Icon name="upload" className="w-4 h-4" />
                                                    <span>Choose Face Photo</span>
                                                    <input type="file" accept="image/*" className="hidden" onChange={handlePhotoUpload} />
                                                </label>
                                            )}
                                            {scanStep === 1 && (
                                                <div className="space-y-3">
                                                    <div className="w-full bg-slate-950 h-2 rounded-full overflow-hidden border border-slate-800 shadow-inner">
                                                        <div className="bg-indigo-500 h-full transition-all duration-300" style={{ width: `${confidence}%` }}></div>
                                                    </div>
                                                    <div className="bg-slate-950 rounded-xl p-3 border border-slate-800 font-mono text-[10px] text-slate-500 h-28 overflow-y-auto space-y-1 custom-scrollbar">
                                                        {scanLogs.map((log, lIdx) => (
                                                            <div key={lIdx} className="flex gap-1.5 items-start">
                                                                <span className="text-indigo-500 shrink-0">&gt;</span>
                                                                <span className={lIdx === scanLogs.length - 1 ? "text-slate-100 font-semibold" : ""}>{log}</span>
                                                            </div>
                                                        ))}
                                                        <div ref={logEndRef}></div>
                                                    </div>
                                                </div>
                                            )}
                                            {scanStep === 2 && (
                                                <div className="space-y-4">
                                                    <div className="p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-2xl text-center">
                                                        <h4 className="text-sm font-bold text-emerald-400 mb-1">✓ Analysis Complete</h4>
                                                        <p className="text-xs text-slate-400">Face data is ready to save.</p>
                                                    </div>
                                                    <div className="flex gap-3">
                                                        <label className="flex-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-bold py-2.5 px-4 rounded-xl transition-all text-sm cursor-pointer text-center flex justify-center items-center gap-1.5 shadow-sm">
                                                            <Icon name="upload" className="w-3.5 h-3.5" />
                                                            <span>Try Another</span>
                                                            <input type="file" accept="image/*" className="hidden" onChange={handlePhotoUpload} />
                                                        </label>
                                                        <button type="button" onClick={() => saveFacialEnrollment()}
                                                            className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2.5 px-4 rounded-xl transition-all text-sm flex justify-center items-center gap-1.5 shadow-md shadow-indigo-900/20">
                                                            <Icon name="check" className="w-4 h-4" />
                                                            <span>Save Face ID</span>
                                                        </button>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {/* LIVE CAMERA — guided recording flow */}
                                    {enrollMethod === "live" && (() => {
                                        // High-contrast SVG arrow: double-stroke (dark outline + white fill)
                                        // visible on ANY background color
                                        const ArrowSVG = ({ direction, size = 72 }) => {
                                            const style = {
                                                filter: 'drop-shadow(0 0 6px rgba(0,0,0,0.7))',
                                                animation: 'arrowPulse 0.9s ease-in-out infinite',
                                                display: 'block',
                                            };
                                            const paths = {
                                                left:  'M58 36H22M22 36L40 18M22 36L40 54',
                                                right: 'M22 36H58M58 36L40 18M58 36L40 54',
                                                up:    'M36 58V22M36 22L18 40M36 22L54 40',
                                                down:  'M36 22V58M36 58L18 40M36 58L54 40',
                                            };
                                            if (direction === null) return (
                                                <svg width={size} height={size} viewBox='0 0 72 72' fill='none' style={style}>
                                                    <circle cx='36' cy='36' r='20' stroke='black' strokeWidth='7' strokeDasharray='9 5'/>
                                                    <circle cx='36' cy='36' r='20' stroke='white' strokeWidth='4' strokeDasharray='9 5'/>
                                                    <circle cx='36' cy='36' r='7' fill='black'/>
                                                    <circle cx='36' cy='36' r='4' fill='white'/>
                                                </svg>
                                            );
                                            const d = paths[direction];
                                            if (!d) return null;
                                            return (
                                                <svg width={size} height={size} viewBox='0 0 72 72' fill='none' style={style}>
                                                    {/* Dark outline — visible on light/white backgrounds */}
                                                    <path d={d} stroke='black' strokeWidth='12' strokeLinecap='round' strokeLinejoin='round'/>
                                                    {/* White inner — visible on dark backgrounds */}
                                                    <path d={d} stroke='white' strokeWidth='6' strokeLinecap='round' strokeLinejoin='round'/>
                                                </svg>
                                            );
                                        };

                                        const positionClass = (dir) => ({
                                            left:  'absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none',
                                            right: 'absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none',
                                            up:    'absolute top-2 left-1/2 -translate-x-1/2 pointer-events-none',
                                            down:  'absolute bottom-16 left-1/2 -translate-x-1/2 pointer-events-none',
                                        }[dir] || 'absolute inset-0 flex items-center justify-center pointer-events-none');

                                        const curPose = GUIDE_POSES[guidePoseIndex] || GUIDE_POSES[0];
                                        const phaseProgress = recordingPhase === 'embedding' ? embeddingProgress : recordingProgress;

                                        return (
                                            <div className='space-y-4'>
                                                <style>{`
                                                    @keyframes arrowPulse {
                                                        0%,100% { opacity:1; transform:scale(1); }
                                                        50% { opacity:0.45; transform:scale(0.82); }
                                                    }
                                                    @keyframes countdownPop {
                                                        0% { transform:scale(2); opacity:0; }
                                                        100% { transform:scale(1); opacity:1; }
                                                    }
                                                `}</style>

                                                {/* ── Camera viewport ── */}
                                                <div className='relative bg-black rounded-2xl border border-slate-800 overflow-hidden shadow-inner' style={{aspectRatio:'16/9'}}>

                                                    {/* Camera feed */}
                                                    {cameraStream
                                                        ? <video ref={videoRef} autoPlay playsInline muted className='absolute inset-0 w-full h-full object-cover -scale-x-100'/>
                                                        : <div className='absolute inset-0 flex flex-col items-center justify-center text-slate-700 gap-2'>
                                                            <Icon name='camera' className='w-14 h-14 opacity-50'/>
                                                            <p className='text-xs font-semibold'>Camera preview</p>
                                                          </div>
                                                    }
                                                    <canvas ref={canvasRef} style={{display:'none'}} width={640} height={480}/>

                                                    {/* Corner brackets */}
                                                    {cameraStream && (
                                                        <div className='absolute inset-8 pointer-events-none'>
                                                            <div className='absolute top-0 left-0 w-8 h-8 border-t-[3px] border-l-[3px] border-white/70'></div>
                                                            <div className='absolute top-0 right-0 w-8 h-8 border-t-[3px] border-r-[3px] border-white/70'></div>
                                                            <div className='absolute bottom-0 left-0 w-8 h-8 border-b-[3px] border-l-[3px] border-white/70'></div>
                                                            <div className='absolute bottom-0 right-0 w-8 h-8 border-b-[3px] border-r-[3px] border-white/70'></div>
                                                        </div>
                                                    )}

                                                    {/* ── Countdown overlay ── */}
                                                    {recordingPhase === 'countdown' && (
                                                        <div className='absolute inset-0 bg-black/60 flex items-center justify-center pointer-events-none'>
                                                            <div key={recordingCountdown} className='text-white font-black text-8xl'
                                                                style={{animation:'countdownPop 0.4s ease-out forwards'}}>
                                                                {recordingCountdown}
                                                            </div>
                                                        </div>
                                                    )}

                                                    {/* ── Processing overlay ── */}
                                                    {recordingPhase === 'embedding' && (
                                                        <div className='absolute inset-0 bg-black/70 flex flex-col items-center justify-center gap-4 pointer-events-none'>
                                                            <div className='w-12 h-12 border-4 border-indigo-400 border-t-transparent rounded-full animate-spin'></div>
                                                            <p className='text-white font-bold text-sm'>Embedding Face ID...</p>
                                                            <p className='text-slate-400 text-xs'>{embeddingProgress}% complete</p>
                                                        </div>
                                                    )}

                                                    {/* ── Success overlay ── */}
                                                    {recordingPhase === 'success' && (
                                                        <div className='absolute inset-0 bg-emerald-950/80 flex flex-col items-center justify-center gap-3 pointer-events-none'>
                                                            <div className='w-16 h-16 bg-emerald-500/20 border-2 border-emerald-500 rounded-full flex items-center justify-center shadow-lg shadow-emerald-500/20'>
                                                                <Icon name='check' className='w-8 h-8 text-emerald-400'/>
                                                            </div>
                                                            <p className='text-emerald-300 font-bold text-sm'>Face ID Enrolled!</p>
                                                        </div>
                                                    )}

                                                    {/* ── Directional arrow (shown only during recording) ── */}
                                                    {recordingPhase === 'recording' && cameraStream && (
                                                        curPose.dir !== null
                                                            ? <div className={positionClass(curPose.dir)}><ArrowSVG direction={curPose.dir}/></div>
                                                            : <div className='absolute inset-0 flex items-center justify-center pointer-events-none'><ArrowSVG direction={null}/></div>
                                                    )}

                                                    {/* ── Instruction banner (shown when recording) ── */}
                                                    {recordingPhase === 'recording' && cameraStream && (
                                                        <div className='absolute bottom-3 left-3 right-3 pointer-events-none'>
                                                            <div className='bg-black/75 border border-white/15 backdrop-blur-md rounded-xl px-3 py-2 text-center shadow-lg'>
                                                                <p className='text-sm font-bold text-white tracking-wide'>{curPose.label}</p>
                                                            </div>
                                                        </div>
                                                    )}

                                                    {/* ── LIVE / STANDBY badge ── */}
                                                    <div className='absolute top-3 left-3 flex items-center gap-1.5 bg-black/70 border border-white/10 px-2.5 py-1 rounded-lg text-[10px] font-bold'>
                                                        {recordingPhase === 'recording'
                                                            ? <><span className='w-2 h-2 rounded-full bg-red-500 animate-ping'></span><span className='text-red-400'>REC</span></>
                                                            : cameraStream
                                                                ? <><span className='w-2 h-2 rounded-full bg-emerald-500'></span><span className='text-emerald-400'>READY</span></>
                                                                : <><span className='w-2 h-2 rounded-full bg-slate-600'></span><span className='text-slate-400'>NO CAMERA</span></>
                                                        }
                                                    </div>
                                                </div>

                                                {/* ── Recording progress bar ── */}
                                                {(recordingPhase === 'recording' || recordingPhase === 'embedding') && (
                                                    <div className='space-y-1.5'>
                                                        <div className='flex justify-between text-[10px] font-mono font-bold text-slate-500'>
                                                            <span>{recordingPhase === 'embedding' ? 'Embedding Face ID...' : 'Recording in progress...'}</span>
                                                            <span>{phaseProgress}%</span>
                                                        </div>
                                                        <div className='w-full h-2 bg-slate-900 rounded-full overflow-hidden border border-slate-800 shadow-inner'>
                                                            <div className='h-full bg-gradient-to-r from-indigo-500 to-red-500 transition-all duration-200 rounded-full'
                                                                style={{width:`${phaseProgress}%`}}></div>
                                                        </div>
                                                    </div>
                                                )}

                                                {/* ── Pose step progress dots (idle/ready state) ── */}
                                                {(recordingPhase === 'idle' || recordingPhase === 'failed') && cameraStream && (
                                                    <div className='bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-3 shadow-inner'>
                                                        <p className='text-xs font-bold text-slate-400 uppercase tracking-wider'>Motion sequence to follow</p>
                                                        <div className='flex items-center gap-1.5'>
                                                            {GUIDE_POSES.map((p, i) => {
                                                                const sym = {left:'←',right:'→',up:'↑',down:'↓'}[p.dir] || '●';
                                                                return (
                                                                    <div key={i} title={p.label}
                                                                        className='flex-1 h-8 rounded-lg flex items-center justify-center text-sm font-bold bg-slate-900 border border-slate-800 text-slate-400 shadow-sm'>
                                                                        {sym}
                                                                    </div>
                                                                );
                                                            })}
                                                        </div>
                                                        <p className='text-xs text-slate-500 leading-relaxed'>
                                                            When you press Record, follow the arrows on screen — turn your head slowly left, then right, then look up and gently down. The whole thing takes about 10 seconds.
                                                        </p>
                                                    </div>
                                                )}

                                                {/* ── Error / failed feedback ── */}
                                                {recordingPhase === 'failed' && enrollFeedback && (
                                                    <div className='flex items-start gap-3 bg-red-950/40 border border-red-900/40 rounded-2xl p-4 shadow-sm'>
                                                        <Icon name='alert-circle' className='w-4 h-4 text-red-400 shrink-0 mt-0.5'/>
                                                        <div>
                                                            <p className='text-sm font-bold text-red-400'>Enrollment failed</p>
                                                            <p className='text-xs text-red-400/80 mt-0.5 leading-relaxed'>{enrollFeedback}</p>
                                                            <p className='text-xs text-slate-500 mt-1.5'>Try again — move your head more slowly and keep your face well-lit.</p>
                                                        </div>
                                                    </div>
                                                )}

                                                {/* ── Action buttons ── */}
                                                <div className='flex gap-3'>
                                                    {!cameraStream ? (
                                                        <button type='button' onClick={startCamera}
                                                            className='flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-3 px-4 rounded-xl transition-all text-sm flex justify-center items-center gap-2 shadow-md shadow-indigo-900/20'>
                                                            <Icon name='camera' className='w-4 h-4'/><span>Enable Camera</span>
                                                        </button>
                                                    ) : recordingPhase === 'idle' || recordingPhase === 'failed' ? (
                                                        <>
                                                            <button type='button' onClick={stopCamera}
                                                                className='bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 font-bold py-3 px-4 rounded-xl transition-all text-sm flex justify-center items-center gap-2 shadow-sm'>
                                                                <Icon name='video-off' className='w-4 h-4'/>
                                                            </button>
                                                            <button type='button' onClick={startGuidedRecording}
                                                                className='flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-3 px-4 rounded-xl transition-all text-sm flex justify-center items-center gap-2 shadow-lg shadow-indigo-900/30'>
                                                                <Icon name='circle' className='w-3.5 h-3.5 fill-red-400 text-red-400'/>
                                                                <span>{recordingPhase === 'failed' ? 'Record Again' : 'Start Recording'}</span>
                                                            </button>
                                                        </>
                                                    ) : recordingPhase === 'countdown' ? (
                                                        <div className='flex-1 bg-slate-900 border border-slate-800 rounded-xl py-3 text-center text-sm font-bold text-slate-400 shadow-inner'>Get ready...</div>
                                                    ) : recordingPhase === 'recording' ? (
                                                        <button type='button' onClick={() => {
                                                            guidedCaptureRef.current.active = false;
                                                            setRecordingPhase('failed');
                                                            setEnrollFeedback('Capture stopped before enrollment completed.');
                                                        }} className='flex-1 bg-red-600 hover:bg-red-500 text-white font-bold py-3 px-4 rounded-xl transition-all text-sm flex justify-center items-center gap-2 shadow-md shadow-red-900/20'>
                                                            <Icon name='square' className='w-3.5 h-3.5 fill-white'/><span>Stop Early</span>
                                                        </button>
                                                    ) : null}
                                                </div>
                                            </div>
                                        );
                                    })()}


                                    {/* VIDEO UPLOAD */}
                                    {enrollMethod === "video" && (
                                        <div className="space-y-5">
                                            <div className="border-2 border-dashed border-slate-700/60 rounded-2xl p-8 text-center bg-slate-950/40 shadow-inner">
                                                <Icon name="video" className="w-12 h-12 mx-auto text-slate-600 mb-4" />
                                                <p className="text-sm text-slate-400 mb-5">Upload a short video slowly rotating your head</p>
                                                <label className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white font-bold px-5 py-2.5 rounded-xl cursor-pointer text-sm transition-all shadow-md shadow-indigo-900/20">
                                                    <Icon name="upload" className="w-4 h-4" />
                                                    <span>{selectedVideoFile ? selectedVideoFile.name : "Choose Video File"}</span>
                                                    <input type="file" accept="video/*" className="hidden" onChange={handleVideoFileChange} />
                                                </label>
                                            </div>
                                            {videoError && (
                                                <div className="flex items-center gap-2 text-red-400 text-xs bg-red-950/40 border border-red-900/40 rounded-xl px-4 py-3 shadow-sm">
                                                    <Icon name="alert-circle" className="w-4 h-4 shrink-0" />
                                                    <span>{videoError}</span>
                                                </div>
                                            )}
                                            <button type="button" onClick={uploadVideoEnrollment} disabled={!selectedVideoFile || videoProcessing}
                                                className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 disabled:cursor-not-allowed text-white font-bold py-3 px-4 rounded-xl transition-all text-sm flex justify-center items-center gap-2 shadow-md disabled:shadow-none">
                                                {videoProcessing ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div> : <Icon name="upload" className="w-4 h-4" />}
                                                <span>{videoProcessing ? "Processing video..." : "Process & Enroll"}</span>
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                    </div>
                        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
                    </main>
                </div>
            </div>
        );
    }
