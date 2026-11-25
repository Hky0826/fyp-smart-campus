const { useState, useEffect, useRef, useMemo } = React;

const DASHBOARD_SUB_TABS = {
    iam: ["users", "roles", "facial-recognition"],
    rag: ["documents", "chatbot-queries", "adaptation-phrases", "speech-languages"],
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

function CampusMapTab() {
    return (
        <div className="w-full h-[calc(100vh-6rem)] rounded-2xl overflow-hidden border border-slate-800 bg-slate-950 shadow-2xl">
            <iframe
                src="/static/vite/index.html"
                className="w-full h-full border-none"
                title="Campus Map Editor"
            />
        </div>
    );
}

// ============================================================
// MAIN APP COMPONENT
// ============================================================
        function App() {
            const initialRoute = useMemo(() => readDashboardRoute(), []);
            // ── Core auth state ──────────────────────────────
            const [token, setToken] = useState("");
            const [authChecked, setAuthChecked] = useState(false);
            const [adminType, setAdminType] = useState(localStorage.getItem("admin_type") || "");
            const [email, setEmail] = useState(localStorage.getItem("email") || "");
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
            const [loginEmail, setLoginEmail] = useState("");
            const [loginPass, setLoginPass] = useState("");
            const [loginLoading, setLoginLoading] = useState(false);
            const [loginError, setLoginError] = useState("");

            // Authentication is cookie-based. The state value is only a
            // non-secret UI flag; the JWT stays in the HttpOnly cookie.
            useEffect(() => {
                let active = true;
                fetch("/api/auth/me", { credentials: "include" })
                    .then(async response => {
                        if (!response.ok) throw new Error("Not authenticated");
                        return response.json();
                    })
                    .then(admin => {
                        if (!active) return;
                        localStorage.setItem("admin_type", admin.admin_type || "");
                        localStorage.setItem("email", admin.user?.email || admin.email || "");
                        localStorage.setItem("full_name", admin.user?.full_name || admin.full_name || "");
                        localStorage.setItem("admin_id", String(admin.admin_id || ""));
                        setAdminType(admin.admin_type || "");
                        setEmail(admin.user?.email || admin.email || "");
                        setFullName(admin.user?.full_name || admin.full_name || "");
                        setAdminId(admin.admin_id || "");
                        setToken("cookie-authenticated");
                    })
                    .catch(() => {
                        if (active) setToken("");
                    })
                    .finally(() => {
                        if (active) setAuthChecked(true);
                    });
                return () => { active = false; };
            }, []);

            // ── Dashboard data ────────────────────────────────
            const [dashboardStats, setDashboardStats] = useState({
                users: 0, active_users: 0, inactive_users: 0, face_enrolled_users: 0,
                devices: 0, online_devices: 0, offline_devices: 0,
                documents: 0, courses: 0,
                active_sessions: 0, auth_attempts_24h: 0, auth_failures_24h: 0, db_latency_ms: 0
            });
            const [listData, setListData] = useState([]);
            const [listLoading, setListLoading] = useState(false);
            const [searchQuery, setSearchQuery] = useState("");
            const [debouncedSearch, setDebouncedSearch] = useState("");
            const searchInputRef = useRef(null);

            // ── Filter state ──────────────────────────────────
            const [roleFilter, setRoleFilter] = useState("ALL");
            const [statusFilter, setStatusFilter] = useState("ALL");
            const [userFaceFilter, setUserFaceFilter] = useState("ALL");
            const [facultyFilter, setFacultyFilter] = useState("ALL");
            const [departmentFilter, setDepartmentFilter] = useState("ALL");
            const [accessLevelFilter, setAccessLevelFilter] = useState("ALL");
            const [categoryFilter, setCategoryFilter] = useState("ALL");
            const [faceStatusFilter, setFaceStatusFilter] = useState("ALL");
            const [faceRoleFilter, setFaceRoleFilter] = useState("ALL");
            const [speechLanguages, setSpeechLanguages] = useState([]);
            const [adaptationCategories, setAdaptationCategories] = useState([]);

            // ── Scalable directory, inspector drawer, bulk & UX state ──
            const [serverPagination, setServerPagination] = useState({ total: 0, page: 1, page_size: 25, total_pages: 1 });
            const [userSummary, setUserSummary] = useState({ total_users: 0, active_users: 0, inactive_users: 0, face_enrolled_users: 0 });
            const [selectedUserIds, setSelectedUserIds] = useState([]);
            const [bulkRoleId, setBulkRoleId] = useState("");
            const [bulkBusy, setBulkBusy] = useState(false);
            const [drawerState, setDrawerState] = useState({ record: null, kind: "" });
            const [confirmState, setConfirmState] = useState({ open: false, title: "", message: "", confirmLabel: "Confirm", variant: "danger", onConfirm: null });
            const [tableDensity, setTableDensity] = useState(localStorage.getItem("dashboard_table_density") || "comfortable");
            const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
            const [jumpPageInput, setJumpPageInput] = useState("");

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
            const [photoPose, setPhotoPose] = useState("front");
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
            const [provisioningDetails, setProvisioningDetails] = useState(null);

            // ── Sorting & Pagination ──────────────────────────
            const [sortKey, setSortKey] = useState("");
            const [sortOrder, setSortOrder] = useState("asc");
            const [currentPage, setCurrentPage] = useState(1);
            const [itemsPerPage, setItemsPerPage] = useState(() => {
                const saved = parseInt(localStorage.getItem("dashboard_page_size") || "25", 10);
                return [10, 25, 50, 100].includes(saved) ? saved : 25;
            });

            const isServerPaginatedUsers = currentTab === "iam" && (subTab === "users" || subTab === "facial-recognition");

            useEffect(() => {
                localStorage.setItem("dashboard_table_density", tableDensity);
            }, [tableDensity]);

            useEffect(() => {
                localStorage.setItem("dashboard_page_size", String(itemsPerPage));
            }, [itemsPerPage]);

            useEffect(() => {
                const timer = setTimeout(() => setDebouncedSearch(searchQuery), 220);
                return () => clearTimeout(timer);
            }, [searchQuery]);

            useEffect(() => {
                const onKeyDown = (e) => {
                    if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
                        if (searchInputRef.current) {
                            e.preventDefault();
                            searchInputRef.current.focus();
                        }
                    } else if (e.key === "Escape") {
                        if (confirmState.open) setConfirmState(prev => ({ ...prev, open: false }));
                        else if (drawerState.record) setDrawerState({ record: null, kind: "" });
                        else if (showModal) setShowModal(false);
                        else if (mobileSidebarOpen) setMobileSidebarOpen(false);
                    }
                };
                window.addEventListener("keydown", onKeyDown);
                return () => window.removeEventListener("keydown", onKeyDown);
            }, [confirmState.open, drawerState.record, showModal, mobileSidebarOpen]);

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
                'adaptation-phrases': 'Acronyms & Translations',
                'speech-languages': 'Supported Languages',
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

            const getSingleTabLabel = (t) => {
                if (t === 'faculties') return 'Faculty';
                if (t === 'categories') return 'Category';
                const label = subTabLabel(t);
                if (label.endsWith('ies')) return label.replace(/ies$/, 'y');
                if (label.endsWith('s')) return label.replace(/s$/, '');
                return label;
            };

            // ── Lucide icon refresh ───────────────────────────
            useEffect(() => { if (window.lucide) window.lucide.createIcons(); }, [currentTab, subTab, listData, showModal, showFaceModal, toast]);

            // ── Auto-scroll scan logs ─────────────────────────
            useEffect(() => { if (logEndRef.current) logEndRef.current.scrollIntoView({ behavior: 'smooth' }); }, [scanLogs]);

            // ── Helpers ───────────────────────────────────────
            const showErrorToast = (msg) => setToast({ message: msg, type: 'error' });
            const showSuccessToast = (msg) => setToast({ message: msg, type: 'success' });

            const parseTranslations = (desc) => {
                if (!desc) return [];
                try {
                    const parsed = JSON.parse(desc);
                    if (Array.isArray(parsed)) {
                        return parsed.filter(t => t && (t.text || typeof t === 'string')).map(t => {
                            if (typeof t === 'string') return { lang: 'en', text: t };
                            return { lang: t.lang || 'en', text: t.text || '' };
                        });
                    }
                    if (typeof parsed === 'object' && parsed !== null) {
                        return Object.entries(parsed).map(([lang, text]) => ({ lang, text: String(text) }));
                    }
                } catch (e) {
                    return [{ lang: 'en', text: desc }];
                }
                return [];
            };

            const getLangBadge = (lang) => {
                const l = (lang || 'en').toLowerCase();
                const map = {
                    'en': { name: 'English', cls: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30' },
                    'ms': { name: 'Bahasa Melayu', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
                    'zh': { name: 'Chinese', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
                    'ta': { name: 'Tamil', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
                    'yue': { name: 'Cantonese', cls: 'bg-purple-500/15 text-purple-300 border-purple-500/30' },
                    'ar': { name: 'Arabic', cls: 'bg-teal-500/15 text-teal-300 border-teal-500/30' }
                };
                return map[l] || { name: l.toUpperCase(), cls: 'bg-slate-800 text-slate-300 border-slate-700' };
            };

            const getRecordKey = (item, tab = currentTab, activeSubTab = subTab) => {
                if (!item) return "";
                const keyMap = {
                    iam: { users: "user_id", roles: "role_id", "facial-recognition": "user_id" },
                    rag: { documents: "document_id", "chatbot-queries": "query_id", "adaptation-phrases": "phrase_id", "speech-languages": "language_code" },
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
                    formData.append("email", loginEmail);
                    formData.append("password", loginPass);
                    const response = await fetch("/api/auth/login", {
                        method: "POST",
                        headers: { "Content-Type": "application/x-www-form-urlencoded" },
                        body: formData
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Authentication failed. Please check your credentials.");
                    localStorage.setItem("admin_type", data.admin_type);
                    localStorage.setItem("email", data.email);
                    localStorage.setItem("full_name", data.full_name);
                    localStorage.setItem("admin_id", data.admin_id);
                    setToken("cookie-authenticated");
                    setAdminType(data.admin_type);
                    setEmail(data.email);
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
                setToken(""); setAdminType(""); setEmail(""); setFullName(""); setAdminId("");
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
                        active_users: Number(data.active_users) || 0,
                        inactive_users: Number(data.inactive_users) || 0,
                        face_enrolled_users: Number(data.face_enrolled_users) || 0,
                        devices: Number(data.devices) || 0,
                        online_devices: Number(data.online_devices) || 0,
                        offline_devices: Number(data.offline_devices) || 0,
                        documents: Number(data.documents) || 0,
                        courses: Number(data.courses) || 0,
                        active_sessions: Number(data.active_sessions) || 0,
                        auth_attempts_24h: Number(data.auth_attempts_24h) || 0,
                        auth_failures_24h: Number(data.auth_failures_24h) || 0,
                        db_latency_ms: Number(data.db_latency_ms) || 0
                    });
                } catch (err) { console.error("Overview stats failed:", err); }
            };

            // ── Fetch current tab data ────────────────────────
            const fetchTabData = async (overrides = {}) => {
                if (!token) return;
                const requestId = ++tabRequestIdRef.current;
                setListLoading(true);
                try {
                    const headers = { "Authorization": `Bearer ${token}` };
                    if (currentTab === "iam" && (subTab === "users" || subTab === "facial-recognition")) {
                        const params = new URLSearchParams();
                        params.set("page", String(overrides.page ?? currentPage));
                        params.set("page_size", String(overrides.page_size ?? itemsPerPage));
                        const qVal = (overrides.q ?? debouncedSearch ?? "").trim();
                        if (qVal) params.set("q", qVal);
                        const activeRole = subTab === "facial-recognition" ? faceRoleFilter : roleFilter;
                        if (activeRole && activeRole !== "ALL") params.set("role_id", String(activeRole));
                        if (subTab === "users" && statusFilter !== "ALL") params.set("status", statusFilter);
                        const activeFace = subTab === "facial-recognition" ? faceStatusFilter : userFaceFilter;
                        if (activeFace && activeFace !== "ALL") params.set("face_status", activeFace);
                        if (subTab === "users" && facultyFilter !== "ALL") params.set("faculty_id", facultyFilter);
                        if (subTab === "users" && departmentFilter !== "ALL") params.set("department_id", departmentFilter);
                        if (sortKey) {
                            params.set("sort_by", sortKey);
                            params.set("sort_order", sortOrder);
                        }
                        const response = await fetch(`/api/iam/users/paginated?${params.toString()}`, { headers });
                        const data = await response.json();
                        if (!response.ok) throw new Error(data.detail || "Failed to load users.");
                        if (requestId === tabRequestIdRef.current) {
                            setListData(Array.isArray(data.items) ? data.items : []);
                            setServerPagination({
                                total: Number(data.total) || 0,
                                page: Number(data.page) || 1,
                                page_size: Number(data.page_size) || itemsPerPage,
                                total_pages: Number(data.total_pages) || 1
                            });
                            if (data.summary) setUserSummary(data.summary);
                        }
                        return;
                    }

                    const endpointMap = {
                        iam: { roles: "/api/iam/roles" },
                        rag: { documents: "/api/rag/documents", "chatbot-queries": "/api/rag/chatbot-queries", "adaptation-phrases": "/api/rag/adaptation-phrases", "speech-languages": "/api/rag/speech-languages" },
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

            // ── Fetch speech languages & categories ──────────
            const fetchSpeechLanguages = async () => {
                if (!token) return;
                try {
                    const res = await fetch("/api/rag/speech-languages", { headers: { "Authorization": `Bearer ${token}` } });
                    if (res.ok) {
                        const data = await res.json();
                        setSpeechLanguages(Array.isArray(data) ? data : []);
                    }
                } catch (e) {
                    console.error("Failed to load speech languages", e);
                }
            };

            const fetchAdaptationCategories = async () => {
                if (!token) return;
                try {
                    const res = await fetch("/api/rag/adaptation-phrases/categories", { headers: { "Authorization": `Bearer ${token}` } });
                    if (res.ok) {
                        const data = await res.json();
                        setAdaptationCategories(Array.isArray(data) ? data : []);
                    }
                } catch (e) {
                    console.error("Failed to load adaptation categories", e);
                }
            };

            const handleToggleLanguageDefault = async (code) => {
                try {
                    const res = await fetch(`/api/rag/speech-languages/${code}/toggle-default`, {
                        method: "POST",
                        headers: { "Authorization": `Bearer ${token}` }
                    });
                    if (!res.ok) {
                        const d = await res.json();
                        throw new Error(d.detail || "Failed to toggle default language status.");
                    }
                    showSuccessToast("Default language status updated.");
                    await fetchSpeechLanguages();
                    if (currentTab === "rag" && subTab === "speech-languages") await fetchTabData();
                } catch (err) {
                    showErrorToast(err.message);
                }
            };

            const handleToggleLanguageActive = async (code) => {
                try {
                    const res = await fetch(`/api/rag/speech-languages/${code}/toggle-active`, {
                        method: "POST",
                        headers: { "Authorization": `Bearer ${token}` }
                    });
                    if (!res.ok) {
                        const d = await res.json();
                        throw new Error(d.detail || "Failed to toggle language active status.");
                    }
                    showSuccessToast("Language active status updated.");
                    await fetchSpeechLanguages();
                    if (currentTab === "rag" && subTab === "speech-languages") await fetchTabData();
                } catch (err) {
                    showErrorToast(err.message);
                }
            };

            // ── Effects: data loading ─────────────────────────
            useEffect(() => {
                if (token) {
                    fetchReferences();
                    if (currentTab === "overview") fetchOverviewStats();
                    else if (!isServerPaginatedUsers && (subTab || !DASHBOARD_DEFAULT_SUB_TAB[currentTab])) {
                        fetchTabData();
                        if (currentTab === "rag" && subTab === "adaptation-phrases") {
                            fetchSpeechLanguages();
                            fetchAdaptationCategories();
                        }
                    }
                }
            }, [token, currentTab, subTab]);

            useEffect(() => {
                if (token && isServerPaginatedUsers) {
                    fetchTabData();
                }
            }, [
                token, isServerPaginatedUsers, subTab, currentPage, itemsPerPage,
                debouncedSearch, roleFilter, statusFilter, userFaceFilter,
                faceStatusFilter, faceRoleFilter, facultyFilter, departmentFilter,
                sortKey, sortOrder
            ]);

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
                setSearchQuery(""); setDebouncedSearch("");
                setRoleFilter("ALL"); setStatusFilter("ALL"); setUserFaceFilter("ALL");
                setFacultyFilter("ALL"); setDepartmentFilter("ALL");
                setAccessLevelFilter("ALL"); setCategoryFilter("ALL");
                setFaceStatusFilter("ALL"); setFaceRoleFilter("ALL");
                setSortKey(""); setSortOrder("asc");
                setSelectedUserIds([]); setDrawerState({ record: null, kind: "" });
                setMobileSidebarOpen(false);
            }, [currentTab, subTab]);

            // ── Reset pagination on filter change ─────────────
            useEffect(() => {
                setCurrentPage(1);
                setSelectedUserIds([]);
            }, [debouncedSearch, currentTab, subTab, roleFilter, statusFilter, userFaceFilter, facultyFilter, departmentFilter, accessLevelFilter, categoryFilter, faceStatusFilter, faceRoleFilter, itemsPerPage]);

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
                    } else if (currentTab === "rag") {
                        if (subTab === "documents") {
                            endpoint = modalType === "create" ? "/api/rag/documents" : `/api/rag/documents/${selectedItem.document_id}`;
                            method = modalType === "create" ? "POST" : "PUT"; finalBody = payload;
                        } else if (subTab === "adaptation-phrases") {
                            endpoint = modalType === "create" ? "/api/rag/adaptation-phrases" : `/api/rag/adaptation-phrases/${selectedItem.phrase_id}`;
                            method = modalType === "create" ? "POST" : "PUT"; finalBody = payload;
                        } else if (subTab === "speech-languages") {
                            endpoint = "/api/rag/speech-languages";
                            method = "POST";
                            finalBody = payload;
                        }
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
                    if (currentTab === "infra" && subTab === "devices" && modalType === "create" && (savedRecord?.pairing_code || savedRecord?.provisioned_secret)) {
                        setProvisioningDetails({
                            deviceId: savedRecord.device_id,
                            deviceName: savedRecord.device_name,
                            secret: savedRecord.provisioned_secret || "",
                            ipAddress: savedRecord.ip_address || "Auto (Outbound Sync)",
                            pairingCode: savedRecord.pairing_code || "",
                            pairingExpiresAt: savedRecord.pairing_expires_at || "",
                            pairingQrSvgDataUri: savedRecord.pairing_qr_svg_data_uri || "",
                            paired: false,
                            showManualSecret: false,
                        });
                    }
                    refreshAfterMutation({ refreshRefs: currentTab === "academics" && ["faculties", "departments", "programmes"].includes(subTab) });

                    if (currentTab === "iam" && subTab === "users" && modalType === "create" && createdUser) {
                        setSelectedItem(createdUser);
                        setConfidence(0); setScanStep(0); setScanning(false);
                        setUploadedPhoto(null); setSelectedPhotoFile(null);
                        setPhotoPose("front");
                        setEnrollMethod("video");
                        setShowFaceModal(true);
                    }
                } catch (err) { showErrorToast(err.message); }
                finally { setFormSubmitting(false); }
            };

            // ── Delete ────────────────────────────────────────
            const executeDeleteItem = async (item) => {
                const actionKey = `delete:${getRecordKey(item)}`;
                if (pendingActionKey) return;
                setPendingActionKey(actionKey);
                try {
                    const headers = { "Authorization": `Bearer ${token}` };
                    const epMap = {
                        iam: { users: `/api/iam/users/${item.user_id}`, roles: `/api/iam/roles/${item.role_id}` },
                        rag: { documents: `/api/rag/documents/${item.document_id}`, "adaptation-phrases": `/api/rag/adaptation-phrases/${item.phrase_id}`, "speech-languages": `/api/rag/speech-languages/${item.language_code}` },
                        infra: { devices: `/api/infra/devices/${item.device_id}`, "node-rbac": `/api/infra/node-rbac/${item.node_id}/${item.role_id}`, "edge-rbac": `/api/infra/edge-rbac/${item.edge_id}/${item.role_id}` },
                        academics: { courses: `/api/academics/courses/${item.course_id}`, enrollments: `/api/academics/enrollments/${item.enrollment_id}`, timetables: `/api/academics/timetables/${item.timetable_id}`, appointments: `/api/academics/appointments/${item.appointment_id}`, faculties: `/api/refs/faculties/${item.faculty_id}`, departments: `/api/refs/departments/${item.department_id}`, programmes: `/api/refs/programmes/${item.programme_id}` }
                    };
                    const endpoint = epMap[currentTab]?.[subTab];
                    if (!endpoint) return;
                    const response = await fetch(endpoint, { method: "DELETE", headers });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Delete failed.");
                    if (data.deactivated) {
                        showSuccessToast(data.detail || "Device deactivated; audit history was preserved.");
                    } else {
                        removeRecordFromList(item);
                        showSuccessToast("Record deleted successfully.");
                    }
                    setDrawerState(prev => (prev.record && getRecordKey(prev.record) === getRecordKey(item)) ? { record: null, kind: "" } : prev);
                    refreshAfterMutation({ refreshRefs: currentTab === "academics" && ["faculties", "departments", "programmes"].includes(subTab) });
                } catch (err) { showErrorToast(err.message); }
                finally { setPendingActionKey(""); }
            };

            const handleDeleteItem = (item) => {
                const label = item.full_name || item.device_name || item.title || item.course_name || item.role_name || getRecordKey(item) || "this record";
                setConfirmState({
                    open: true,
                    title: "Delete Record",
                    message: `Are you sure you want to permanently delete "${label}"? This action cannot be undone.`,
                    confirmLabel: "Delete",
                    variant: "danger",
                    onConfirm: async () => {
                        setConfirmState(prev => ({ ...prev, open: false }));
                        await executeDeleteItem(item);
                    }
                });
            };

            // ── Bulk User Actions & CSV Export ────────────────
            const toggleSelectUser = (userId) => {
                setSelectedUserIds(prev => prev.includes(userId) ? prev.filter(id => id !== userId) : [...prev, userId]);
            };

            const toggleSelectAllPageUsers = () => {
                const pageIds = paginatedData.map(u => u.user_id).filter(Boolean);
                const allSelected = pageIds.length > 0 && pageIds.every(id => selectedUserIds.includes(id));
                if (allSelected) {
                    setSelectedUserIds(prev => prev.filter(id => !pageIds.includes(id)));
                } else {
                    setSelectedUserIds(prev => Array.from(new Set([...prev, ...pageIds])));
                }
            };

            const handleBulkUserStatus = async (isActive) => {
                if (selectedUserIds.length === 0 || bulkBusy) return;
                setBulkBusy(true);
                try {
                    const res = await fetch("/api/iam/users/bulk-status", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ user_ids: selectedUserIds, is_active: isActive })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || "Bulk status update failed.");
                    showSuccessToast(data.detail || "Users updated.");
                    setSelectedUserIds([]);
                    await fetchTabData();
                } catch (err) {
                    showErrorToast(err.message);
                } finally {
                    setBulkBusy(false);
                }
            };

            const handleBulkUserRole = async () => {
                if (selectedUserIds.length === 0 || !bulkRoleId || bulkBusy) return;
                setBulkBusy(true);
                try {
                    const res = await fetch("/api/iam/users/bulk-role", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ user_ids: selectedUserIds, role_id: parseInt(bulkRoleId, 10), mode: "add" })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || "Bulk role assignment failed.");
                    showSuccessToast(data.detail || "Roles assigned.");
                    setBulkRoleId("");
                    setSelectedUserIds([]);
                    await fetchTabData();
                } catch (err) {
                    showErrorToast(err.message);
                } finally {
                    setBulkBusy(false);
                }
            };

            const handleBulkUserDelete = () => {
                if (selectedUserIds.length === 0 || bulkBusy) return;
                const count = selectedUserIds.length;
                setConfirmState({
                    open: true,
                    title: `Delete ${count} User${count > 1 ? "s" : ""}`,
                    message: `This will permanently remove ${count} selected user account${count > 1 ? "s" : ""} and associated biometric profiles. This cannot be undone.`,
                    confirmLabel: `Delete ${count} User${count > 1 ? "s" : ""}`,
                    variant: "danger",
                    onConfirm: async () => {
                        setConfirmState(prev => ({ ...prev, open: false }));
                        setBulkBusy(true);
                        try {
                            const res = await fetch("/api/iam/users/bulk-delete", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ user_ids: selectedUserIds })
                            });
                            const data = await res.json();
                            if (!res.ok) throw new Error(data.detail || "Bulk delete failed.");
                            showSuccessToast(data.detail || "Selected users deleted.");
                            setSelectedUserIds([]);
                            await fetchTabData();
                        } catch (err) {
                            showErrorToast(err.message);
                        } finally {
                            setBulkBusy(false);
                        }
                    }
                });
            };

            const handleExportUsersCsv = () => {
                const sourceRows = selectedUserIds.length > 0
                    ? paginatedData.filter(u => selectedUserIds.includes(u.user_id))
                    : paginatedData;
                if (sourceRows.length === 0) {
                    showErrorToast("No user rows to export.");
                    return;
                }
                const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
                const header = ["User ID", "Full Name", "Email", "Roles", "Status", "Face Enrolled", "Identity ID", "Enrolled At"];
                const rows = sourceRows.map(u => {
                    const idCode = u.student?.student_id || u.lecturer?.lecturer_id || u.staff?.staff_id || u.visitor?.id_number || u.admin?.admin_id || "";
                    const roleNames = (u.roles || []).map(r => r.role_name).join("; ");
                    return [u.user_id, u.full_name, u.email, roleNames, u.is_active ? "Active" : "Deactivated", u.face_enrolled ? "Yes" : "No", idCode, u.enrolled_at || ""].map(esc).join(",");
                });
                const blob = new Blob([[header.map(esc).join(","), ...rows].join("\n")], { type: "text/csv;charset=utf-8;" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `smart-campus-users-page${pageToRender}.csv`;
                a.click();
                URL.revokeObjectURL(url);
                showSuccessToast(`Exported ${sourceRows.length} user record(s) to CSV.`);
            };

            const handleRevokeUserSession = async (sessionId, userId) => {
                try {
                    const res = await fetch(`/api/infra/jwt-sessions/${sessionId}`, { method: "DELETE" });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error(data.detail || "Failed to revoke session.");
                    showSuccessToast("Session revoked.");
                    setDrawerState(prev => prev.record && prev.record.user_id === userId ? { ...prev, record: { ...prev.record } } : prev);
                } catch (err) {
                    showErrorToast(err.message);
                }
            };

            // ── Toggle active status ──────────────────────────
            const handleToggleStatus = async (item) => {
                const actionKey = `toggle:${getRecordKey(item)}`;
                if (pendingActionKey) return;
                setPendingActionKey(actionKey);
                try {
                    const headers = { "Authorization": `Bearer ${token}` };
                    const epMap = {
                        iam: { users: `/api/iam/users/${item.user_id}/toggle-active` },
                        rag: {
                            documents: `/api/rag/documents/${item.document_id}/toggle-active`,
                            "adaptation-phrases": `/api/rag/adaptation-phrases/${item.phrase_id}/toggle-active`
                        }
                    };
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

            const handleIssuePairingCode = async (item) => {
                const actionKey = `pair:${item.device_id}`;
                if (pendingActionKey) return;
                setPendingActionKey(actionKey);
                try {
                    const response = await fetch(`/api/infra/devices/${item.device_id}/pairing-code`, {
                        method: "POST",
                        headers: { "Authorization": `Bearer ${token}` }
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Failed to generate pairing code.");
                    setProvisioningDetails({
                        deviceId: data.device_id,
                        deviceName: data.device_name,
                        secret: "",
                        ipAddress: data.ip_address || "Auto (Outbound Sync)",
                        pairingCode: data.pairing_code || "",
                        pairingExpiresAt: data.pairing_expires_at || "",
                        pairingQrSvgDataUri: data.pairing_qr_svg_data_uri || "",
                        paired: false,
                        showManualSecret: false,
                    });
                } catch (err) {
                    showErrorToast(err.message);
                } finally {
                    setPendingActionKey("");
                }
            };

            useEffect(() => {
                if (!provisioningDetails || !provisioningDetails.deviceId || provisioningDetails.paired) return;
                let cancelled = false;
                const pollStatus = async () => {
                    try {
                        const res = await fetch(`/api/infra/devices/${provisioningDetails.deviceId}`, {
                            headers: { "Authorization": `Bearer ${token}` }
                        });
                        if (!res.ok || cancelled) return;
                        const data = await res.json();
                        if (data.pairing_claimed_at && !cancelled) {
                            setProvisioningDetails(prev => prev ? { ...prev, paired: true } : prev);
                            mergeRecordIntoList(data);
                            showSuccessToast(`Device "${data.device_name}" paired and online!`);
                        }
                    } catch (_) {}
                };
                const timer = setInterval(pollStatus, 2500);
                return () => { cancelled = true; clearInterval(timer); };
            }, [provisioningDetails?.deviceId, provisioningDetails?.paired, token]);

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
                    const formData = new FormData();
                    formData.append("file", selectedPhotoFile);
                    formData.append("pose", photoPose);
                    const response = await fetch(`/api/iam/users/${selectedItem.user_id}/upload-photo`, {
                        method: "POST", headers: { "Authorization": `Bearer ${token}` }, body: formData
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || "Failed to save Face ID.");
                    showSuccessToast(`Face ID ${photoPose === "front" ? "photo" : `${photoPose} pose`} updated for ${selectedItem.full_name}!`);
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

            // ── Single front camera capture flow ───────────────────────
            const GUIDE_POSES = [
                { id: 'front',       dir: null,    label: 'Face the camera — stay still' }
            ];

            const startCamera = async () => {
                try {
                    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                        throw new Error("Camera access is restricted by your browser. Ensure you are accessing via HTTPS or http://localhost, and browser permissions are granted.");
                    }
                    let stream;
                    try {
                        stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 } } });
                    } catch (e1) {
                        stream = await navigator.mediaDevices.getUserMedia({ video: true });
                    }
                    setCameraStream(stream);
                    setRecordingPhase('idle');
                    setGuidePoseIndex(0);
                    setEnrollFeedback('');
                    setRecordingProgress(0);
                    setEmbeddingProgress(0);
                    if (videoRef.current) {
                        videoRef.current.srcObject = stream;
                        videoRef.current.play().catch(e => console.warn("Video play exception:", e));
                    }
                } catch (err) {
                    setRecordingPhase('failed');
                    let hint = "";
                    if (err.name === "NotAllowedError" || (err.message && err.message.toLowerCase().includes("permission"))) {
                        hint = " Recommended Checks:\n1. Windows Settings -> Privacy & security -> Camera -> Enable 'Allow desktop apps to access your camera'.\n2. Ensure no other application (Zoom, Teams, Python script, OpenCV, OBS) is currently using your webcam.";
                    }
                    setEnrollFeedback(`Could not access camera (${err.name || 'Error'}): ${err.message || 'Permission denied'}.${hint}`);
                }
            };

            const completeLiveEnrollment = async () => {
                setRecordingPhase('embedding');
                setEmbeddingProgress(0);
                setEnrollFeedback('');

                let progressTimer;
                const pollProgress = async () => {
                    try {
                        const res = await fetch(`/api/iam/users/${selectedItem.user_id}/enroll-live/progress`, {
                            headers: { "Authorization": `Bearer ${token}` }
                        });
                        if (res.ok) {
                            const data = await res.json();
                            if (data.progress !== undefined) {
                                setEmbeddingProgress(data.progress);
                            }
                        }
                    } catch (err) {
                        console.error("Error polling progress:", err);
                    }
                };

                pollProgress();
                progressTimer = setInterval(pollProgress, 250);

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
                            const mQ = q === "" || item.full_name?.toLowerCase().includes(q) || item.email?.toLowerCase().includes(q) || String(item.user_id).includes(q);
                            const mR = faceRoleFilter === "ALL" || userHasRole(item, faceRoleFilter);
                            const mS = faceStatusFilter === "ALL" || (faceStatusFilter === "ENROLLED" ? !!item.face_vector : !item.face_vector);
                            return mQ && mR && mS;
                        }
                        if (subTab === "users") {
                            const mQ = q === "" || item.full_name?.toLowerCase().includes(q) || item.email?.toLowerCase().includes(q) || String(item.user_id).includes(q) || item.student?.student_id?.toLowerCase().includes(q) || item.lecturer?.lecturer_id?.toLowerCase().includes(q) || item.staff?.staff_id?.toLowerCase().includes(q);
                            const mR = roleFilter === "ALL" || userHasRole(item, roleFilter);
                            const mS = statusFilter === "ALL" || (statusFilter === "ACTIVE" ? item.is_active : !item.is_active);
                            return mQ && mR && mS;
                        }
                    }
                    if (currentTab === "rag") {
                        if (subTab === "documents") {
                            const matchesQuery = q === "" || item.title?.toLowerCase().includes(q) || item.filename?.toLowerCase().includes(q);
                            const roles = (item.allowed_roles && item.allowed_roles.length > 0)
                                ? item.allowed_roles
                                : (item.access_level === "PUBLIC" ? ["VISITOR"] : [item.access_level || "VISITOR"]);
                            const isUniversal = roles.includes("VISITOR") || roles.includes("PUBLIC");
                            const matchesRole = accessLevelFilter === "ALL"
                                || (accessLevelFilter === "VISITOR" && isUniversal)
                                || (roles.includes(accessLevelFilter))
                                || (isUniversal);
                            return matchesQuery && matchesRole;
                        }
                        if (subTab === "chunks") {
                            const matchesQuery = q === "" || item.chunk_text?.toLowerCase().includes(q);
                            const roles = (item.allowed_roles && item.allowed_roles.length > 0)
                                ? item.allowed_roles
                                : (item.access_level === "PUBLIC" ? ["VISITOR"] : [item.access_level || "VISITOR"]);
                            const isUniversal = roles.includes("VISITOR") || roles.includes("PUBLIC");
                            const matchesRole = accessLevelFilter === "ALL"
                                || (accessLevelFilter === "VISITOR" && isUniversal)
                                || (roles.includes(accessLevelFilter))
                                || (isUniversal);
                            return matchesQuery && matchesRole;
                        }
                        if (subTab === "chatbot-queries") {
                            const matchesQuery = q === "" 
                                || item.query_text?.toLowerCase().includes(q)
                                || item.response_text?.toLowerCase().includes(q)
                                || item.user_name?.toLowerCase().includes(q)
                                || item.user_email?.toLowerCase().includes(q);
                            const matchesRole = roleFilter === "ALL" 
                                || (item.user_role?.toUpperCase() === roleFilter.toUpperCase())
                                || (roleFilter === "VISITOR" && (!item.user_role || item.user_role === "VISITOR"));
                            const matchesNav = accessLevelFilter === "ALL"
                                || (accessLevelFilter === "NAV" && item.is_navigational)
                                || (accessLevelFilter === "INFO" && !item.is_navigational);
                            return matchesQuery && matchesRole && matchesNav;
                        }
                        if (subTab === "adaptation-phrases") {
                            return q === "" 
                                || item.phrase?.toLowerCase().includes(q)
                                || item.description?.toLowerCase().includes(q);
                        }
                        if (subTab === "speech-languages") {
                            return q === "" 
                                || item.language_name?.toLowerCase().includes(q)
                                || item.language_code?.toLowerCase().includes(q);
                        }
                    }
                    if (currentTab === "infra") {
                        if (subTab === "devices") return q === "" || item.device_name?.toLowerCase().includes(q) || item.device_id?.toLowerCase().includes(q);
                        if (subTab === "auth-logs") return q === "" || item.email?.toLowerCase().includes(q) || item.auth_status?.toLowerCase().includes(q);
                        if (subTab === "jwt-sessions") return q === "" || item.user?.email?.toLowerCase().includes(q) || item.ip_address?.toLowerCase().includes(q);
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
                () => isServerPaginatedUsers ? listData : getFilteredSortedData(),
                [isServerPaginatedUsers, listData, searchQuery, currentTab, subTab, roleFilter, statusFilter, accessLevelFilter, faceStatusFilter, faceRoleFilter, sortKey, sortOrder]
            );
            const totalItems = isServerPaginatedUsers ? serverPagination.total : processedData.length;
            const totalPages = isServerPaginatedUsers ? Math.max(1, serverPagination.total_pages) : (Math.ceil(totalItems / itemsPerPage) || 1);
            const pageToRender = Math.min(currentPage, totalPages);
            const startIndex = (pageToRender - 1) * itemsPerPage;
            const paginatedData = isServerPaginatedUsers ? listData : processedData.slice(startIndex, startIndex + itemsPerPage);

            const handleJumpToPage = (e) => {
                e.preventDefault();
                const parsed = parseInt(jumpPageInput, 10);
                if (!Number.isNaN(parsed) && parsed >= 1 && parsed <= totalPages) {
                    setCurrentPage(parsed);
                    setJumpPageInput("");
                }
            };

            // ── Pagination render ─────────────────────────────
            const renderPagination = () => {
                if (totalItems === 0) return null;
                return (
                    <div className="flex flex-col lg:flex-row justify-between items-center gap-4 mt-5 bg-slate-900/50 border border-slate-800 px-4 py-3.5 rounded-2xl">
                        <div className="flex flex-wrap items-center gap-4 text-xs text-slate-400">
                            <span className="tabular-nums">
                                Showing <span className="text-slate-100 font-bold">{totalItems === 0 ? 0 : startIndex + 1}</span>–<span className="text-slate-100 font-bold">{Math.min(startIndex + paginatedData.length, totalItems)}</span> of <span className="text-slate-100 font-bold">{totalItems.toLocaleString()}</span> records
                            </span>
                            <label className="flex items-center gap-2">
                                <span className="text-slate-500 font-medium">Rows</span>
                                <select
                                    value={itemsPerPage}
                                    onChange={(e) => { setItemsPerPage(parseInt(e.target.value, 10)); setCurrentPage(1); }}
                                    className="bg-slate-950 border border-slate-800 rounded-lg px-2 py-1 text-xs font-semibold text-slate-200 focus:outline-none focus:border-indigo-500"
                                >
                                    {[10, 25, 50, 100].map(sz => <option key={sz} value={sz}>{sz}</option>)}
                                </select>
                            </label>
                        </div>
                        {totalPages > 1 && (
                            <div className="flex flex-wrap items-center gap-2">
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
                                                className={`min-w-[36px] h-9 px-2 rounded-xl text-xs font-bold tabular-nums transition-all ${pageToRender === pn ? 'bg-indigo-600 text-white shadow-md shadow-indigo-900/30' : 'bg-slate-800 border border-slate-700/50 text-slate-400 hover:bg-slate-700 hover:text-white'}`}>
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
                                {totalPages > 5 && (
                                    <form onSubmit={handleJumpToPage} className="flex items-center gap-1.5 pl-2 border-l border-slate-800">
                                        <span className="text-[11px] text-slate-500">Go to</span>
                                        <input
                                            type="number"
                                            min="1"
                                            max={totalPages}
                                            value={jumpPageInput}
                                            onChange={(e) => setJumpPageInput(e.target.value)}
                                            placeholder={String(pageToRender)}
                                            className="w-14 bg-slate-950 border border-slate-800 rounded-lg px-2 py-1 text-xs text-slate-200 tabular-nums focus:outline-none focus:border-indigo-500"
                                        />
                                    </form>
                                )}
                            </div>
                        )}
                    </div>
                );
            };

            // ── Camera frame polling ──────────────────────────
            useEffect(() => {
                let active = true, timerId = null;
                const validPoses = ["front"];
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

            useEffect(() => {
                if (cameraStream && videoRef.current) {
                    videoRef.current.srcObject = cameraStream;
                    videoRef.current.play().catch(e => console.warn("Video play exception:", e));
                }
            }, [cameraStream]);

            // ── Render modal form ─────────────────────────────
            const renderModalForm = () => {
                if (modalType === "view-chatbot-query" && selectedItem) {
                    return (
                        <div className="space-y-5 text-sm">
                            <div className="bg-slate-950/60 p-4 rounded-2xl border border-slate-800 space-y-3">
                                <div className="flex items-center justify-between">
                                    <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">User / Requester</span>
                                    <span className={`px-2.5 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider border ${
                                        selectedItem.user_role === 'ADMIN' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' :
                                        selectedItem.user_role === 'LECTURER' ? 'bg-violet-500/10 text-violet-400 border-violet-500/20' :
                                        selectedItem.user_role === 'STUDENT' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                                        selectedItem.user_role === 'STAFF' ? 'bg-sky-500/10 text-sky-400 border-sky-500/20' :
                                        'bg-slate-800 text-slate-400 border-slate-700/50'
                                    }`}>
                                        {selectedItem.user_role || "VISITOR"}
                                    </span>
                                </div>
                                <div>
                                    <p className="font-bold text-slate-100 text-base">{selectedItem.user_name || "Anonymous Visitor"}</p>
                                    {selectedItem.user_email && <p className="text-xs text-slate-400 font-mono mt-0.5">{selectedItem.user_email}</p>}
                                    {selectedItem.user_id && <p className="text-[11px] text-slate-500 font-mono mt-0.5">User ID: #{selectedItem.user_id} {selectedItem.session_id ? `• Session ID: #${selectedItem.session_id}` : ''}</p>}
                                </div>
                            </div>

                            <div>
                                <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-1.5">Question Asked</label>
                                <div className="bg-slate-950/80 border border-slate-800 rounded-2xl p-4 text-slate-100 text-sm font-medium leading-relaxed">
                                    {selectedItem.query_text}
                                </div>
                            </div>

                            <div>
                                <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-1.5">Chatbot Response</label>
                                <div className="bg-slate-950/80 border border-slate-800 rounded-2xl p-4 text-slate-300 text-xs font-normal leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap">
                                    {selectedItem.response_text || "No response recorded."}
                                </div>
                            </div>

                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                                <div className="bg-slate-950/40 border border-slate-800/80 rounded-xl p-3">
                                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Response Time</span>
                                    <span className="text-xs font-mono font-bold text-indigo-400">{selectedItem.response_time_ms ? `${selectedItem.response_time_ms} ms` : 'N/A'}</span>
                                </div>
                                <div className="bg-slate-950/40 border border-slate-800/80 rounded-xl p-3">
                                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Intent / Type</span>
                                    <span className="text-xs font-bold text-slate-300">{selectedItem.is_navigational ? 'Navigation' : 'Information'}</span>
                                </div>
                                <div className="bg-slate-950/40 border border-slate-800/80 rounded-xl p-3 col-span-2 sm:col-span-1">
                                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Source Chunks</span>
                                    <span className="text-xs font-mono text-slate-300">{selectedItem.retrieved_chunks?.length ? `${selectedItem.retrieved_chunks.length} chunk${selectedItem.retrieved_chunks.length > 1 ? 's' : ''}` : 'None'}</span>
                                </div>
                            </div>

                            <div className="flex justify-between items-center text-xs text-slate-500 font-mono pt-2 border-t border-slate-800">
                                <span>Query ID: #{selectedItem.query_id}</span>
                                <span>{selectedItem.timestamp ? new Date(selectedItem.timestamp).toLocaleString() : ''}</span>
                            </div>

                            <div className="pt-2">
                                <button type="button" onClick={() => setShowModal(false)}
                                    className="w-full py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold text-xs transition-colors">
                                    Close Details
                                </button>
                            </div>
                        </div>
                    );
                }
                if (subTab === "users") return <UserForm item={selectedItem} roles={refs.roles} nodes={refs.nodes} programmes={refs.programmes} faculties={refs.faculties} departments={refs.departments} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (subTab === "roles") return <RoleForm item={selectedItem} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "rag" && subTab === "documents") return <DocumentForm item={selectedItem} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "rag" && subTab === "adaptation-phrases") return <SpeechAdaptationPhraseForm item={selectedItem} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "rag" && subTab === "speech-languages") return <SpeechLanguageForm item={selectedItem} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "infra" && subTab === "devices") return <DeviceForm item={selectedItem} nodes={refs.nodes} roles={refs.roles} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "infra" && subTab === "node-rbac") return <NodeRBACForm nodes={refs.nodes} roles={refs.roles} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "infra" && subTab === "edge-rbac") return <EdgeRBACForm edges={refs.edges} roles={refs.roles} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "academics" && subTab === "courses") return <CourseForm item={selectedItem} programmes={refs.programmes} faculties={refs.faculties} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
                if (currentTab === "academics" && subTab === "enrollments") return <EnrollmentForm item={selectedItem} courses={refs.courses} onSubmit={handleFormSubmit} onCancel={() => setShowModal(false)} />;
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
                                        <label className="block text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">Email</label>
                                        <div className="relative">
                                            <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-600">
                                                <Icon name="user" className="w-4 h-4" />
                                            </span>
                                            <input type="email" required value={loginEmail} onChange={e => setLoginEmail(e.target.value)} placeholder="Enter your email"
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

                    {/* ─── MOBILE SIDEBAR BACKDROP ──────────────────────── */}
                    {mobileSidebarOpen && (
                        <div
                            className="fixed inset-0 z-30 bg-slate-950/75 backdrop-blur-xs lg:hidden"
                            onClick={() => setMobileSidebarOpen(false)}
                        />
                    )}

                    {/* ─── SIDEBAR ──────────────────────────────────────── */}
                    <aside className={`fixed inset-y-0 left-0 lg:static bg-slate-950 border-r border-slate-800 flex flex-col justify-between shrink-0 z-40 transition-all duration-300 ${mobileSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'} ${sidebarCollapsed ? 'w-[72px]' : 'w-[272px]'}`}>
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
                        <header className="h-[72px] shrink-0 border-b border-slate-800/60 bg-slate-900/80 backdrop-blur-md px-4 sm:px-8 flex items-center justify-between z-10">
                            <div className="flex items-center gap-3 text-sm min-w-0">
                                <button
                                    type="button"
                                    onClick={() => setMobileSidebarOpen(true)}
                                    aria-label="Open navigation menu"
                                    className="lg:hidden p-2 rounded-xl bg-slate-800/80 text-slate-300 hover:text-white border border-slate-700/60"
                                >
                                    <Icon name="menu" className="w-4 h-4" />
                                </button>
                                <span className="hidden sm:inline text-slate-500 font-medium">{navItems.find(n => n.id === currentTab)?.section === 'main' ? 'Main' : 'Manage'}</span>
                                <Icon name="chevron-right" className="hidden sm:inline w-3.5 h-3.5 text-slate-600" />
                                <span className="text-slate-200 font-bold truncate">{navItems.find(n => n.id === currentTab)?.label}</span>
                                {subTab && (
                                    <>
                                        <Icon name="chevron-right" className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                                        <span className="text-indigo-400 font-semibold truncate">{subTabLabel(subTab)}</span>
                                    </>
                                )}
                            </div>
                            <div className="flex items-center gap-3">
                                <div className="hidden md:flex items-center gap-2 text-xs bg-slate-800/50 border border-slate-700/50 px-3 py-1.5 rounded-full text-slate-300 tabular-nums">
                                    <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                                    <span>System Online</span>
                                    {dashboardStats.db_latency_ms > 0 && (
                                        <span className="text-slate-500 font-mono">· {dashboardStats.db_latency_ms}ms</span>
                                    )}
                                </div>
                                <button
                                    type="button"
                                    onClick={() => { if (adminType !== 'CONTENT_ADMIN') { setCurrentTab("academics"); setSubTab("notifications"); } }}
                                    title="View Notifications"
                                    className="relative p-2 text-slate-400 hover:text-slate-200 rounded-xl hover:bg-slate-800/60 transition-colors"
                                >
                                    <Icon name="bell" className="w-5 h-5" />
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
                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
                                            {adminType !== 'CONTENT_ADMIN' && (
                                                <StatCard
                                                    title="Total Users"
                                                    value={dashboardStats.users.toLocaleString()}
                                                    icon="users"
                                                    changeText={`${dashboardStats.active_users.toLocaleString()} active · ${dashboardStats.inactive_users.toLocaleString()} inactive`}
                                                    color="indigo"
                                                />
                                            )}
                                            {adminType !== 'CONTENT_ADMIN' && (
                                                <StatCard
                                                    title="Face ID Coverage"
                                                    value={dashboardStats.users > 0 ? `${Math.round((dashboardStats.face_enrolled_users / dashboardStats.users) * 100)}%` : "0%"}
                                                    icon="scan-face"
                                                    changeText={`${dashboardStats.face_enrolled_users.toLocaleString()} of ${dashboardStats.users.toLocaleString()} users enrolled`}
                                                    color="emerald"
                                                />
                                            )}
                                            {adminType !== 'CONTENT_ADMIN' && (
                                                <StatCard
                                                    title="IoT Devices"
                                                    value={dashboardStats.devices.toLocaleString()}
                                                    icon="cpu"
                                                    changeText={`${dashboardStats.online_devices} online · ${dashboardStats.offline_devices} offline`}
                                                    color="amber"
                                                />
                                            )}
                                            {adminType !== 'SYSTEM_ADMIN' ? (
                                                <StatCard
                                                    title="Knowledge Docs"
                                                    value={dashboardStats.documents.toLocaleString()}
                                                    icon="book-open"
                                                    changeText={`${dashboardStats.courses.toLocaleString()} active courses`}
                                                    color="violet"
                                                />
                                            ) : (
                                                <StatCard
                                                    title="Active Courses"
                                                    value={dashboardStats.courses.toLocaleString()}
                                                    icon="graduation-cap"
                                                    changeText="Current catalog"
                                                    color="violet"
                                                />
                                            )}
                                        </div>

                                        {/* System status + permissions */}
                                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                                            {/* System status */}
                                            <div className="lg:col-span-2 bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6 shadow-sm">
                                                <div className="flex items-center justify-between mb-6">
                                                    <div className="flex items-center gap-3">
                                                        <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-xl"><Icon name="activity" className="w-5 h-5" /></div>
                                                        <h3 className="text-lg font-bold text-slate-100">Live Telemetry</h3>
                                                    </div>
                                                    {adminType === 'SUPER_ADMIN' && (
                                                        <button
                                                            type="button"
                                                            onClick={() => { setCurrentTab("infra"); setSubTab("auth-logs"); }}
                                                            className="text-xs text-indigo-400 font-semibold hover:text-indigo-300 transition-colors"
                                                        >
                                                            View Access Logs →
                                                        </button>
                                                    )}
                                                </div>
                                                <div className="space-y-3.5">
                                                    {[
                                                        {
                                                            status: "ok",
                                                            title: "Database Connection",
                                                            desc: "Central cloud database responding to live telemetry query.",
                                                            metric: `${dashboardStats.db_latency_ms}ms`
                                                        },
                                                        {
                                                            status: dashboardStats.offline_devices > 0 && dashboardStats.online_devices === 0 && dashboardStats.devices > 0 ? "warn" : "ok",
                                                            title: "Edge Device Fleet",
                                                            desc: `${dashboardStats.online_devices} device(s) reported heartbeat in the last 5 minutes.`,
                                                            metric: `${dashboardStats.online_devices}/${dashboardStats.devices} online`
                                                        },
                                                        {
                                                            status: dashboardStats.auth_failures_24h > 0 ? "warn" : "ok",
                                                            title: "Access Control Activity (24h)",
                                                            desc: `${dashboardStats.auth_attempts_24h} authentication attempt(s) logged · ${dashboardStats.active_sessions} active JWT session(s).`,
                                                            metric: `${dashboardStats.auth_failures_24h} failed`
                                                        },
                                                    ].map((s, i) => (
                                                        <div key={i} className="flex items-center justify-between gap-4 p-4 rounded-xl bg-slate-900/50 border border-slate-800 hover:border-slate-700 transition-colors">
                                                            <div className="flex gap-3.5 items-start">
                                                                <span className={`w-2.5 h-2.5 rounded-full mt-1.5 shrink-0 ${s.status === 'ok' ? 'bg-emerald-500' : 'bg-amber-400'}`}></span>
                                                                <div>
                                                                    <p className="text-sm font-bold text-slate-200">{s.title}</p>
                                                                    <p className="text-xs text-slate-400 mt-0.5">{s.desc}</p>
                                                                </div>
                                                            </div>
                                                            <span className="text-xs font-mono font-semibold text-slate-300 bg-slate-950 border border-slate-800 px-2.5 py-1 rounded-lg tabular-nums shrink-0">{s.metric}</span>
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
                                            <div className="flex items-center gap-3 mb-5">
                                                <div className="p-2 bg-amber-500/10 text-amber-400 rounded-xl"><Icon name="zap" className="w-5 h-5" /></div>
                                                <h3 className="text-lg font-bold text-slate-100">Quick Actions</h3>
                                            </div>
                                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                                                {[
                                                    { tab: "iam",       sub: "users",     label: "Manage Users",     icon: "users",       cls: "bg-indigo-500/15 text-indigo-400",   disabled: adminType === 'CONTENT_ADMIN' },
                                                    { tab: "rag",       sub: "documents", label: "Upload Document",  icon: "upload",      cls: "bg-violet-500/15 text-violet-400",   disabled: adminType === 'SYSTEM_ADMIN' },
                                                    { tab: "infra",     sub: "devices",   label: "View Devices",     icon: "cpu",         cls: "bg-amber-500/15 text-amber-400",     disabled: adminType !== 'SUPER_ADMIN' },
                                                    { tab: "academics", sub: "courses",   label: "Manage Courses",   icon: "book-open",   cls: "bg-emerald-500/15 text-emerald-400", disabled: adminType === 'CONTENT_ADMIN' },
                                                ].map((a, i) => (
                                                    <button key={i} onClick={() => { if (!a.disabled) { setCurrentTab(a.tab); setSubTab(a.sub); } }} disabled={a.disabled}
                                                        className={`flex items-center gap-3 p-4 rounded-xl border text-left transition-all duration-200 ${a.disabled ? 'opacity-30 cursor-not-allowed border-slate-800 bg-slate-900/50' : 'border-slate-700 bg-slate-800/80 hover:bg-slate-800 hover:border-indigo-500/40 cursor-pointer shadow-sm'}`}>
                                                        <div className={`p-2.5 rounded-lg shrink-0 ${a.cls}`}>
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
                        {currentTab === "iam" && (() => {
                            const cellPad = tableDensity === "compact" ? "py-2.5 px-3.5" : "p-4";
                            const hasUserFilters = Boolean(searchQuery.trim()) || roleFilter !== "ALL" || statusFilter !== "ALL" || userFaceFilter !== "ALL" || facultyFilter !== "ALL" || departmentFilter !== "ALL";
                            const hasFaceFilters = Boolean(searchQuery.trim()) || faceStatusFilter !== "ALL" || faceRoleFilter !== "ALL";
                            const resetIamFilters = () => {
                                setSearchQuery(""); setDebouncedSearch("");
                                setRoleFilter("ALL"); setStatusFilter("ALL"); setUserFaceFilter("ALL");
                                setFacultyFilter("ALL"); setDepartmentFilter("ALL");
                                setFaceStatusFilter("ALL"); setFaceRoleFilter("ALL");
                            };
                            const pageUserIds = paginatedData.map(u => u.user_id).filter(Boolean);
                            const allPageSelected = pageUserIds.length > 0 && pageUserIds.every(id => selectedUserIds.includes(id));
                            const facePct = userSummary.total_users > 0 ? Math.round((userSummary.face_enrolled_users / userSummary.total_users) * 100) : 0;

                            return (
                            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out">
                                {/* Sub-tab bar */}
                                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4 mb-5">
                                    <div className="flex flex-wrap gap-2">
                                        {["users", "roles", "facial-recognition"].map(t => (
                                            <button key={t} onClick={() => setSubTab(t)}
                                                className={`px-4 py-2 rounded-xl text-sm font-bold transition-all duration-200 border ${subTab === t ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20 shadow-sm' : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-slate-200 hover:bg-slate-800/80 hover:border-slate-700'}`}>
                                                {subTabLabel(t)}
                                            </button>
                                        ))}
                                    </div>
                                    {(subTab === "users" || subTab === "facial-recognition") && (
                                        <div className="flex items-center gap-2">
                                            <div className="inline-flex bg-slate-950 border border-slate-800 rounded-xl p-0.5">
                                                <button type="button" onClick={() => setTableDensity("comfortable")} title="Comfortable density"
                                                    className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors ${tableDensity === "comfortable" ? "bg-slate-800 text-slate-100" : "text-slate-500 hover:text-slate-300"}`}>
                                                    Comfortable
                                                </button>
                                                <button type="button" onClick={() => setTableDensity("compact")} title="Compact density"
                                                    className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors ${tableDensity === "compact" ? "bg-slate-800 text-slate-100" : "text-slate-500 hover:text-slate-300"}`}>
                                                    Compact
                                                </button>
                                            </div>
                                            {subTab === "users" && (
                                                <button type="button" onClick={handleExportUsersCsv}
                                                    className="bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 px-3 py-1.5 rounded-xl text-xs font-bold transition-colors flex items-center gap-1.5">
                                                    <Icon name="download" className="w-3.5 h-3.5" />
                                                    <span>{selectedUserIds.length > 0 ? `Export (${selectedUserIds.length})` : "Export CSV"}</span>
                                                </button>
                                            )}
                                        </div>
                                    )}
                                </div>

                                {/* Live Directory Summary Strip for Users & Face ID */}
                                {(subTab === "users" || subTab === "facial-recognition") && (
                                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
                                        <button type="button" onClick={resetIamFilters}
                                            className="text-left p-3.5 rounded-2xl bg-slate-900/70 border border-slate-800 hover:border-indigo-500/40 transition-colors">
                                            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Total Users</div>
                                            <div className="text-2xl font-extrabold text-slate-100 mt-1 tabular-nums">{userSummary.total_users.toLocaleString()}</div>
                                        </button>
                                        <button type="button" onClick={() => { if (subTab === "users") setStatusFilter(statusFilter === "ACTIVE" ? "ALL" : "ACTIVE"); }}
                                            className={`text-left p-3.5 rounded-2xl border transition-colors ${subTab === "users" && statusFilter === "ACTIVE" ? "bg-emerald-500/10 border-emerald-500/40" : "bg-slate-900/70 border-slate-800 hover:border-slate-700"}`}>
                                            <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">Active Accounts</div>
                                            <div className="text-2xl font-extrabold text-slate-100 mt-1 tabular-nums">{userSummary.active_users.toLocaleString()}</div>
                                        </button>
                                        <button type="button" onClick={() => { if (subTab === "users") setStatusFilter(statusFilter === "DEACTIVATED" ? "ALL" : "DEACTIVATED"); }}
                                            className={`text-left p-3.5 rounded-2xl border transition-colors ${subTab === "users" && statusFilter === "DEACTIVATED" ? "bg-red-500/10 border-red-500/40" : "bg-slate-900/70 border-slate-800 hover:border-slate-700"}`}>
                                            <div className="text-[11px] font-semibold uppercase tracking-wider text-red-400">Deactivated</div>
                                            <div className="text-2xl font-extrabold text-slate-100 mt-1 tabular-nums">{userSummary.inactive_users.toLocaleString()}</div>
                                        </button>
                                        <button type="button" onClick={() => {
                                            if (subTab === "users") setUserFaceFilter(userFaceFilter === "ENROLLED" ? "ALL" : "ENROLLED");
                                            else setFaceStatusFilter(faceStatusFilter === "ENROLLED" ? "ALL" : "ENROLLED");
                                        }}
                                            className={`text-left p-3.5 rounded-2xl border transition-colors ${((subTab === "users" && userFaceFilter === "ENROLLED") || (subTab === "facial-recognition" && faceStatusFilter === "ENROLLED")) ? "bg-indigo-500/10 border-indigo-500/40" : "bg-slate-900/70 border-slate-800 hover:border-slate-700"}`}>
                                            <div className="flex items-center justify-between">
                                                <span className="text-[11px] font-semibold uppercase tracking-wider text-indigo-400">Face ID Enrolled</span>
                                                <span className="text-[11px] font-mono text-indigo-300 tabular-nums">{facePct}%</span>
                                            </div>
                                            <div className="text-2xl font-extrabold text-slate-100 mt-1 tabular-nums">{userSummary.face_enrolled_users.toLocaleString()}</div>
                                        </button>
                                    </div>
                                )}

                                <SectionHeader
                                    title={subTab === "facial-recognition" ? "Face ID Enrollment" : subTab === "roles" ? "Access Roles" : "Users Directory"}
                                    description={
                                        subTab === "roles" ? "Manage campus access roles and their permission levels." :
                                        subTab === "facial-recognition" ? "Inspect and enroll facial recognition profiles. Click any user row to view enrolled poses." :
                                        "Server-paginated directory. Click any user row to open their 360° profile, biometrics, and access logs."
                                    }
                                    searchVal={searchQuery}
                                    onSearchChange={setSearchQuery}
                                    searchInputRef={searchInputRef}
                                    searchPlaceholder={subTab === "roles" ? "Search roles..." : "Search name, email, ID... (/)"}
                                    onCreateClick={subTab === "facial-recognition" ? null : () => { setSelectedItem(null); setModalType("create"); setShowModal(true); }}
                                    createLabel={subTab === "roles" ? "Add Role" : "Register User"}
                                    customAction={
                                        subTab === "facial-recognition" && adminType === "SUPER_ADMIN" ? (
                                            <button onClick={handleReembedAll} disabled={reembedding}
                                                className="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700/50 px-4 py-2 rounded-xl text-sm font-bold transition-all flex items-center gap-2 disabled:opacity-50">
                                                {reembedding ? <><span className="w-3.5 h-3.5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin"></span><span>Processing...</span></>
                                                    : <><Icon name="refresh-cw" className="w-4 h-4" /><span>Re-process All</span></>}
                                            </button>
                                        ) : null
                                    }
                                />

                                {/* Multi-Facet Filter Bar */}
                                {subTab === "users" && (
                                    <div className="flex flex-wrap items-center gap-2 mb-4">
                                        <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)}
                                            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs font-semibold text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer">
                                            <option value="ALL">All Roles</option>
                                            {refs.roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)}
                                        </select>
                                        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
                                            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs font-semibold text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer">
                                            <option value="ALL">All Status</option>
                                            <option value="ACTIVE">Active</option>
                                            <option value="DEACTIVATED">Deactivated</option>
                                        </select>
                                        <select value={userFaceFilter} onChange={e => setUserFaceFilter(e.target.value)}
                                            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs font-semibold text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer">
                                            <option value="ALL">All Face ID</option>
                                            <option value="ENROLLED">Face ID Enrolled</option>
                                            <option value="NOT_ENROLLED">Not Enrolled</option>
                                        </select>
                                        {refs.faculties.length > 0 && (
                                            <select value={facultyFilter} onChange={e => setFacultyFilter(e.target.value)}
                                                className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs font-semibold text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer max-w-[190px]">
                                                <option value="ALL">All Faculties</option>
                                                {refs.faculties.map(f => <option key={f.faculty_id} value={f.faculty_id}>{f.faculty_name}</option>)}
                                            </select>
                                        )}
                                        {refs.departments.length > 0 && (
                                            <select value={departmentFilter} onChange={e => setDepartmentFilter(e.target.value)}
                                                className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs font-semibold text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer max-w-[190px]">
                                                <option value="ALL">All Departments</option>
                                                {refs.departments.map(d => <option key={d.department_id} value={d.department_id}>{d.department_name}</option>)}
                                            </select>
                                        )}
                                        {hasUserFilters && (
                                            <button type="button" onClick={resetIamFilters}
                                                className="px-3 py-2 rounded-xl text-xs font-bold text-indigo-400 hover:text-indigo-300 bg-indigo-500/10 border border-indigo-500/20 transition-colors">
                                                Reset Filters
                                            </button>
                                        )}
                                    </div>
                                )}

                                {subTab === "facial-recognition" && (
                                    <div className="flex flex-wrap items-center gap-2 mb-4">
                                        <select value={faceStatusFilter} onChange={e => setFaceStatusFilter(e.target.value)}
                                            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs font-semibold text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer">
                                            <option value="ALL">All Face ID Status</option>
                                            <option value="ENROLLED">Face ID Enrolled</option>
                                            <option value="NOT_ENROLLED">Not Enrolled</option>
                                        </select>
                                        <select value={faceRoleFilter} onChange={e => setFaceRoleFilter(e.target.value)}
                                            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs font-semibold text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer">
                                            <option value="ALL">All Roles</option>
                                            {refs.roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)}
                                        </select>
                                        {hasFaceFilters && (
                                            <button type="button" onClick={resetIamFilters}
                                                className="px-3 py-2 rounded-xl text-xs font-bold text-indigo-400 hover:text-indigo-300 bg-indigo-500/10 border border-indigo-500/20 transition-colors">
                                                Reset Filters
                                            </button>
                                        )}
                                    </div>
                                )}

                                {/* Bulk Selection Action Bar */}
                                {subTab === "users" && selectedUserIds.length > 0 && (
                                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 px-4 py-3 rounded-2xl bg-indigo-950/60 border border-indigo-500/40 shadow-lg">
                                        <div className="flex items-center gap-2.5 text-sm font-bold text-indigo-200 tabular-nums">
                                            <span className="px-2 py-0.5 rounded-lg bg-indigo-600 text-white text-xs">{selectedUserIds.length}</span>
                                            <span>user{selectedUserIds.length > 1 ? "s" : ""} selected</span>
                                        </div>
                                        <div className="flex flex-wrap items-center gap-2">
                                            <button type="button" disabled={bulkBusy} onClick={() => handleBulkUserStatus(true)}
                                                className="px-3 py-1.5 rounded-xl text-xs font-bold bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 disabled:opacity-50">
                                                Activate
                                            </button>
                                            <button type="button" disabled={bulkBusy} onClick={() => handleBulkUserStatus(false)}
                                                className="px-3 py-1.5 rounded-xl text-xs font-bold bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border border-amber-500/30 disabled:opacity-50">
                                                Deactivate
                                            </button>
                                            <div className="flex items-center gap-1.5">
                                                <select value={bulkRoleId} onChange={(e) => setBulkRoleId(e.target.value)}
                                                    className="bg-slate-950 border border-slate-700 rounded-xl px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500">
                                                    <option value="">Add role...</option>
                                                    {refs.roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)}
                                                </select>
                                                <button type="button" disabled={!bulkRoleId || bulkBusy} onClick={handleBulkUserRole}
                                                    className="px-3 py-1.5 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40">
                                                    Apply
                                                </button>
                                            </div>
                                            <button type="button" disabled={bulkBusy} onClick={handleBulkUserDelete}
                                                className="px-3 py-1.5 rounded-xl text-xs font-bold bg-red-500/15 hover:bg-red-500/25 text-red-300 border border-red-500/30 disabled:opacity-50">
                                                Delete
                                            </button>
                                            <button type="button" onClick={() => setSelectedUserIds([])}
                                                className="px-2.5 py-1.5 rounded-xl text-xs font-semibold text-slate-400 hover:text-white">
                                                Clear
                                            </button>
                                        </div>
                                    </div>
                                )}

                                {listLoading ? (
                                    <div className="flex flex-col items-center justify-center py-24 text-slate-500 bg-slate-900/50 rounded-2xl border border-slate-800">
                                        <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-4"></div>
                                        <span className="text-sm font-semibold">Loading directory...</span>
                                    </div>
                                ) : paginatedData.length === 0 ? (
                                    <div className="flex flex-col items-center justify-center border-2 border-dashed border-slate-800 bg-slate-900/30 rounded-3xl py-20 px-4">
                                        <div className="p-4 bg-slate-800 border border-slate-700 text-slate-400 rounded-2xl mb-4"><Icon name="users" className="w-7 h-7" /></div>
                                        <h4 className="text-base font-bold text-slate-200">
                                            {(hasUserFilters || hasFaceFilters) ? "No matching records" : "No records yet"}
                                        </h4>
                                        <p className="text-sm text-slate-400 mt-1 max-w-sm text-center">
                                            {(hasUserFilters || hasFaceFilters)
                                                ? "No users match your active search or filter criteria."
                                                : "Register a user to get started."}
                                        </p>
                                        {(hasUserFilters || hasFaceFilters) && (
                                            <button type="button" onClick={resetIamFilters}
                                                className="mt-4 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white transition-colors">
                                                Reset All Filters
                                            </button>
                                        )}
                                    </div>
                                ) : (
                                    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl shadow-sm overflow-hidden backdrop-blur-sm">
                                        <div className="overflow-x-auto max-h-[68vh] overflow-y-auto scrollbar-thin">
                                            <table className="w-full text-left text-sm">
                                                <thead className="sticky top-0 z-10 bg-slate-900/95 backdrop-blur-sm">
                                                    {subTab === "roles" && (
                                                        <tr className="bg-slate-800/70 text-slate-400 font-bold text-xs tracking-wider uppercase border-b border-slate-800">
                                                            <th className="p-4 pl-6 font-semibold">Role Name</th>
                                                            <th className="p-4 font-semibold">Description</th>
                                                            <th className="p-4 font-semibold">Role ID</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    )}
                                                    {subTab === "facial-recognition" && (
                                                        <tr className="bg-slate-800/70 text-slate-400 font-bold text-xs tracking-wider uppercase border-b border-slate-800">
                                                            <th className="p-4 pl-6 font-semibold cursor-pointer select-none hover:text-slate-200" onClick={() => handleSort("name")}>
                                                                <span className="inline-flex items-center">User Profile {renderSortIcon("name")}</span>
                                                            </th>
                                                            <th className="p-4 font-semibold">Face ID Status</th>
                                                            <th className="p-4 font-semibold">Enrolled Poses</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    )}
                                                    {subTab === "users" && (
                                                        <tr className="bg-slate-800/70 text-slate-400 font-bold text-xs tracking-wider uppercase border-b border-slate-800">
                                                            <th className="p-3.5 pl-5 w-10">
                                                                <input
                                                                    type="checkbox"
                                                                    aria-label="Select all users on page"
                                                                    checked={allPageSelected}
                                                                    onChange={toggleSelectAllPageUsers}
                                                                    className="w-4 h-4 rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                                                                />
                                                            </th>
                                                            <th className="p-3.5 font-semibold cursor-pointer select-none hover:text-slate-200" onClick={() => handleSort("name")}>
                                                                <span className="inline-flex items-center">User Profile {renderSortIcon("name")}</span>
                                                            </th>
                                                            <th className="p-3.5 font-semibold">Identity Details</th>
                                                            <th className="p-3.5 font-semibold">Face ID</th>
                                                            <th className="p-3.5 font-semibold cursor-pointer select-none hover:text-slate-200" onClick={() => handleSort("is_active")}>
                                                                <span className="inline-flex items-center">Status {renderSortIcon("is_active")}</span>
                                                            </th>
                                                            <th className="p-3.5 pr-5 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    )}
                                                </thead>
                                                <tbody className="divide-y divide-slate-800/50">
                                                    {paginatedData.map((item, idx) => {
                                                        if (subTab === "roles") return (
                                                            <tr key={item.role_id ?? idx} className="hover:bg-slate-800/40 transition-colors">
                                                                <td className={`${cellPad} pl-6`}>
                                                                    <div className="inline-flex px-2 py-1 rounded-md bg-slate-800 border border-slate-700/50 text-slate-200 uppercase font-mono text-xs font-bold tracking-wider">
                                                                        {item.role_name}
                                                                    </div>
                                                                </td>
                                                                <td className={`${cellPad} text-sm text-slate-400 max-w-xs`}>{item.description || "—"}</td>
                                                                <td className={`${cellPad} text-xs font-mono text-slate-500 tabular-nums`}>#{item.role_id}</td>
                                                                <td className={`${cellPad} pr-6 text-right`}>
                                                                    <div className="flex justify-end gap-1.5">
                                                                        <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit Role"
                                                                            className="p-2 bg-slate-800/80 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
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
                                                            <tr key={item.user_id ?? idx}
                                                                onClick={() => setDrawerState({ record: item, kind: "user" })}
                                                                className="hover:bg-slate-800/40 transition-colors cursor-pointer">
                                                                <td className={`${cellPad} pl-6`}>
                                                                    <div className="flex items-center gap-3">
                                                                        <div className="w-9 h-9 rounded-full bg-slate-800 border border-slate-700/50 flex items-center justify-center overflow-hidden shrink-0">
                                                                            <span className="text-xs font-bold text-slate-300">
                                                                                {((item.given_name?.[0] || "") + (item.family_name?.[0] || "")).toUpperCase() || (item.full_name?.slice(0, 2).toUpperCase() || "U")}
                                                                            </span>
                                                                        </div>
                                                                        <div className="min-w-0">
                                                                            <div className="font-bold text-slate-200 text-sm flex items-center gap-2">
                                                                                <span className="truncate">{item.full_name}</span>
                                                                                <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60 tabular-nums">#{item.user_id}</span>
                                                                            </div>
                                                                            <div className="text-xs text-slate-400 font-mono truncate">{item.email}</div>
                                                                            <div className="flex gap-1 mt-1 flex-wrap">
                                                                                {(item.roles || []).map((r, rI) => (
                                                                                    <span key={rI} className="text-[10px] font-bold tracking-wider px-1.5 py-0.2 bg-slate-800 text-indigo-300 border border-slate-700/50 rounded uppercase">
                                                                                        {r.role_name}
                                                                                    </span>
                                                                                ))}
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                </td>
                                                                <td className={cellPad}>
                                                                    {item.face_enrolled || item.face_vector ? (
                                                                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full text-xs font-bold">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                                                                            Enrolled
                                                                        </span>
                                                                    ) : (
                                                                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-slate-800 text-slate-400 border border-slate-700/50 rounded-full text-xs font-bold">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-slate-500"></span>
                                                                            Not Enrolled
                                                                        </span>
                                                                    )}
                                                                </td>
                                                                <td className={`${cellPad} text-xs font-mono text-slate-400`}>
                                                                    {item.enrolled_poses?.length > 0
                                                                        ? `${item.enrolled_poses.length} pose(s): ${item.enrolled_poses.join(", ")}`
                                                                        : (item.face_enrolled ? "Enrolled" : "No biometric templates")}
                                                                </td>
                                                                <td className={`${cellPad} pr-6 text-right`} onClick={(e) => e.stopPropagation()}>
                                                                    <div className="flex justify-end gap-1.5">
                                                                        <button onClick={() => setDrawerState({ record: item, kind: "user" })} title="Inspect User"
                                                                            className="p-2 bg-slate-800/80 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="eye" className="w-4 h-4" />
                                                                        </button>
                                                                        <button onClick={() => {
                                                                            setSelectedItem(item);
                                                                            setSelectedPhotoFile(null);
                                                                            setUploadedPhoto(null);
                                                                            setPhotoPose("front");
                                                                            setEnrollMethod("photo");
                                                                            setScanStep(0);
                                                                            setScanning(false);
                                                                            setShowFaceModal(true);
                                                                        }} title="Manage Biometrics"
                                                                            className="p-2 bg-slate-800/80 hover:bg-slate-700 border border-slate-700/50 text-indigo-400 rounded-xl transition-all hover:text-white">
                                                                            <Icon name="scan-face" className="w-4 h-4" />
                                                                        </button>
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        );

                                                        if (subTab === "users") {
                                                            const studentObj = item.student;
                                                            const lecturerObj = item.lecturer;
                                                            const staffObj = item.staff;
                                                            const visitorObj = item.visitor;
                                                            const adminObj = item.admin;
                                                            const isSelected = selectedUserIds.includes(item.user_id);

                                                            return (
                                                                <tr key={item.user_id ?? idx}
                                                                    onClick={() => setDrawerState({ record: item, kind: "user" })}
                                                                    className={`transition-colors cursor-pointer ${isSelected ? "bg-indigo-950/35 hover:bg-indigo-950/50" : "hover:bg-slate-800/40"}`}>
                                                                    <td className={`${cellPad} pl-5`} onClick={(e) => e.stopPropagation()}>
                                                                        <input
                                                                            type="checkbox"
                                                                            aria-label={`Select ${item.full_name}`}
                                                                            checked={isSelected}
                                                                            onChange={() => toggleSelectUser(item.user_id)}
                                                                            className="w-4 h-4 rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                                                                        />
                                                                    </td>
                                                                    <td className={cellPad}>
                                                                        <div className="flex items-center gap-3">
                                                                            <div className="w-9 h-9 rounded-full bg-slate-800 border border-slate-700/50 flex items-center justify-center overflow-hidden shrink-0">
                                                                                <span className="text-xs font-bold text-slate-300">
                                                                                    {((item.given_name?.[0] || "") + (item.family_name?.[0] || "")).toUpperCase() || (item.full_name?.slice(0, 2).toUpperCase() || "U")}
                                                                                </span>
                                                                            </div>
                                                                            <div className="min-w-0">
                                                                                <div className="font-bold text-slate-200 text-sm flex items-center gap-2">
                                                                                    <span className="truncate">{item.full_name}</span>
                                                                                    <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60 tabular-nums shrink-0">#{item.user_id}</span>
                                                                                </div>
                                                                                <div className="text-xs text-slate-400 font-mono truncate">{item.email}</div>
                                                                                <div className="flex flex-wrap gap-1 mt-1">
                                                                                    {(item.roles || []).map((r, rI) => (
                                                                                        <span key={rI} className="text-[10px] font-bold tracking-wider px-1.5 py-0.5 bg-indigo-950/80 text-indigo-300 border border-indigo-700/50 rounded uppercase">
                                                                                            {r.role_name}
                                                                                        </span>
                                                                                    ))}
                                                                                </div>
                                                                            </div>
                                                                        </div>
                                                                    </td>
                                                                    <td className={cellPad}>
                                                                        <div className="space-y-1">
                                                                            {studentObj && (
                                                                                <div className="text-xs text-slate-300 flex items-center gap-1.5">
                                                                                    <Icon name="graduation-cap" className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                                                                                    <span className="font-mono text-indigo-400 font-semibold">{studentObj.student_id}</span>
                                                                                    {studentObj.program && <span className="text-slate-400 truncate max-w-[180px]">· {studentObj.program}</span>}
                                                                                </div>
                                                                            )}
                                                                            {lecturerObj && (
                                                                                <div className="text-xs text-slate-300 flex items-center gap-1.5">
                                                                                    <Icon name="book-open" className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                                                                                    <span className="font-mono text-purple-400 font-semibold">{lecturerObj.lecturer_id}</span>
                                                                                    {lecturerObj.position && <span className="text-slate-400 truncate max-w-[180px]">· {lecturerObj.position}</span>}
                                                                                </div>
                                                                            )}
                                                                            {staffObj && (
                                                                                <div className="text-xs text-slate-300 flex items-center gap-1.5">
                                                                                    <Icon name="briefcase" className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                                                                                    <span className="font-mono text-emerald-400 font-semibold">{staffObj.staff_id}</span>
                                                                                    {staffObj.position && <span className="text-slate-400 truncate max-w-[180px]">· {staffObj.position}</span>}
                                                                                </div>
                                                                            )}
                                                                            {visitorObj && (
                                                                                <div className="text-xs text-slate-300 flex items-center gap-1.5">
                                                                                    <Icon name="user-check" className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                                                                                    <span className="font-mono text-amber-400 font-semibold">{visitorObj.id_number}</span>
                                                                                    {visitorObj.organization && <span className="text-slate-400 truncate max-w-[180px]">· {visitorObj.organization}</span>}
                                                                                </div>
                                                                            )}
                                                                            {adminObj && (
                                                                                <div className="text-xs text-slate-300 flex items-center gap-1.5">
                                                                                    <Icon name="shield" className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                                                                                    <span className="font-mono text-rose-400 font-semibold">{adminObj.admin_id}</span>
                                                                                    <span className="text-slate-400">· {adminObj.admin_type}</span>
                                                                                </div>
                                                                            )}
                                                                            {!studentObj && !lecturerObj && !staffObj && !visitorObj && !adminObj && (
                                                                                <span className="text-xs text-slate-500 italic">No sub-profile</span>
                                                                            )}
                                                                        </div>
                                                                    </td>
                                                                    <td className={cellPad}>
                                                                        {item.face_enrolled ? (
                                                                            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full text-[11px] font-bold tabular-nums">
                                                                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                                                                                {item.enrolled_poses_count ? `${item.enrolled_poses_count} pose${item.enrolled_poses_count > 1 ? "s" : ""}` : "Enrolled"}
                                                                            </span>
                                                                        ) : (
                                                                            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 bg-slate-800/80 text-slate-500 border border-slate-700/60 rounded-full text-[11px] font-semibold">
                                                                                None
                                                                            </span>
                                                                        )}
                                                                    </td>
                                                                    <td className={cellPad} onClick={(e) => e.stopPropagation()}>
                                                                        <button onClick={() => handleToggleStatus(item)}
                                                                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold border transition-all ${item.is_active ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500 hover:text-white hover:border-emerald-500' : 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500 hover:text-white'}`}>
                                                                            <span className={`w-1.5 h-1.5 rounded-full ${item.is_active ? 'bg-emerald-400' : 'bg-red-400'}`}></span>
                                                                            {item.is_active ? 'Active' : 'Deactivated'}
                                                                        </button>
                                                                    </td>
                                                                    <td className={`${cellPad} pr-5 text-right`} onClick={(e) => e.stopPropagation()}>
                                                                        <div className="flex justify-end gap-1.5">
                                                                            <button onClick={() => setDrawerState({ record: item, kind: "user" })} title="Inspect User 360°"
                                                                                className="p-2 bg-slate-800/70 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                                <Icon name="eye" className="w-4 h-4" />
                                                                            </button>
                                                                            <button onClick={() => {
                                                                                setSelectedItem(item);
                                                                                setSelectedPhotoFile(null);
                                                                                setUploadedPhoto(null);
                                                                                setPhotoPose("front");
                                                                                setEnrollMethod("photo");
                                                                                setScanStep(0);
                                                                                setScanning(false);
                                                                                setShowFaceModal(true);
                                                                            }} title="Manage Face ID"
                                                                                className="p-2 bg-slate-800/70 hover:bg-slate-700 border border-slate-700/50 text-indigo-400 rounded-xl transition-all hover:text-white">
                                                                                <Icon name="scan-face" className="w-4 h-4" />
                                                                            </button>
                                                                            <button onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }} title="Edit User"
                                                                                className="p-2 bg-slate-800/70 hover:bg-slate-700 border border-slate-700/50 text-slate-300 rounded-xl transition-all hover:text-white">
                                                                                <Icon name="edit-3" className="w-4 h-4" />
                                                                            </button>
                                                                            <button onClick={() => handleDeleteItem(item)} title="Remove User"
                                                                                className="p-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-xl transition-all">
                                                                                <Icon name="trash-2" className="w-4 h-4" />
                                                                            </button>
                                                                        </div>
                                                                    </td>
                                                                </tr>
                                                            );
                                                        }
                                                        return null;
                                                    })}
                                                </tbody>
                                            </table>
                                        </div>
                                    </div>
                                )}
                                {renderPagination()}
                            </div>
                            );
                        })()}

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
                                    title={subTab === 'documents' ? "Uploaded Documents" : subTab === 'adaptation-phrases' ? "Acronyms & Translations" : subTab === 'speech-languages' ? "Supported Languages" : "Chatbot Conversations"}
                                    description={
                                        subTab === 'documents' ? "Upload and manage documents that the campus chatbot uses to answer questions." :
                                        subTab === 'adaptation-phrases' ? "List of campus acronyms and all their language translations." :
                                        subTab === 'speech-languages' ? "Configure recognized campus languages and default voice recognition settings." :
                                        "Review and analyze user queries submitted to the chatbot, response quality, and latency."
                                    }
                                    searchVal={searchQuery}
                                    onSearchChange={setSearchQuery}
                                    onCreateClick={['documents', 'adaptation-phrases', 'speech-languages'].includes(subTab) ? () => { setSelectedItem(null); setModalType("create"); setShowModal(true); } : null}
                                    createLabel={subTab === 'adaptation-phrases' ? "Add Acronym" : subTab === 'speech-languages' ? "Add Language" : "Upload Document"}
                                    customAction={subTab === 'documents' ? (
                                        <select value={accessLevelFilter} onChange={e => setAccessLevelFilter(e.target.value)}
                                            className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-sm text-slate-300 focus:outline-none focus:border-indigo-500 hover:border-slate-600 transition-colors cursor-pointer">
                                            <option value="ALL">All Roles</option>
                                            <option value="VISITOR">Visitor (Public)</option>
                                            <option value="STUDENT">Students</option>
                                            <option value="LECTURER">Lecturers</option>
                                            <option value="STAFF">Staff</option>
                                            <option value="ADMIN">Admins</option>
                                        </select>
                                    ) : subTab === 'chatbot-queries' ? (
                                        <div className="flex flex-wrap items-center gap-2">
                                            <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)}
                                                className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-sm text-slate-300 focus:outline-none focus:border-indigo-500 hover:border-slate-600 transition-colors cursor-pointer">
                                                <option value="ALL">All Roles</option>
                                                <option value="VISITOR">Visitor</option>
                                                <option value="STUDENT">Student</option>
                                                <option value="LECTURER">Lecturer</option>
                                                <option value="STAFF">Staff</option>
                                                <option value="ADMIN">Admin</option>
                                            </select>
                                            <select value={accessLevelFilter} onChange={e => setAccessLevelFilter(e.target.value)}
                                                className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-sm text-slate-300 focus:outline-none focus:border-indigo-500 hover:border-slate-600 transition-colors cursor-pointer">
                                                <option value="ALL">All Types</option>
                                                <option value="INFO">Information</option>
                                                <option value="NAV">Navigation</option>
                                            </select>
                                        </div>
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
                                        <h4 className="text-base font-bold text-slate-200">No records found</h4>
                                        <p className="text-sm text-slate-500 mt-1 max-w-sm text-center">
                                            {subTab === 'adaptation-phrases' ? "Add campus acronyms and their translations to get started." : subTab === 'speech-languages' ? "No languages configured." : "Upload documents to build the knowledge base."}
                                        </p>
                                    </div>
                                ) : subTab === 'adaptation-phrases' ? (
                                    <div className="space-y-3.5">
                                        {paginatedData.map((item, idx) => {
                                            const translations = parseTranslations(item.description);
                                            return (
                                                <div key={item.phrase_id || idx} className="bg-slate-900/80 border border-slate-800/80 hover:border-slate-700/80 rounded-2xl p-5 transition-all shadow-sm">
                                                    <div className="flex items-center justify-between pb-3.5 border-b border-slate-800/80 mb-3.5">
                                                        <div className="flex items-center gap-3">
                                                            <span className="text-lg font-black text-white tracking-tight">{item.phrase}</span>
                                                            <span className="text-[11px] font-bold text-indigo-400 bg-indigo-500/10 border border-indigo-500/20 px-2.5 py-0.5 rounded-md">
                                                                {translations.length} {translations.length === 1 ? 'translation' : 'translations'}
                                                            </span>
                                                        </div>
                                                        <div className="flex items-center gap-2">
                                                            <button
                                                                onClick={() => { setSelectedItem(item); setModalType("edit"); setShowModal(true); }}
                                                                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 transition-colors inline-flex items-center gap-1.5"
                                                                title="Edit Acronym & Translations"
                                                            >
                                                                <Icon name="edit-3" className="w-3.5 h-3.5" />
                                                                <span>Edit</span>
                                                            </button>
                                                            <button
                                                                onClick={() => handleDeleteItem(item)}
                                                                className="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                                                                title="Delete Acronym"
                                                            >
                                                                <Icon name="trash-2" className="w-4 h-4" />
                                                            </button>
                                                        </div>
                                                    </div>

                                                    {translations.length === 0 ? (
                                                        <p className="text-xs text-slate-500 italic py-1">No translations added yet.</p>
                                                    ) : (
                                                        <div className="space-y-2">
                                                            {translations.map((t, tIdx) => {
                                                                const badge = getLangBadge(t.lang);
                                                                return (
                                                                    <div key={tIdx} className="flex items-center justify-between bg-slate-950/60 border border-slate-800/60 rounded-xl px-3.5 py-2 text-xs">
                                                                        <div className="flex items-center gap-3 min-w-0">
                                                                            <span className={`inline-flex items-center justify-center font-bold text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md border shrink-0 min-w-[70px] ${badge.cls}`}>
                                                                                {badge.name}
                                                                            </span>
                                                                            <span className="text-slate-200 font-medium truncate">{t.text}</span>
                                                                        </div>
                                                                    </div>
                                                                );
                                                            })}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                ) : subTab === 'speech-languages' ? (
                                    <div className="space-y-4">
                                        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 backdrop-blur-sm">
                                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                                                <div>
                                                    <h4 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                                                        <Icon name="languages" className="w-4 h-4 text-indigo-400" />
                                                        Speech Recognition & Voice Understanding
                                                    </h4>
                                                    <p className="text-xs text-slate-400 mt-1 max-w-2xl leading-relaxed">
                                                        The chatbot can dynamically converse and switch to <strong className="text-slate-200">any language</strong> requested by the user during conversation.
                                                        Use <strong className="text-slate-200">"Listen by Default"</strong> to pre-load speech recognition models immediately at session start, or add new supported languages to the campus directory.
                                                    </p>
                                                </div>
                                                <div className="flex items-center gap-2 shrink-0">
                                                    <span className="text-xs font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-3 py-1 rounded-xl">
                                                        {listData.filter(l => l.is_default).length} Active Defaults
                                                    </span>
                                                    <span className="text-xs font-semibold text-indigo-400 bg-indigo-500/10 border border-indigo-500/20 px-3 py-1 rounded-xl">
                                                        {listData.filter(l => l.is_active).length} Enabled
                                                    </span>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                                            {paginatedData.map((lang, idx) => (
                                                <div key={lang.language_code || idx} className={`p-4 rounded-2xl border transition-all ${
                                                    lang.is_default
                                                        ? 'bg-slate-900/90 border-indigo-500/30 shadow-sm'
                                                        : lang.is_active
                                                            ? 'bg-slate-900/70 border-slate-800 hover:border-slate-700'
                                                            : 'bg-slate-950/40 border-slate-900 opacity-60'
                                                }`}>
                                                    <div className="flex items-center justify-between gap-3 mb-3">
                                                        <div className="flex items-center gap-3">
                                                            <div className={`w-10 h-10 rounded-xl flex items-center justify-center font-bold text-xs uppercase border ${
                                                                lang.is_default
                                                                    ? 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30'
                                                                    : 'bg-slate-800 text-slate-300 border-slate-700'
                                                            }`}>
                                                                {lang.language_code}
                                                            </div>
                                                            <div>
                                                                <h5 className="font-bold text-slate-100 text-sm">{lang.language_name}</h5>
                                                                <span className="text-[11px] text-slate-500 font-mono">Code: {lang.language_code}</span>
                                                            </div>
                                                        </div>
                                                        <div className="flex items-center gap-1.5">
                                                            {lang.is_default && (
                                                                <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 rounded-full uppercase tracking-wider">
                                                                    Primary ASR
                                                                </span>
                                                            )}
                                                            <button
                                                                type="button"
                                                                onClick={() => handleDeleteItem(lang)}
                                                                className="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                                                                title={`Delete ${lang.language_name} (${lang.language_code})`}
                                                            >
                                                                <Icon name="trash-2" className="w-4 h-4" />
                                                            </button>
                                                        </div>
                                                    </div>

                                                    <div className="flex items-center justify-between pt-3 border-t border-slate-800/80 text-xs">
                                                        <div className="flex items-center gap-2">
                                                            <button
                                                                type="button"
                                                                onClick={() => handleToggleLanguageDefault(lang.language_code)}
                                                                className={`px-3 py-1.5 rounded-xl font-semibold text-xs border transition-all flex items-center gap-1.5 ${
                                                                    lang.is_default
                                                                        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/25'
                                                                        : 'bg-slate-800/80 text-slate-400 border-slate-700/60 hover:text-slate-200 hover:bg-slate-800'
                                                                }`}
                                                                title="Toggle whether this language is loaded by default in Live ASR"
                                                            >
                                                                <span className={`w-1.5 h-1.5 rounded-full ${lang.is_default ? 'bg-emerald-400' : 'bg-slate-500'}`}></span>
                                                                {lang.is_default ? 'Listening by Default' : 'Standby'}
                                                            </button>
                                                        </div>

                                                        <button
                                                            type="button"
                                                            onClick={() => handleToggleLanguageActive(lang.language_code)}
                                                            className={`px-3 py-1.5 rounded-xl font-semibold text-xs border transition-all ${
                                                                lang.is_active
                                                                    ? 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30 hover:bg-indigo-500/25'
                                                                    : 'bg-rose-500/10 text-rose-400 border-rose-500/20 hover:bg-rose-500/20'
                                                            }`}
                                                            title="Toggle whether this language is active in the campus directory"
                                                        >
                                                            {lang.is_active ? 'Enabled' : 'Disabled'}
                                                        </button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
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
                                                            <tr key={item.document_id ?? idx} onClick={() => setDrawerState({ record: item, kind: "document" })} className="hover:bg-slate-800/40 transition-colors cursor-pointer group">
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
                                                                    <div className="flex flex-wrap gap-1.5 max-w-xs">
                                                                        {((item.allowed_roles && item.allowed_roles.length > 0)
                                                                            ? item.allowed_roles
                                                                            : (item.access_level === "PUBLIC" ? ["VISITOR"] : [item.access_level || "VISITOR"])
                                                                        ).map((role, rIdx) => (
                                                                            <span key={rIdx} className="text-[10px] font-bold tracking-wider px-2.5 py-0.5 rounded-md uppercase border bg-indigo-950/80 text-indigo-300 border-indigo-700/50">
                                                                                {role === "PUBLIC" ? "VISITOR" : role}
                                                                            </span>
                                                                        ))}
                                                                    </div>
                                                                </td>
                                                                <td className="p-4 text-xs font-mono text-slate-400">{item.uploaded_at}</td>
                                                                <td className="p-4">
                                                                    {item.chunking_status === "COMPLETED" && (
                                                                        <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full text-xs font-bold">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                                                                            Chunked
                                                                        </span>
                                                                    )}
                                                                    {item.chunking_status === "PROCESSING" && (
                                                                        <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-full text-xs font-bold">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
                                                                            Processing
                                                                        </span>
                                                                    )}
                                                                    {item.chunking_status === "PENDING" && (
                                                                        <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-slate-500/10 text-slate-400 border border-slate-500/20 rounded-full text-xs font-bold">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                                                                            Pending
                                                                        </span>
                                                                    )}
                                                                    {item.chunking_status === "FAILED" && (
                                                                        <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-red-500/10 text-red-400 border border-red-500/20 rounded-full text-xs font-bold">
                                                                            <span className="w-1.5 h-1.5 rounded-full bg-red-400"></span>
                                                                            Failed
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
                                                            <th className="p-4 pl-6 font-semibold">User / Requester</th>
                                                            <th className="p-4 font-semibold">Question Asked</th>
                                                            <th className="p-4 font-semibold">Response</th>
                                                            <th className="p-4 w-32 font-semibold">Latency</th>
                                                            <th className="p-4 w-36 font-semibold">Type</th>
                                                            <th className="p-4 pr-6 w-24 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={idx} className="hover:bg-slate-800/40 transition-colors group">
                                                                <td className="p-4 pl-6 align-top">
                                                                    <div className="flex items-start gap-3">
                                                                        <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs shrink-0 ${
                                                                            item.user_role === 'ADMIN' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                                                                            item.user_role === 'LECTURER' ? 'bg-violet-500/10 text-violet-400 border border-violet-500/20' :
                                                                            item.user_role === 'STUDENT' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                                                                            item.user_role === 'STAFF' ? 'bg-sky-500/10 text-sky-400 border border-sky-500/20' :
                                                                            'bg-slate-800 text-slate-400 border border-slate-700/50'
                                                                        }`}>
                                                                            {item.user_name ? item.user_name.charAt(0).toUpperCase() : <Icon name="user" className="w-4 h-4"/>}
                                                                        </div>
                                                                        <div>
                                                                            <p className="font-bold text-slate-200 text-xs">{item.user_name || "Anonymous Visitor"}</p>
                                                                            <span className={`inline-block mt-0.5 text-[9px] font-bold tracking-wider px-1.5 py-0.2 rounded uppercase border ${
                                                                                item.user_role === 'ADMIN' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' :
                                                                                item.user_role === 'LECTURER' ? 'bg-violet-500/10 text-violet-400 border-violet-500/20' :
                                                                                item.user_role === 'STUDENT' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                                                                                item.user_role === 'STAFF' ? 'bg-sky-500/10 text-sky-400 border-sky-500/20' :
                                                                                'bg-slate-800 text-slate-400 border-slate-700/50'
                                                                            }`}>
                                                                                {item.user_role || "VISITOR"}
                                                                            </span>
                                                                            {item.user_email && <p className="text-[10px] text-slate-500 truncate max-w-[140px] mt-0.5">{item.user_email}</p>}
                                                                        </div>
                                                                    </div>
                                                                </td>
                                                                <td className="p-4 align-top max-w-xs">
                                                                    <p className="font-bold text-slate-200 text-xs leading-snug line-clamp-2">{item.query_text}</p>
                                                                    <span className="text-[10px] text-slate-500 font-mono mt-1 block">
                                                                        {item.timestamp ? new Date(item.timestamp).toLocaleString() : ''}
                                                                    </span>
                                                                </td>
                                                                <td className="p-4 align-top text-xs text-slate-400 leading-relaxed max-w-sm">
                                                                    <p className="line-clamp-2">{item.response_text || "No response recorded."}</p>
                                                                    {item.retrieved_chunks && item.retrieved_chunks.length > 0 && (
                                                                        <span className="text-[10px] text-indigo-400 font-mono mt-1 inline-flex items-center gap-1">
                                                                            <Icon name="book-open" className="w-3 h-3" /> {item.retrieved_chunks.length} source chunk{item.retrieved_chunks.length > 1 ? 's' : ''}
                                                                        </span>
                                                                    )}
                                                                </td>
                                                                <td className="p-4 align-top text-xs font-mono">
                                                                    {item.response_time_ms ? (
                                                                        <span className="px-2 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 font-semibold">
                                                                            {item.response_time_ms}ms
                                                                        </span>
                                                                    ) : (
                                                                        <span className="text-slate-600">N/A</span>
                                                                    )}
                                                                </td>
                                                                <td className="p-4 align-top text-xs">
                                                                    {item.is_navigational ? (
                                                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 font-bold uppercase tracking-wider text-[9px]">
                                                                            <Icon name="map" className="w-3 h-3"/> Navigation
                                                                        </span>
                                                                    ) : (
                                                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 border border-slate-700/50 text-slate-400 font-bold uppercase tracking-wider text-[9px]">
                                                                            <Icon name="info" className="w-3 h-3"/> Information
                                                                        </span>
                                                                    )}
                                                                </td>
                                                                <td className="p-4 pr-6 align-top text-right">
                                                                    <button
                                                                        onClick={() => { setSelectedItem(item); setModalType("view-chatbot-query"); setShowModal(true); }}
                                                                        title="View Details"
                                                                        className="p-1.5 bg-slate-800 hover:bg-indigo-600 hover:text-white border border-slate-700/50 text-slate-300 rounded-lg transition-colors inline-flex items-center gap-1 text-xs font-medium"
                                                                    >
                                                                        <Icon name="eye" className="w-3.5 h-3.5" />
                                                                    </button>
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
                                                            <th className="p-4 font-semibold">Authorized Roles</th>
                                                            <th className="p-4 font-semibold">Last Seen</th>
                                                            <th className="p-4 pr-6 text-right font-semibold">Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-800/50">
                                                        {paginatedData.map((item, idx) => (
                                                            <tr key={item.device_id ?? idx} onClick={() => setDrawerState({ record: item, kind: "device" })} className="hover:bg-slate-800/40 transition-colors cursor-pointer group">
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
                                                                    <div className="flex flex-wrap gap-1 max-w-xs">
                                                                        {item.allowed_role_ids && item.allowed_role_ids.length > 0 ? (
                                                                            item.allowed_role_ids.map(roleId => {
                                                                                const roleObj = refs.roles?.find(r => r.role_id === roleId);
                                                                                const roleName = roleObj ? roleObj.role_name : `Role ${roleId}`;
                                                                                return (
                                                                                    <span key={roleId} className="px-2 py-0.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded text-[11px] font-medium">
                                                                                        {roleName}
                                                                                    </span>
                                                                                );
                                                                            })
                                                                        ) : (
                                                                            <span className="text-xs text-rose-400/80 italic font-mono">None (Deny-All)</span>
                                                                        )}
                                                                    </div>
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
                                                                            if (item.ws_connected) return true;
                                                                            const diffMs = new Date() - dateObj;
                                                                            // 120 seconds threshold
                                                                            return diffMs >= 0 && diffMs <= 120000;
                                                                        })();
                                                                        const localTimeStr = `${String(dateObj.getHours()).padStart(2, '0')}:${String(dateObj.getMinutes()).padStart(2, '0')}`;
                                                                        const tel = item.telemetry || {};
                                                                        const skewWarn = typeof tel.clock_skew_seconds === 'number' && tel.clock_skew_seconds > 60;
                                                                        const backlogWarn = typeof tel.pending_logs === 'number' && tel.pending_logs > 100;
                                                                        return (
                                                                            <div className="flex flex-col gap-1 items-start">
                                                                                <div className="inline-flex items-center gap-2 bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg">
                                                                                    <span className={`w-2 h-2 rounded-full shrink-0 shadow-sm ${isOnline ? 'bg-emerald-400 shadow-emerald-500/50 animate-pulse' : 'bg-red-500 shadow-red-500/50'}`}></span>
                                                                                    <span className="text-xs font-semibold text-slate-300">
                                                                                        {isOnline ? (item.ws_connected ? `Live · ${localTimeStr}` : `Active ${localTimeStr}`) : 'Offline'}
                                                                                    </span>
                                                                                </div>
                                                                                {(skewWarn || backlogWarn || typeof tel.cached_users === 'number') && (
                                                                                    <div className="flex flex-wrap gap-1">
                                                                                        {typeof tel.cached_users === 'number' && (
                                                                                            <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60">{tel.cached_users} cached</span>
                                                                                        )}
                                                                                        {skewWarn && (
                                                                                            <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 font-semibold">Clock skew {Math.round(tel.clock_skew_seconds)}s</span>
                                                                                        )}
                                                                                        {backlogWarn && (
                                                                                            <span className="text-[10px] px-2 py-0.5 rounded bg-red-500/15 text-red-300 border border-red-500/30 font-semibold">{tel.pending_logs} queued</span>
                                                                                        )}
                                                                                    </div>
                                                                                )}
                                                                            </div>
                                                                        );
                                                                    })()}
                                                                </td>
                                                                <td className="p-4 pr-6 text-right">
                                                                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                        <button onClick={() => handleIssuePairingCode(item)} disabled={pendingActionKey === `pair:${item.device_id}`} title="Pair / Show QR Code" className="p-2 bg-slate-800 hover:bg-slate-700 text-amber-300 rounded-xl border border-slate-700/50 transition-all hover:border-amber-500/40 disabled:opacity-50 disabled:cursor-not-allowed">
                                                                            {pendingActionKey === `pair:${item.device_id}` ? <span className="block w-4 h-4 border-2 border-amber-400/30 border-t-amber-400 rounded-full animate-spin"></span> : <Icon name="qr-code" className="w-4 h-4" />}
                                                                        </button>
                                                                        <button onClick={() => handlePingDevice(item)} disabled={pendingActionKey === `ping:${item.device_id}`} title="Check Status" className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl border border-slate-700/50 transition-all hover:text-indigo-400 hover:border-indigo-500/30 disabled:opacity-50 disabled:cursor-not-allowed">
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
                                                            <tr key={item.log_id ?? idx} onClick={() => setDrawerState({ record: item, kind: "auth-log" })} className="hover:bg-slate-800/40 transition-colors cursor-pointer">
                                                                <td className="p-4 pl-6 font-mono text-slate-200 text-sm font-semibold">{item.email || "Unknown"}</td>
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
                                                                <td className="p-4 pl-6 font-mono text-slate-200 text-sm font-bold"><Icon name="shield" className="inline-block w-4 h-4 mr-2 text-indigo-400"/>{item.user?.email || item.admin_id || "—"}</td>
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
                                    createLabel={`Add ${getSingleTabLabel(subTab)}`}
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
                                                            <tr key={item.course_id ?? idx} onClick={() => setDrawerState({ record: item, kind: "course" })} className="hover:bg-slate-800/40 transition-colors cursor-pointer group">
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
                                                                <td className="p-4 text-xs font-semibold text-slate-400">Course <span className="text-indigo-400">{item.course_code || "Unknown"}</span></td>
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
                                                                <td className="p-4 pl-6 font-mono text-slate-200 text-sm font-semibold">Course <span className="text-indigo-400">{item.course_code || "Unknown"}</span></td>
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
                            <CampusMapTab setToast={setToast} />
                        )}

                        {/* ══ MODAL: CREATE / EDIT ══════════════════════════ */}
                        {showModal && (
                            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-md p-4 overflow-y-auto animate-in fade-in duration-200">
                                <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl p-6 md:p-8 shadow-2xl relative my-4 animate-in zoom-in-95 duration-200 ease-out">
                                    <div className="flex justify-between items-start mb-6">
                                        <div>
                                            <h3 className="text-xl font-bold text-slate-100 tracking-tight">
                                                {modalType === "create" ? "Add New Record" : modalType === "view-chatbot-query" ? "Chatbot Query Details" : "Edit Record"}
                                            </h3>
                                            <p className="text-xs text-slate-400 mt-1">
                                                {modalType === "view-chatbot-query" ? "Detailed inspection of user interaction and model response." : "Fill in the details below and save your changes."}
                                            </p>
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

                        {provisioningDetails && (
                            <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/90 backdrop-blur-md p-4 animate-in fade-in duration-200 overflow-y-auto">
                                <div className="w-full max-w-xl bg-slate-900 border border-amber-500/40 rounded-3xl p-6 md:p-8 shadow-2xl my-4">
                                    <div className="flex items-start justify-between gap-4 mb-5">
                                        <div className="flex items-start gap-4">
                                            <div className={`p-3 rounded-2xl border ${provisioningDetails.paired ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'bg-amber-500/10 text-amber-400 border-amber-500/20'}`}>
                                                <Icon name={provisioningDetails.paired ? "check-circle-2" : "qr-code"} className="w-6 h-6" />
                                            </div>
                                            <div>
                                                <h3 className="text-xl font-bold text-slate-100">Pair {provisioningDetails.deviceName || provisioningDetails.deviceId}</h3>
                                                <p className="text-sm text-slate-400 mt-1">
                                                    {provisioningDetails.paired
                                                        ? "Device has claimed its credentials and is syncing with the cloud."
                                                        : "Show this QR code to the Access Control kiosk or Surveillance camera, or enter the 8-character pairing code."}
                                                </p>
                                            </div>
                                        </div>
                                        <div className={`shrink-0 inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-bold border ${provisioningDetails.paired ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' : 'bg-amber-500/10 text-amber-300 border-amber-500/30'}`}>
                                            <span className={`w-2 h-2 rounded-full ${provisioningDetails.paired ? 'bg-emerald-400' : 'bg-amber-400 animate-pulse'}`}></span>
                                            {provisioningDetails.paired ? "Paired & Online" : "Waiting for device..."}
                                        </div>
                                    </div>

                                    {!provisioningDetails.paired && provisioningDetails.pairingCode && (
                                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-center rounded-2xl border border-slate-800 bg-slate-950/60 p-5 mb-5">
                                            <div className="flex flex-col items-center justify-center">
                                                {provisioningDetails.pairingQrSvgDataUri ? (
                                                    <img
                                                        src={provisioningDetails.pairingQrSvgDataUri}
                                                        alt="Device pairing QR code"
                                                        className="w-44 h-44 rounded-xl bg-white p-2 shadow-lg"
                                                    />
                                                ) : (
                                                    <div className="w-44 h-44 rounded-xl bg-slate-800 flex items-center justify-center text-xs text-slate-400 text-center p-4">
                                                        QR unavailable — use pairing code
                                                    </div>
                                                )}
                                                <span className="text-[11px] text-slate-400 mt-2">Expires in 15 minutes</span>
                                            </div>
                                            <div className="space-y-3">
                                                <div className="text-[10px] font-bold uppercase tracking-widest text-indigo-300">Pairing Code</div>
                                                <div className="font-mono text-2xl font-extrabold tracking-widest text-white bg-slate-900 border border-indigo-500/30 rounded-xl px-4 py-3 text-center select-all">
                                                    {provisioningDetails.pairingCode}
                                                </div>
                                                <ol className="list-decimal list-inside text-xs text-slate-300 space-y-1">
                                                    <li><span className="font-semibold text-slate-100">Access Control:</span> Point kiosk camera at QR or type the code.</li>
                                                    <li><span className="font-semibold text-slate-100">Surveillance:</span> Hold QR in front of camera or open <span className="font-mono text-indigo-300">/setup</span>.</li>
                                                </ol>
                                            </div>
                                        </div>
                                    )}

                                    <div className="space-y-2 text-sm mb-4">
                                        <div className="flex justify-between gap-4"><span className="text-slate-500">Device ID</span><span className="font-mono font-bold text-indigo-300">{provisioningDetails.deviceId}</span></div>
                                        <div className="flex justify-between gap-4"><span className="text-slate-500">Cloud URL</span><span className="font-mono text-slate-200">{window.location.origin}</span></div>
                                    </div>

                                    {provisioningDetails.secret && (
                                        <div className="mb-5">
                                            <button
                                                type="button"
                                                onClick={() => setProvisioningDetails(prev => prev ? { ...prev, showManualSecret: !prev.showManualSecret } : prev)}
                                                className="text-xs font-semibold text-slate-400 hover:text-amber-300 underline"
                                            >
                                                {provisioningDetails.showManualSecret ? "Hide manual secret (advanced)" : "Show manual secret for headless/.env deployment"}
                                            </button>
                                            {provisioningDetails.showManualSecret && (
                                                <div className="mt-2 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-3">
                                                    <div>
                                                        <div className="text-[10px] font-bold uppercase tracking-widest text-amber-300 mb-1">One-time secret</div>
                                                        <div className="font-mono text-xs md:text-sm text-amber-100 break-all select-all">{provisioningDetails.secret}</div>
                                                    </div>
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            const blob = new Blob([JSON.stringify({
                                                                cloud_url: window.location.origin,
                                                                device_id: provisioningDetails.deviceId,
                                                                device_name: provisioningDetails.deviceName || provisioningDetails.deviceId,
                                                                device_secret: provisioningDetails.secret,
                                                            }, null, 2)], { type: "application/json" });
                                                            const url = URL.createObjectURL(blob);
                                                            const a = document.createElement("a");
                                                            a.href = url;
                                                            a.download = `provision-${provisioningDetails.deviceId}.json`;
                                                            a.click();
                                                            URL.revokeObjectURL(url);
                                                        }}
                                                        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-amber-200 border border-amber-500/30"
                                                    >
                                                        <Icon name="download" className="w-3.5 h-3.5" />
                                                        Download provision.json
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    <div className="flex justify-end">
                                        <button onClick={() => setProvisioningDetails(null)} className={`font-bold px-5 py-2.5 rounded-xl text-sm ${provisioningDetails.paired ? 'bg-emerald-500 hover:bg-emerald-400 text-slate-950' : 'bg-amber-500 hover:bg-amber-400 text-slate-950'}`}>
                                            {provisioningDetails.paired ? "Done" : "Close"}
                                        </button>
                                    </div>
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
                                            setPhotoPose("front");
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
                                            <div className="space-y-2">
                                                <label className="text-xs font-bold text-slate-300">Pose to add or update</label>
                                                <select value={photoPose} onChange={e => setPhotoPose(e.target.value)}
                                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500">
                                                    <option value="front">Front (also refresh low-light template)</option>
                                                    <option value="left_30">Turn left 30°</option>
                                                    <option value="right_30">Turn right 30°</option>
                                                    <option value="left_60">Turn left 60°</option>
                                                    <option value="right_60">Turn right 60°</option>
                                                    <option value="slightly_up">Look slightly up</option>
                                                </select>
                                                <p className="text-[11px] text-slate-500">Existing face poses are kept. Upload another pose later to complete or update the enrollment.</p>
                                            </div>
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
                                                        ? <video ref={(el) => {
                                                            videoRef.current = el;
                                                            if (el && cameraStream && el.srcObject !== cameraStream) {
                                                                el.srcObject = cameraStream;
                                                                el.play().catch(() => {});
                                                            }
                                                          }} autoPlay playsInline muted className='absolute inset-0 w-full h-full object-cover -scale-x-100'/>
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
                                                        <div className='absolute inset-0 bg-black/70 flex flex-col items-center justify-center gap-4 pointer-events-none px-8'>
                                                            <div className='w-12 h-12 border-4 border-indigo-400 border-t-transparent rounded-full animate-spin'></div>
                                                            <div className='text-center space-y-1.5 w-full max-w-[240px]'>
                                                                <p className='text-white font-bold text-sm'>Embedding Face ID...</p>
                                                                <p className='text-slate-400 text-xs'>{embeddingProgress}% complete</p>
                                                                <div className='h-2 w-full bg-slate-950/80 rounded-full border border-white/5 overflow-hidden shadow-inner mt-2'>
                                                                    <div className='h-full bg-gradient-to-r from-teal-400 to-indigo-500 rounded-full transition-all duration-300'
                                                                        style={{width:`${embeddingProgress}%`}}></div>
                                                                </div>
                                                            </div>
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
                                                                <p className='text-sm font-bold text-white tracking-wide'>{enrollFeedback || curPose.label}</p>
                                                            </div>
                                                        </div>
                                                    )}

                                                    {/* ── LIVE / STANDBY badge ── */}
                                                    <div className='absolute top-3 left-3 flex items-center gap-1.5 bg-black/70 border border-white/10 px-2.5 py-1 rounded-lg text-[10px] font-bold'>
                                                        {recordingPhase === 'recording'
                                                            ? <><span className='w-2 h-2 rounded-full bg-red-500 animate-ping'></span><span className='text-red-400'>CAPTURING</span></>
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
                                                            <span>{recordingPhase === 'embedding' ? 'Embedding Face ID...' : 'Capturing front photo...'}</span>
                                                            <span>{phaseProgress}%</span>
                                                        </div>
                                                        <div className='w-full h-2 bg-slate-900 rounded-full overflow-hidden border border-slate-800 shadow-inner'>
                                                            <div className='h-full bg-gradient-to-r from-indigo-500 to-emerald-500 transition-all duration-200 rounded-full'
                                                                style={{width:`${phaseProgress}%`}}></div>
                                                        </div>
                                                    </div>
                                                )}

                                                {/* ── Single front capture instructions (idle/ready state) ── */}
                                                {(recordingPhase === 'idle' || recordingPhase === 'failed') && cameraStream && (
                                                    <div className='bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-2 shadow-inner'>
                                                        <p className='text-xs font-bold text-slate-400 uppercase tracking-wider'>Front-Facing Photo Capture</p>
                                                        <p className='text-xs text-slate-400 leading-relaxed'>
                                                            Position your face in the center of the frame and look directly into the camera. Only a single front-facing image will be captured for Face ID enrollment.
                                                        </p>
                                                    </div>
                                                )}

                                                {/* ── Error / failed feedback ── */}
                                                {recordingPhase === 'failed' && enrollFeedback && (
                                                    <div className='flex items-start gap-3 bg-red-950/40 border border-red-900/40 rounded-2xl p-4 shadow-sm'>
                                                        <Icon name='alert-circle' className='w-4 h-4 text-red-400 shrink-0 mt-0.5'/>
                                                        <div>
                                                            <p className='text-sm font-bold text-red-400'>Capture failed</p>
                                                            <p className='text-xs text-red-400/80 mt-0.5 leading-relaxed'>{enrollFeedback}</p>
                                                            <p className='text-xs text-slate-500 mt-1.5'>Try again — look straight at the camera and ensure good lighting.</p>
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
                                                                <Icon name='camera' className='w-4 h-4'/>
                                                                <span>{recordingPhase === 'failed' ? 'Capture Again' : 'Capture Photo'}</span>
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
                                                            <Icon name='square' className='w-3.5 h-3.5 fill-white'/><span>Cancel</span>
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
                        <RecordDrawer
                            record={drawerState.record}
                            kind={drawerState.kind}
                            refs={refs}
                            onClose={() => setDrawerState({ record: null, kind: "" })}
                            onEdit={(rec) => {
                                setDrawerState({ record: null, kind: "" });
                                setSelectedItem(rec);
                                setModalType("edit");
                                setShowModal(true);
                            }}
                            onDelete={(rec) => handleDeleteItem(rec)}
                            onToggleUserStatus={(rec) => handleToggleStatus(rec)}
                            onOpenFaceEnroll={(rec) => {
                                setDrawerState({ record: null, kind: "" });
                                setSelectedItem(rec);
                                setSelectedPhotoFile(null);
                                setUploadedPhoto(null);
                                setPhotoPose("front");
                                setEnrollMethod("photo");
                                setScanStep(0);
                                setScanning(false);
                                setShowFaceModal(true);
                            }}
                            onRevokeSession={handleRevokeUserSession}
                            onRotateDeviceSecret={null}
                        />
                        <ConfirmDialog
                            open={confirmState.open}
                            title={confirmState.title}
                            message={confirmState.message}
                            confirmLabel={confirmState.confirmLabel}
                            variant={confirmState.variant}
                            busy={bulkBusy || Boolean(pendingActionKey)}
                            onConfirm={confirmState.onConfirm}
                            onCancel={() => setConfirmState(prev => ({ ...prev, open: false }))}
                        />
                        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
                    </main>
                </div>
            </div>
        );
    }
