const { useState, useEffect, useRef } = React;

// ==========================================================
// SEARCHABLE DROPDOWN COMPONENT (Custom Search + Dropdown)
// ==========================================================
function SearchableDropdown({ list, value, onChange, placeholder, filterFn, displayFn, valueFn }) {
    const [query, setQuery] = useState("");
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef(null);

    useEffect(() => {
        if (valueFn) {
            const selected = list.find(item => String(valueFn(item)) === String(value));
            setQuery(selected ? displayFn(selected) : (value || ""));
        } else {
            setQuery(value || "");
        }
    }, [value, list]);

    useEffect(() => {
        function handleClickOutside(event) {
            if (containerRef.current && !containerRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

    const filtered = list.filter(item => {
        const q = query.toLowerCase();
        return filterFn(item, q);
    });

    return (
        <div className="relative" ref={containerRef}>
            <div className="relative flex items-center">
                <input
                    type="text"
                    placeholder={placeholder}
                    value={query}
                    onChange={e => {
                        const val = e.target.value;
                        setQuery(val);
                        onChange(val);
                        setIsOpen(true);
                    }}
                    onFocus={() => setIsOpen(true)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-4 pr-10 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 transition-all placeholder:text-slate-600"
                />
                <button
                    type="button"
                    onClick={() => setIsOpen(!isOpen)}
                    className="absolute right-3 text-slate-500 hover:text-slate-300"
                >
                    <svg className={`w-4 h-4 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                    </svg>
                </button>
            </div>
            {isOpen && (
                <div className="absolute left-0 z-50 w-full mt-1.5 max-h-60 overflow-y-auto bg-slate-950 border border-slate-800 rounded-xl shadow-2xl divide-y divide-slate-900 scrollbar-thin">
                    {filtered.map((item, idx) => (
                        <div
                            key={idx}
                            onClick={() => {
                                const displayVal = displayFn(item);
                                const submitVal = valueFn ? valueFn(item) : displayVal;
                                setQuery(displayVal);
                                onChange(submitVal, item);
                                setIsOpen(false);
                            }}
                            className="p-3 hover:bg-slate-900 cursor-pointer text-sm transition-colors duration-150 text-slate-200"
                        >
                            {displayFn(item)}
                        </div>
                    ))}
                    {filtered.length === 0 && (
                        <div className="p-3 text-slate-500 text-xs text-center">No matching options</div>
                    )}
                </div>
            )}
        </div>
    );
}

// ==========================================================
// AUTOCOMPLETE SEARCH COMPONENT (Google-style similarity search)
// ==========================================================
function AutocompleteSearch({ list, onSelect, filterFn, renderItem, placeholder }) {
    const [query, setQuery] = useState("");
    const [isOpen, setIsOpen] = useState(false);
    
    const filtered = list.filter(item => filterFn(item, query.toLowerCase()));

    return (
        <div className="relative">
            <div className="relative flex items-center">
                <input
                    type="text"
                    placeholder={placeholder}
                    value={query}
                    onChange={e => {
                        setQuery(e.target.value);
                        setIsOpen(true);
                    }}
                    onFocus={() => setIsOpen(true)}
                    onBlur={() => setTimeout(() => setIsOpen(false), 250)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-4 pr-10 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 transition-all placeholder:text-slate-600"
                />
                <button
                    type="button"
                    onClick={() => setIsOpen(!isOpen)}
                    className="absolute right-3 text-slate-500 hover:text-slate-300"
                >
                    <svg className={`w-4 h-4 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                    </svg>
                </button>
            </div>
            {isOpen && (
                <div className="absolute top-full left-0 z-50 w-full mt-1.5 max-h-60 overflow-y-auto bg-slate-950 border border-slate-800 rounded-xl shadow-2xl divide-y divide-slate-900 scrollbar-thin">
                    {filtered.map((item, idx) => (
                        <div
                            key={idx}
                            onMouseDown={() => {
                                onSelect(item, setQuery);
                                setIsOpen(false);
                            }}
                            className="p-3 hover:bg-slate-900 cursor-pointer text-sm transition-colors duration-150 text-slate-200"
                        >
                            {renderItem(item)}
                        </div>
                    ))}
                    {filtered.length === 0 && (
                        <div className="p-3 text-slate-500 text-xs text-center">No matching records found</div>
                    )}
                </div>
            )}
        </div>
    );
}

// ==========================================================
// SUBFORM COMPONENT UTILITIES (React elements)
// ==========================================================

// 1. Unified User Form Component
function UserForm({ item, roles, nodes, programmes = [], faculties = [], departments = [], onSubmit, onCancel }) {
    const isEdit = !!item;
    
    // User core states
    const [givenName, setGivenName] = useState(item?.given_name || "");
    const [familyName, setFamilyName] = useState(item?.family_name || "");
    const [email, setEmail] = useState(item?.email || "");
    const [roleId, setRoleId] = useState(item?.role_id || item?.roles?.[0]?.role_id || "");
    const [isActive, setIsActive] = useState(item ? item.is_active : true);
    const [locationId, setLocationId] = useState(item?.last_known_location || "");
    const [editRole, setEditRole] = useState(false);

    // ── Link to Existing User ──────────────────────────────────
    const [linkExisting, setLinkExisting] = useState(false);
    const [linkedUserId, setLinkedUserId] = useState(null);
    const [systemUsers, setSystemUsers] = useState([]);
    const [userSearchQuery, setUserSearchQuery] = useState("");
    const [userDropdownOpen, setUserDropdownOpen] = useState(false);
    const userSearchRef = useRef(null);

    useEffect(() => {
        if (!isEdit) {
            const token = localStorage.getItem("access_token");
            fetch("/api/iam/users", { headers: { "Authorization": `Bearer ${token}` } })
                .then(res => res.json())
                .then(data => { if (Array.isArray(data)) setSystemUsers(data); })
                .catch(() => {});
        }
    }, []);

    useEffect(() => {
        function handleOutside(e) {
            if (userSearchRef.current && !userSearchRef.current.contains(e.target)) setUserDropdownOpen(false);
        }
        document.addEventListener("mousedown", handleOutside);
        return () => document.removeEventListener("mousedown", handleOutside);
    }, []);

    const filteredUsers = systemUsers.filter(u => {
        const q = userSearchQuery.toLowerCase();
        return u.full_name?.toLowerCase().includes(q) ||
               u.email?.toLowerCase().includes(q) ||
               String(u.user_id).includes(q);
    });

    const handleLinkUser = (u) => {
        setLinkedUserId(u.user_id);
        setGivenName(u.given_name || "");
        setFamilyName(u.family_name || "");
        setEmail(u.email);
        setRoleId(u.role_id || u.roles?.[0]?.role_id || "");
        setUserSearchQuery(`${u.full_name} (@${u.email})`);
        setUserDropdownOpen(false);
    };

    const handleUnlink = () => {
        setLinkedUserId(null);
        setGivenName(""); setFamilyName(""); setEmail(""); setRoleId("");
        setUserSearchQuery("");
    };

    // ── Face Photo Upload ──────────────────────────────────────
    // Find active role details
    const selectedRole = roles.find(r => r.role_id === parseInt(roleId));
    const roleName = selectedRole ? selectedRole.role_name : "";

    // Sub-profile states
    // Student
    const [studentId, setStudentId] = useState(item?.student?.student_id || "");
    const [program, setProgram] = useState(item?.student?.programme_id || item?.student?.program || "");
    const [faculty, setFaculty] = useState(item?.student?.faculty_id || item?.lecturer?.faculty_id || item?.student?.faculty || item?.lecturer?.faculty || "");
    const [intake, setIntake] = useState(item?.student?.intake || "");
    const [enrolledSince, setEnrolledSince] = useState(item?.student?.enrolled_since || new Date().toISOString().split('T')[0]);

    // Lecturer / Staff / Admin / Visitor common department, faculty & office
    const [lecturerId, setLecturerId] = useState(item?.lecturer?.lecturer_id || "");
    const [department, setDepartment] = useState(item?.lecturer?.department_id || item?.staff?.department_id || item?.admin?.department_id || item?.lecturer?.department || item?.staff?.department || item?.admin?.department || "");
    const [position, setPosition] = useState(item?.lecturer?.position || item?.staff?.position || "");
    const [isHoD, setIsHoD] = useState(item?.lecturer?.is_head_of_department || false);
    const [officeNodeId, setOfficeNodeId] = useState(item?.lecturer?.office_node_id || item?.staff?.office_node_id || item?.admin?.office_node_id || "");

    const [staffId, setStaffId] = useState(item?.staff?.staff_id || item?.admin?.staff_id || "");
    const [staffType, setStaffType] = useState(item?.staff?.staff_type || "ADMINISTRATIVE");
    
    const [visitorId, setVisitorId] = useState(item?.visitor?.visitor_id || "");
    const [idNumber, setIdNumber] = useState(item?.visitor?.id_number || "");
    const [organization, setOrganization] = useState(item?.visitor?.organization || "");
    const [visitPurpose, setVisitPurpose] = useState(item?.visitor?.visit_purpose || "");
    const [accessExpiry, setAccessExpiry] = useState(item?.visitor?.access_expiry ? new Date(item.visitor.access_expiry).toISOString().slice(0, 16) : new Date(Date.now() + 86400000).toISOString().slice(0, 16));
    const [registeredBy, setRegisteredBy] = useState(item?.visitor?.registered_by || 1);

    const [adminId, setAdminId] = useState(item?.admin?.admin_id || "");
    const [adminType, setAdminType] = useState(item?.admin?.admin_type || "SYSTEM_ADMIN");
    const [password, setPassword] = useState("");

    // Real-time email generation
    useEffect(() => {
        if (!isEdit) {
            const cleanGiven = givenName.toLowerCase().replace(/[^a-z0-9]/g, "");
            const cleanFamily = familyName.toLowerCase().replace(/[^a-z0-9]/g, "");
            if (cleanGiven || cleanFamily) {
                setEmail(`${cleanGiven}.${cleanFamily}@qiu.edu.my`);
            } else {
                setEmail("");
            }
        }
    }, [givenName, familyName, isEdit]);

    // Custom Validation states
    const [errors, setErrors] = useState({});

    const findProgramme = (value) => programmes.find(p => String(p.programme_id) === String(value) || p.programme_name === value);
    const findFaculty = (value) => faculties.find(f => String(f.faculty_id) === String(value) || f.faculty_name === value);
    const findDepartment = (value) => departments.find(d => String(d.department_id) === String(value) || d.department_name === value);

    const validate = () => {
        let err = {};
        if (!linkExisting || isEdit) {
            if (!givenName.trim()) err.givenName = "Given name is required";
            if (!familyName.trim()) err.familyName = "Family name is required";
            if (!email.trim()) err.email = "email is required";
        }
        if (!roleId) err.roleId = "Role selection is required";

        if (roleName === "STUDENT") {
            if (!program.trim()) err.program = "Program selection is required";
            else if (programmes.length > 0 && !findProgramme(program)) err.program = "Select a valid programme from the list";
            if (!faculty.trim()) err.faculty = "Faculty selection is required";
            else if (faculties.length > 0 && !findFaculty(faculty)) err.faculty = "Select a valid faculty from the list";
            if (!/^\d{6}$/.test(String(intake).trim())) err.intake = "Intake must be exactly 6 digits, for example 202407";
            if (!enrolledSince) err.enrolledSince = "Enrollment date is required";
        } else if (roleName === "LECTURER") {
            if (!department.trim()) err.department = "Department selection is required";
            else if (departments.length > 0 && !findDepartment(department)) err.department = "Select a valid department from the list";
            if (!faculty.trim()) err.faculty = "Faculty selection is required";
            else if (faculties.length > 0 && !findFaculty(faculty)) err.faculty = "Select a valid faculty from the list";
            if (!position.trim()) err.position = "Position is required";
        } else if (roleName === "STAFF") {
            if (!department.trim()) err.department = "Department selection is required";
            else if (departments.length > 0 && !findDepartment(department)) err.department = "Select a valid department from the list";
            if (!position.trim()) err.position = "Position is required";
            if (!staffType) err.staffType = "Staff type selection is required";
        } else if (roleName === "VISITOR") {
            if (!idNumber.trim()) err.idNumber = "ID number is required";
            if (!accessExpiry) err.accessExpiry = "Access expiry datetime is required";
        } else if (roleName === "ADMIN") {
            if (!adminType) err.adminType = "Admin type selection is required";
            if (!isEdit && !password.trim()) err.password = "Admin setup password is required";
            if (!department.trim()) err.department = "Department selection is required";
            else if (departments.length > 0 && !findDepartment(department)) err.department = "Select a valid department from the list";
        }

        setErrors(err);
        return Object.keys(err).length === 0;
    };

    const handleFormSubmit = (e) => {
        e.preventDefault();
        if (!validate()) return;
        
        let profileData = {};
        if (roleName === "STUDENT") {
            const selectedProgramme = findProgramme(program);
            const selectedFaculty = findFaculty(faculty);
            profileData = {
                student_id: studentId || null,
                programme_id: selectedProgramme ? selectedProgramme.programme_id : program,
                faculty_id: selectedFaculty ? selectedFaculty.faculty_id : faculty,
                intake: parseInt(String(intake).trim(), 10),
                enrolled_since: enrolledSince
            };
        } else if (roleName === "LECTURER") {
            const selectedDepartment = findDepartment(department);
            const selectedFaculty = findFaculty(faculty);
            profileData = {
                lecturer_id: lecturerId || null,
                department_id: selectedDepartment ? selectedDepartment.department_id : department,
                faculty_id: selectedFaculty ? selectedFaculty.faculty_id : faculty,
                position: position,
                is_head_of_department: isHoD,
                office_node_id: officeNodeId ? parseInt(officeNodeId) : null
            };
        } else if (roleName === "STAFF") {
            const selectedDepartment = findDepartment(department);
            profileData = {
                staff_id: staffId || null,
                department_id: selectedDepartment ? selectedDepartment.department_id : department,
                position: position,
                staff_type: staffType,
                office_node_id: officeNodeId ? parseInt(officeNodeId) : null
            };
        } else if (roleName === "VISITOR") {
            profileData = {
                visitor_id: visitorId || null,
                id_number: idNumber,
                organization: organization,
                visit_purpose: visitPurpose,
                access_expiry: new Date(accessExpiry).toISOString(),
                registered_by: registeredBy
            };
        } else if (roleName === "ADMIN") {
            const selectedDepartment = findDepartment(department);
            profileData = {
                admin_id: adminId || null,
                admin_type: adminType,
                department_id: selectedDepartment ? selectedDepartment.department_id : department,
                office_node_id: officeNodeId ? parseInt(officeNodeId) : null,
                password: password || null
            };
        }

        // When linking to existing user, inject user_id into profile payload
        if (linkExisting && linkedUserId) {
            profileData.user_id = linkedUserId;
        }

        onSubmit(e, {
            isEdit,
            roleName,
            user_id: item?.user_id,
            user_payload: {
                given_name: givenName,
                family_name: familyName,
                email: email,
                role_id: parseInt(roleId),
                is_active: isActive,
                last_known_location: locationId ? parseInt(locationId) : null
            },
            profile_payload: profileData
        });
    };

    const getInputClass = (errFlag) => {
        return `w-full bg-slate-950 border rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none transition-all ${errFlag ? 'border-rose-500 focus:border-rose-500' : 'border-slate-800 focus:border-emerald-500'}`;
    };

    return (
        <form onSubmit={handleFormSubmit} noValidate className="space-y-4 max-h-[80vh] overflow-y-auto pr-2">

            {/* ── Link to Existing User Account (create mode only) ── */}
            {!isEdit && (
                <div className="border border-slate-700/60 rounded-xl p-4 bg-slate-900/60">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-xs font-bold uppercase tracking-wider text-slate-300">Link to Existing User Account</p>
                            <p className="text-[11px] text-slate-500 mt-0.5">Attach this profile to a user already in the system.</p>
                        </div>
                        <button
                            type="button"
                            onClick={() => { setLinkExisting(!linkExisting); if (linkExisting) handleUnlink(); }}
                            className={`relative w-11 h-6 rounded-full transition-colors duration-300 focus:outline-none ${linkExisting ? 'bg-emerald-500' : 'bg-slate-700'}`}
                        >
                            <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-300 ${linkExisting ? 'translate-x-5' : 'translate-x-0'}`}></span>
                        </button>
                    </div>

                    {linkExisting && (
                        <div className="mt-3 relative" ref={userSearchRef}>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-1.5">Search Existing User</label>
                            <div className="relative flex items-center">
                                <input
                                    type="text"
                                    placeholder="Search by name, email or user ID..."
                                    value={userSearchQuery}
                                    onChange={e => { setUserSearchQuery(e.target.value); setUserDropdownOpen(true); if (!e.target.value) handleUnlink(); }}
                                    onFocus={() => setUserDropdownOpen(true)}
                                    className="w-full bg-slate-950 border border-slate-700 rounded-xl pl-4 pr-10 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 transition-all placeholder:text-slate-600"
                                />
                                <svg className={`absolute right-3 w-4 h-4 text-slate-500 pointer-events-none transition-transform duration-200 ${userDropdownOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                                </svg>
                            </div>
                            {userDropdownOpen && filteredUsers.length > 0 && (
                                <div className="absolute left-0 z-50 w-full mt-1.5 max-h-52 overflow-y-auto bg-slate-950 border border-slate-800 rounded-xl shadow-2xl divide-y divide-slate-900">
                                    {filteredUsers.map((u, idx) => (
                                        <div
                                            key={idx}
                                            onMouseDown={() => handleLinkUser(u)}
                                            className="p-3 hover:bg-slate-900 cursor-pointer transition-colors duration-150"
                                        >
                                            <p className="text-sm font-semibold text-slate-200">{u.full_name}</p>
                                            <p className="text-xs text-slate-500 mt-0.5">@{u.email} &bull; UID: {u.user_id} &bull; {u.email}</p>
                                        </div>
                                    ))}
                                </div>
                            )}
                            {userDropdownOpen && filteredUsers.length === 0 && userSearchQuery && (
                                <div className="absolute left-0 z-50 w-full mt-1.5 bg-slate-950 border border-slate-800 rounded-xl shadow-2xl p-3 text-xs text-slate-500 text-center">
                                    No matching users found
                                </div>
                            )}
                            {linkedUserId && (
                                <div className="mt-2 flex items-center gap-2 text-xs text-emerald-400 font-semibold">
                                    <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block animate-pulse"></span>
                                    Linked to User ID: {linkedUserId}
                                    <button type="button" onClick={handleUnlink} className="text-slate-500 hover:text-rose-400 ml-1 font-normal transition-colors">&#x2715; Unlink</button>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Core User Fields */}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                    <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Given Name</label>
                    <input 
                        type="text" 
                        value={givenName} 
                        onChange={e => {
                            setGivenName(e.target.value);
                            if (errors.givenName) setErrors(prev => ({ ...prev, givenName: "" }));
                        }} 
                        className={getInputClass(errors.givenName)} 
                    />
                    {errors.givenName && (
                        <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                            <span>{errors.givenName}</span>
                        </p>
                    )}
                </div>
                <div>
                    <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Family Name</label>
                    <input 
                        type="text" 
                        value={familyName} 
                        onChange={e => {
                            setFamilyName(e.target.value);
                            if (errors.familyName) setErrors(prev => ({ ...prev, familyName: "" }));
                        }} 
                        className={getInputClass(errors.familyName)} 
                    />
                    {errors.familyName && (
                        <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                            <span>{errors.familyName}</span>
                        </p>
                    )}
                </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                    <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Email Address</label>
                    <input 
                        type="email" 
                        value={email} 
                        onChange={e => {
                            setEmail(e.target.value);
                            if (errors.email) setErrors(prev => ({ ...prev, email: "" }));
                        }}
                        placeholder="given_name.familyname@qiu.edu.my"
                        className={getInputClass(errors.email)} 
                    />
                    {errors.email && (
                        <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                            <span>{errors.email}</span>
                        </p>
                    )}
                </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                    <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
                        {isEdit ? "Role" : "Role Access Level"}
                    </label>
                    <select 
                        value={roleId} 
                        onChange={e => {
                            setRoleId(e.target.value);
                            if (errors.roleId) setErrors(prev => ({ ...prev, roleId: "" }));
                        }} 
                        className={getInputClass(errors.roleId)}
                    >
                        <option value="">Select Role</option>
                        {roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)}
                    </select>
                    {errors.roleId && (
                        <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                            <span>{errors.roleId}</span>
                        </p>
                    )}
                </div>
            </div>

            {/* Dynamic Role-specific fields */}
            {roleName === "STUDENT" && (
                <div className="border-t border-slate-800 pt-4 mt-2 space-y-4">
                    <span className="text-xs text-emerald-400 font-extrabold tracking-widest uppercase">Student Profile Parameters</span>
                    
                    {/* Ask student ID ONLY if editing (linking to existing account) */}
                    {isEdit && (
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Student ID</label>
                            <input 
                                type="text" 
                                value={studentId} 
                                onChange={e => setStudentId(e.target.value)} 
                                className={getInputClass(errors.studentId)} 
                            />
                        </div>
                    )}

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Program</label>
                            <SearchableDropdown
                                list={programmes}
                                value={program}
                                onChange={(val, item) => {
                                    setProgram(val);
                                    if (item?.faculty_id) setFaculty(item.faculty_id);
                                    if (errors.program) setErrors(prev => ({ ...prev, program: "" }));
                                    if (errors.faculty) setErrors(prev => ({ ...prev, faculty: "" }));
                                }}
                                placeholder="Search program (e.g. Computer Science)"
                                filterFn={(p, q) => p.programme_name.toLowerCase().includes(q) || p.programme_id.toLowerCase().includes(q)}
                                displayFn={p => p.programme_name}
                                valueFn={p => p.programme_id}
                            />
                            {errors.program && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.program}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Faculty Department</label>
                            <SearchableDropdown
                                list={faculties}
                                value={faculty}
                                onChange={val => {
                                    setFaculty(val);
                                    if (errors.faculty) setErrors(prev => ({ ...prev, faculty: "" }));
                                }}
                                placeholder="Search faculty (e.g. FCI)"
                                filterFn={(f, q) => f.faculty_name.toLowerCase().includes(q) || f.faculty_id.toLowerCase().includes(q)}
                                displayFn={f => f.faculty_name}
                                valueFn={f => f.faculty_id}
                            />
                            {errors.faculty && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.faculty}</span>
                                </p>
                            )}
                        </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Intake Semester Code</label>
                            <input 
                                type="text"
                                inputMode="numeric"
                                maxLength="6"
                                pattern="\d{6}"
                                value={intake} 
                                onChange={e => {
                                    setIntake(e.target.value.replace(/\D/g, "").slice(0, 6));
                                    if (errors.intake) setErrors(prev => ({ ...prev, intake: "" }));
                                }} 
                                className={getInputClass(errors.intake)} 
                            />
                            {errors.intake && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.intake}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Enrolled Since</label>
                            <input 
                                type="date" 
                                value={enrolledSince} 
                                onChange={e => {
                                    setEnrolledSince(e.target.value);
                                    if (errors.enrolledSince) setErrors(prev => ({ ...prev, enrolledSince: "" }));
                                }} 
                                className={getInputClass(errors.enrolledSince)} 
                            />
                            {errors.enrolledSince && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.enrolledSince}</span>
                                </p>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {roleName === "LECTURER" && (
                <div className="border-t border-slate-800 pt-4 mt-2 space-y-4">
                    <span className="text-xs text-emerald-400 font-extrabold tracking-widest uppercase">Lecturer Profile Parameters</span>
                    
                    {isEdit && (
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Lecturer ID</label>
                            <input type="text" value={lecturerId} onChange={e => setLecturerId(e.target.value)} className={getInputClass(errors.lecturerId)} />
                        </div>
                    )}

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Department</label>
                            <SearchableDropdown
                                list={departments}
                                value={department}
                                onChange={val => {
                                    setDepartment(val);
                                    if (errors.department) setErrors(prev => ({ ...prev, department: "" }));
                                }}
                                placeholder="Search department"
                                filterFn={(d, q) => d.department_name.toLowerCase().includes(q) || d.department_id.toLowerCase().includes(q)}
                                displayFn={d => d.department_name}
                                valueFn={d => d.department_id}
                            />
                            {errors.department && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.department}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Faculty</label>
                            <SearchableDropdown
                                list={faculties}
                                value={faculty}
                                onChange={val => {
                                    setFaculty(val);
                                    if (errors.faculty) setErrors(prev => ({ ...prev, faculty: "" }));
                                }}
                                placeholder="Search faculty"
                                filterFn={(f, q) => f.faculty_name.toLowerCase().includes(q) || f.faculty_id.toLowerCase().includes(q)}
                                displayFn={f => f.faculty_name}
                                valueFn={f => f.faculty_id}
                            />
                            {errors.faculty && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.faculty}</span>
                                </p>
                            )}
                        </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Position Title</label>
                            <input 
                                type="text" 
                                value={position} 
                                onChange={e => {
                                    setPosition(e.target.value);
                                    if (errors.position) setErrors(prev => ({ ...prev, position: "" }));
                                }} 
                                className={getInputClass(errors.position)} 
                            />
                            {errors.position && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.position}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Office Room Node</label>
                            <select 
                                value={officeNodeId} 
                                onChange={e => setOfficeNodeId(e.target.value)} 
                                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">No Assigned Office</option>
                                {nodes.filter(n => n.node_type === 'OFFICE').map(n => <option key={n.node_id} value={n.node_id}>{n.room_label || `Node ${n.node_id}`}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <input 
                            type="checkbox" 
                            checked={isHoD} 
                            onChange={e => setIsHoD(e.target.checked)} 
                            id="isHoD" 
                            className="w-4 h-4 text-emerald-600 bg-slate-950 border-slate-800 rounded focus:ring-emerald-500" 
                        />
                        <label htmlFor="isHoD" className="text-xs text-slate-400 font-bold uppercase tracking-wider">Is Head of Department</label>
                    </div>
                </div>
            )}

            {roleName === "STAFF" && (
                <div className="border-t border-slate-800 pt-4 mt-2 space-y-4">
                    <span className="text-xs text-emerald-400 font-extrabold tracking-widest uppercase">Staff Profile Parameters</span>
                    
                    {isEdit && (
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Staff ID</label>
                            <input type="text" value={staffId} onChange={e => setStaffId(e.target.value)} className={getInputClass(errors.staffId)} />
                        </div>
                    )}

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Department</label>
                            <SearchableDropdown
                                list={departments}
                                value={department}
                                onChange={val => {
                                    setDepartment(val);
                                    if (errors.department) setErrors(prev => ({ ...prev, department: "" }));
                                }}
                                placeholder="Search department"
                                filterFn={(d, q) => d.department_name.toLowerCase().includes(q) || d.department_id.toLowerCase().includes(q)}
                                displayFn={d => d.department_name}
                                valueFn={d => d.department_id}
                            />
                            {errors.department && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.department}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Staff Type</label>
                            <select 
                                value={staffType} 
                                onChange={e => {
                                    setStaffType(e.target.value);
                                    if (errors.staffType) setErrors(prev => ({ ...prev, staffType: "" }));
                                }} 
                                className={getInputClass(errors.staffType)}
                            >
                                <option value="ADMINISTRATIVE">ADMINISTRATIVE</option>
                                <option value="TECHNICAL">TECHNICAL</option>
                                <option value="SECURITY">SECURITY</option>
                                <option value="FACILITIES">FACILITIES</option>
                                <option value="OTHER">OTHER</option>
                            </select>
                            {errors.staffType && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.staffType}</span>
                                </p>
                            )}
                        </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Position Title</label>
                            <input 
                                type="text" 
                                value={position} 
                                onChange={e => {
                                    setPosition(e.target.value);
                                    if (errors.position) setErrors(prev => ({ ...prev, position: "" }));
                                }} 
                                className={getInputClass(errors.position)} 
                            />
                            {errors.position && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.position}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Office Room Node</label>
                            <select 
                                value={officeNodeId} 
                                onChange={e => setOfficeNodeId(e.target.value)} 
                                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">No Assigned Office</option>
                                {nodes.filter(n => n.node_type === 'OFFICE').map(n => <option key={n.node_id} value={n.node_id}>{n.room_label || `Node ${n.node_id}`}</option>)}
                            </select>
                        </div>
                    </div>
                </div>
            )}

            {roleName === "VISITOR" && (
                <div className="border-t border-slate-800 pt-4 mt-2 space-y-4">
                    <span className="text-xs text-emerald-400 font-extrabold tracking-widest uppercase">Visitor Profile Parameters</span>
                    
                    {isEdit && (
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Visitor ID</label>
                            <input type="text" value={visitorId} onChange={e => setVisitorId(e.target.value)} className={getInputClass(errors.visitorId)} />
                        </div>
                    )}

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">ID Card Number</label>
                            <input 
                                type="text" 
                                value={idNumber} 
                                onChange={e => {
                                    setIdNumber(e.target.value);
                                    if (errors.idNumber) setErrors(prev => ({ ...prev, idNumber: "" }));
                                }} 
                                className={getInputClass(errors.idNumber)} 
                            />
                            {errors.idNumber && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.idNumber}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Organization</label>
                            <input type="text" value={organization} onChange={e => setOrganization(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Access Expiry</label>
                            <input 
                                type="datetime-local" 
                                value={accessExpiry} 
                                onChange={e => {
                                    setAccessExpiry(e.target.value);
                                    if (errors.accessExpiry) setErrors(prev => ({ ...prev, accessExpiry: "" }));
                                }} 
                                className={getInputClass(errors.accessExpiry)} 
                            />
                            {errors.accessExpiry && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.accessExpiry}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Visit Purpose</label>
                            <input type="text" value={visitPurpose} onChange={e => setVisitPurpose(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>
                </div>
            )}

            {roleName === "ADMIN" && (
                <div className="border-t border-slate-800 pt-4 mt-2 space-y-4">
                    <span className="text-xs text-emerald-400 font-extrabold tracking-widest uppercase">Admin Profile Parameters</span>
                    
                    {isEdit && (
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Admin ID</label>
                            <input type="text" value={adminId} onChange={e => setAdminId(e.target.value)} className={getInputClass(errors.adminId)} />
                        </div>
                    )}

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Admin Type</label>
                            <select 
                                value={adminType} 
                                onChange={e => {
                                    setAdminType(e.target.value);
                                    if (errors.adminType) setErrors(prev => ({ ...prev, adminType: "" }));
                                }} 
                                className={getInputClass(errors.adminType)}
                            >
                                <option value="SUPER_ADMIN">SUPER_ADMIN</option>
                                <option value="SYSTEM_ADMIN">SYSTEM_ADMIN</option>
                                <option value="CONTENT_ADMIN">CONTENT_ADMIN</option>
                            </select>
                            {errors.adminType && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.adminType}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Password</label>
                            <input 
                                type="password" 
                                placeholder={isEdit ? "(Leave blank to keep unchanged)" : "Enter password"}
                                value={password} 
                                onChange={e => {
                                    setPassword(e.target.value);
                                    if (errors.password) setErrors(prev => ({ ...prev, password: "" }));
                                }} 
                                className={getInputClass(errors.password)} 
                            />
                            {errors.password && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.password}</span>
                                </p>
                            )}
                        </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Department</label>
                            <SearchableDropdown
                                list={departments}
                                value={department}
                                onChange={val => {
                                    setDepartment(val);
                                    if (errors.department) setErrors(prev => ({ ...prev, department: "" }));
                                }}
                                placeholder="Search department"
                                filterFn={(d, q) => d.department_name.toLowerCase().includes(q) || d.department_id.toLowerCase().includes(q)}
                                displayFn={d => d.department_name}
                                valueFn={d => d.department_id}
                            />
                            {errors.department && (
                                <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                                    <span>{errors.department}</span>
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Office Room Node</label>
                            <select 
                                value={officeNodeId} 
                                onChange={e => setOfficeNodeId(e.target.value)} 
                                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
                            >
                                <option value="">No Assigned Office</option>
                                {nodes.filter(n => n.node_type === 'OFFICE').map(n => <option key={n.node_id} value={n.node_id}>{n.room_label || `Node ${n.node_id}`}</option>)}
                            </select>
                        </div>
                    </div>
                </div>
            )}

            <div className="flex justify-end gap-3 mt-6">
                <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Submit Setup</button>
            </div>
        </form>
    );
}

// 2. Student Profile Form
        function StudentForm({ item, roles, onSubmit, onCancel }) {
            const [studentId, setStudentId] = useState(item?.student_id || "");
            const [program, setProgram] = useState(item?.program || "");
            const [faculty, setFaculty] = useState(item?.faculty || "");
            const [intake, setIntake] = useState(item?.intake || "");
            const [enrolledSince, setEnrolledSince] = useState(item?.enrolled_since || new Date().toISOString().split('T')[0]);
            
            // Nested User properties
            const [fullName, setFullName] = useState(item?.user?.full_name || "");
            const [email, setEmail] = useState(item?.user?.email || "");
            const [roleId, setRoleId] = useState(item?.user?.role_id || "");
            const [editRole, setEditRole] = useState(false);

            // Multi-role linking states
            const [linkExisting, setLinkExisting] = useState(false);
            const [userId, setUserId] = useState("");
            const [systemUsers, setSystemUsers] = useState([]);

            const isEdit = !!item;

            useEffect(() => {
                if (!isEdit) {
                    const token = localStorage.getItem("access_token");
                    fetch("/api/iam/users", {
                        headers: { "Authorization": `Bearer ${token}` }
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (Array.isArray(data)) {
                            setSystemUsers(data);
                        }
                    })
                    .catch(err => console.error("Error loading system users:", err));
                }
            }, []);

            const handleSubmit = (e) => {
                onSubmit(e, {
                    student_id: studentId || null,
                    program: program,
                    faculty: faculty,
                    intake: parseInt(String(intake).trim(), 10),
                    enrolled_since: enrolledSince,
                    user_id: !isEdit && linkExisting && userId ? parseInt(userId) : null,
                    user: (isEdit || !linkExisting) ? {
                        full_name: fullName,
                        email: email,
                        role_id: parseInt(roleId),
                        is_active: true
                    } : null
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Student ID</label>
                        <input type="text" disabled={isEdit} value={studentId} onChange={e => setStudentId(e.target.value)} placeholder="(Leave blank to auto-generate)" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-40 focus:outline-none focus:border-emerald-500" />
                    </div>
                    
                    {/* Link Existing User Toggle */}
                    {!isEdit && (
                        <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800 space-y-4 mt-2">
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-slate-300 font-bold uppercase tracking-wider">Link to Existing User Account?</span>
                                <label className="relative inline-flex items-center cursor-pointer">
                                    <input type="checkbox" checked={linkExisting} onChange={e => {
                                        setLinkExisting(e.target.checked);
                                        if (!e.target.checked) {
                                            setUserId("");
                                        }
                                    }} className="sr-only peer" />
                                    <div className="w-11 h-6 bg-slate-800 rounded-full peer peer-focus:ring-2 peer-focus:ring-emerald-500/50 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-600 peer-checked:after:bg-slate-100"></div>
                                </label>
                            </div>

                            {linkExisting && (
                                <div className="space-y-3">
                                    <div>
                                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Search Existing User (Similarity Search)</label>
                                        <AutocompleteSearch
                                            list={systemUsers}
                                            placeholder="Type name, email or user ID..."
                                            filterFn={(u, q) => (
                                                u.full_name?.toLowerCase().includes(q) ||
                                                u.email?.toLowerCase().includes(q) ||
                                                String(u.user_id).includes(q)
                                            )}
                                            renderItem={(u) => (
                                                <div>
                                                    <div className="font-bold text-slate-200">{u.full_name}</div>
                                                    <div className="text-xs text-slate-400">ID: {u.user_id} | Email: {u.email}</div>
                                                </div>
                                            )}
                                            onSelect={(u, setQ) => {
                                                setUserId(u.user_id);
                                                setQ(`${u.full_name} (${u.email})`);
                                            }}
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Linked User ID</label>
                                        <input 
                                            type="number" 
                                            value={userId}
                                            onChange={e => setUserId(e.target.value)}
                                            placeholder="(Leave blank for new user, or search/select existing user to link)"
                                            className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono"
                                        />
                                        <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                                            Leave blank for a new user. If a User ID is manually typed, the server will reject it if not found.
                                        </p>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* User Profile sub section */}
                    {(isEdit || !linkExisting) && (
                        <div className="border-t border-slate-800 pt-4 mt-2 space-y-4">
                            <span className="text-xs text-emerald-400 font-extrabold tracking-widest uppercase">Associated System User</span>
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Full Name</label>
                                <input type="text" required value={fullName} onChange={e => setFullName(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Email</label>
                                    <input type="email" required value={email} onChange={e => setEmail(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                                </div>
                            </div>
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
                                    {isEdit ? "Role" : "System Role"}
                                </label>
                                <select 
                                    required 
                                    value={roleId} 
                                    disabled={isEdit && !editRole}
                                    onChange={e => setRoleId(e.target.value)} 
                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select Role</option>
                                    {isEdit && !editRole ? (
                                        roles.filter(r => r.role_id === item?.user?.role_id).map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)
                                    ) : (
                                        roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)
                                    )}
                                </select>
                                {isEdit && (
                                    <div className="mt-1.5 flex items-center gap-1.5">
                                        <input 
                                            type="checkbox" 
                                            id="editStudentRoleCheck" 
                                            checked={editRole} 
                                            onChange={e => setEditRole(e.target.checked)} 
                                            className="w-3.5 h-3.5 text-emerald-600 bg-slate-950 border-slate-800 rounded focus:ring-emerald-500"
                                        />
                                        <label htmlFor="editStudentRoleCheck" className="text-[11px] text-slate-400 font-medium">Edit Role</label>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    <div className="border-t border-slate-800 pt-4 mt-2 grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Degree/Program</label>
                            <input type="text" required value={program} onChange={e => setProgram(e.target.value)} placeholder="e.g. Computer Science" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Faculty Department</label>
                            <input type="text" required value={faculty} onChange={e => setFaculty(e.target.value)} placeholder="e.g. FCI" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Intake Semester Code</label>
                            <input type="text" inputMode="numeric" maxLength="6" pattern="\d{6}" required value={intake} onChange={e => setIntake(e.target.value.replace(/\D/g, "").slice(0, 6))} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Enrolled Since</label>
                            <input type="date" required value={enrolledSince} onChange={e => setEnrolledSince(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>

                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Enroll Student</button>
                    </div>
                </form>
            );
        }

        // 3. Lecturer Profile Form
        function LecturerForm({ item, roles, nodes, onSubmit, onCancel }) {
            const [lecturerId, setLecturerId] = useState(item?.lecturer_id || "");
            const [department, setDepartment] = useState(item?.department || "");
            const [faculty, setFaculty] = useState(item?.faculty || "");
            const [position, setPosition] = useState(item?.position || "");
            const [isHoD, setIsHoD] = useState(item ? item.is_head_of_department : false);
            const [officeNodeId, setOfficeNodeId] = useState(item?.office_node_id || "");
            
            const [fullName, setFullName] = useState(item?.user?.full_name || "");
            const [email, setEmail] = useState(item?.user?.email || "");
            const [roleId, setRoleId] = useState(item?.user?.role_id || "");
            const [editRole, setEditRole] = useState(false);

            // Multi-role linking states
            const [linkExisting, setLinkExisting] = useState(false);
            const [userId, setUserId] = useState("");
            const [systemUsers, setSystemUsers] = useState([]);

            const isEdit = !!item;

            useEffect(() => {
                if (!isEdit) {
                    const token = localStorage.getItem("access_token");
                    fetch("/api/iam/users", {
                        headers: { "Authorization": `Bearer ${token}` }
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (Array.isArray(data)) {
                            setSystemUsers(data);
                        }
                    })
                    .catch(err => console.error("Error loading system users:", err));
                }
            }, []);

            const handleSubmit = (e) => {
                onSubmit(e, {
                    lecturer_id: lecturerId || null,
                    department: department,
                    faculty: faculty,
                    position: position,
                    is_head_of_department: isHoD,
                    office_node_id: officeNodeId ? parseInt(officeNodeId) : null,
                    user_id: !isEdit && linkExisting && userId ? parseInt(userId) : null,
                    user: (isEdit || !linkExisting) ? {
                        full_name: fullName,
                        email: email,
                        role_id: parseInt(roleId),
                        is_active: true
                    } : null
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Lecturer ID</label>
                        <input type="text" disabled={isEdit} value={lecturerId} onChange={e => setLecturerId(e.target.value)} placeholder="(Leave blank to auto-generate)" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-40 focus:outline-none focus:border-emerald-500" />
                    </div>

                    {/* Link Existing User Toggle */}
                    {!isEdit && (
                        <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800 space-y-4 mt-2">
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-slate-300 font-bold uppercase tracking-wider">Link to Existing User Account?</span>
                                <label className="relative inline-flex items-center cursor-pointer">
                                    <input type="checkbox" checked={linkExisting} onChange={e => {
                                        setLinkExisting(e.target.checked);
                                        if (!e.target.checked) {
                                            setUserId("");
                                        }
                                    }} className="sr-only peer" />
                                    <div className="w-11 h-6 bg-slate-800 rounded-full peer peer-focus:ring-2 peer-focus:ring-emerald-500/50 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-600 peer-checked:after:bg-slate-100"></div>
                                </label>
                            </div>

                            {linkExisting && (
                                <div className="space-y-3">
                                    <div>
                                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Search Existing User (Similarity Search)</label>
                                        <AutocompleteSearch
                                            list={systemUsers}
                                            placeholder="Type name, email or user ID..."
                                            filterFn={(u, q) => (
                                                u.full_name?.toLowerCase().includes(q) ||
                                                u.email?.toLowerCase().includes(q) ||
                                                String(u.user_id).includes(q)
                                            )}
                                            renderItem={(u) => (
                                                <div>
                                                    <div className="font-bold text-slate-200">{u.full_name}</div>
                                                    <div className="text-xs text-slate-400">ID: {u.user_id} | Email: {u.email}</div>
                                                </div>
                                            )}
                                            onSelect={(u, setQ) => {
                                                setUserId(u.user_id);
                                                setQ(`${u.full_name} (${u.email})`);
                                            }}
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Linked User ID</label>
                                        <input 
                                            type="number" 
                                            value={userId}
                                            onChange={e => setUserId(e.target.value)}
                                            placeholder="(Leave blank for new user, or search/select existing user to link)"
                                            className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono"
                                        />
                                        <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                                            Leave blank for a new user. If a User ID is manually typed, the server will reject it if not found.
                                        </p>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* User Profile sub section */}
                    {(isEdit || !linkExisting) && (
                        <div className="border-t border-slate-800 pt-4 mt-2 space-y-4">
                            <span className="text-xs text-emerald-400 font-extrabold tracking-widest uppercase">Associated System User</span>
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Full Name</label>
                                <input type="text" required value={fullName} onChange={e => setFullName(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Email</label>
                                    <input type="email" required value={email} onChange={e => setEmail(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                                </div>
                            </div>
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
                                    {isEdit ? "Role" : "System Role"}
                                </label>
                                <select 
                                    required 
                                    value={roleId} 
                                    disabled={isEdit && !editRole}
                                    onChange={e => setRoleId(e.target.value)} 
                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select Role</option>
                                    {isEdit && !editRole ? (
                                        roles.filter(r => r.role_id === item?.user?.role_id).map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)
                                    ) : (
                                        roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)
                                    )}
                                </select>
                                {isEdit && (
                                    <div className="mt-1.5 flex items-center gap-1.5">
                                        <input 
                                            type="checkbox" 
                                            id="editLecturerRoleCheck" 
                                            checked={editRole} 
                                            onChange={e => setEditRole(e.target.checked)} 
                                            className="w-3.5 h-3.5 text-emerald-600 bg-slate-950 border-slate-800 rounded focus:ring-emerald-500"
                                        />
                                        <label htmlFor="editLecturerRoleCheck" className="text-[11px] text-slate-400 font-medium">Edit Role</label>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    <div className="border-t border-slate-800 pt-4 mt-2 grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Department</label>
                            <input type="text" required value={department} onChange={e => setDepartment(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Faculty</label>
                            <input type="text" required value={faculty} onChange={e => setFaculty(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Position Title</label>
                            <input type="text" required value={position} onChange={e => setPosition(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Office Room Node</label>
                            <select value={officeNodeId} onChange={e => setOfficeNodeId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="">No Assigned Office</option>
                                {nodes.filter(n => n.node_type === 'OFFICE').map(n => <option key={n.node_id} value={n.node_id}>{n.room_label || `Node ${n.node_id}`}</option>)}
                            </select>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <input type="checkbox" checked={isHoD} onChange={e => setIsHoD(e.target.checked)} id="isHoD" className="w-4 h-4 text-emerald-600 bg-slate-950 border-slate-800 rounded focus:ring-emerald-500" />
                        <label htmlFor="isHoD" className="text-xs text-slate-400 font-bold uppercase tracking-wider">Is Head of Department</label>
                    </div>

                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Submit Setup</button>
                    </div>
                </form>
            );
        }

        // 4. Staff Profile Form
        function StaffForm({ item, roles, nodes, onSubmit, onCancel }) {
            const [staffId, setStaffId] = useState(item?.staff_id || "");
            const [department, setDepartment] = useState(item?.department || "");
            const [position, setPosition] = useState(item?.position || "");
            const [staffType, setStaffType] = useState(item?.staff_type || "ADMINISTRATIVE");
            const [officeNodeId, setOfficeNodeId] = useState(item?.office_node_id || "");

            const [fullName, setFullName] = useState(item?.user?.full_name || "");
            const [email, setEmail] = useState(item?.user?.email || "");
            const [roleId, setRoleId] = useState(item?.user?.role_id || "");
            const [editRole, setEditRole] = useState(false);

            // Multi-role linking states
            const [linkExisting, setLinkExisting] = useState(false);
            const [userId, setUserId] = useState("");
            const [systemUsers, setSystemUsers] = useState([]);

            const isEdit = !!item;

            useEffect(() => {
                if (!isEdit) {
                    const token = localStorage.getItem("access_token");
                    fetch("/api/iam/users", {
                        headers: { "Authorization": `Bearer ${token}` }
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (Array.isArray(data)) {
                            setSystemUsers(data);
                        }
                    })
                    .catch(err => console.error("Error loading system users:", err));
                }
            }, []);

            const handleSubmit = (e) => {
                onSubmit(e, {
                    staff_id: staffId || null,
                    department: department,
                    position: position,
                    staff_type: staffType,
                    office_node_id: officeNodeId ? parseInt(officeNodeId) : null,
                    user_id: !isEdit && linkExisting && userId ? parseInt(userId) : null,
                    user: (isEdit || !linkExisting) ? {
                        full_name: fullName,
                        email: email,
                        role_id: parseInt(roleId),
                        is_active: true
                    } : null
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Staff Profile ID</label>
                        <input type="text" disabled={isEdit} value={staffId} onChange={e => setStaffId(e.target.value)} placeholder="(Leave blank to auto-generate)" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-40 focus:outline-none focus:border-emerald-500" />
                    </div>

                    {/* Link Existing User Toggle */}
                    {!isEdit && (
                        <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800 space-y-4 mt-2">
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-slate-300 font-bold uppercase tracking-wider">Link to Existing User Account?</span>
                                <label className="relative inline-flex items-center cursor-pointer">
                                    <input type="checkbox" checked={linkExisting} onChange={e => {
                                        setLinkExisting(e.target.checked);
                                        if (!e.target.checked) {
                                            setUserId("");
                                        }
                                    }} className="sr-only peer" />
                                    <div className="w-11 h-6 bg-slate-800 rounded-full peer peer-focus:ring-2 peer-focus:ring-emerald-500/50 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-600 peer-checked:after:bg-slate-100"></div>
                                </label>
                            </div>

                            {linkExisting && (
                                <div className="space-y-3">
                                    <div>
                                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Search Existing User (Similarity Search)</label>
                                        <AutocompleteSearch
                                            list={systemUsers}
                                            placeholder="Type name, email or user ID..."
                                            filterFn={(u, q) => (
                                                u.full_name?.toLowerCase().includes(q) ||
                                                u.email?.toLowerCase().includes(q) ||
                                                String(u.user_id).includes(q)
                                            )}
                                            renderItem={(u) => (
                                                <div>
                                                    <div className="font-bold text-slate-200">{u.full_name}</div>
                                                    <div className="text-xs text-slate-400">ID: {u.user_id} | Email: {u.email}</div>
                                                </div>
                                            )}
                                            onSelect={(u, setQ) => {
                                                setUserId(u.user_id);
                                                setQ(`${u.full_name} (${u.email})`);
                                            }}
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Linked User ID</label>
                                        <input 
                                            type="number" 
                                            value={userId}
                                            onChange={e => setUserId(e.target.value)}
                                            placeholder="(Leave blank for new user, or search/select existing user to link)"
                                            className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono"
                                        />
                                        <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                                            Leave blank for a new user. If a User ID is manually typed, the server will reject it if not found.
                                        </p>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* User Profile sub section */}
                    {(isEdit || !linkExisting) && (
                        <div className="border-t border-slate-800 pt-4 mt-2 space-y-4">
                            <span className="text-xs text-emerald-400 font-extrabold tracking-widest uppercase">Associated System User</span>
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Full Name</label>
                                <input type="text" required value={fullName} onChange={e => setFullName(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Email</label>
                                    <input type="email" required value={email} onChange={e => setEmail(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                                </div>
                            </div>
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
                                    {isEdit ? "Role" : "System Role"}
                                </label>
                                <select 
                                    required 
                                    value={roleId} 
                                    disabled={isEdit && !editRole}
                                    onChange={e => setRoleId(e.target.value)} 
                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select Role</option>
                                    {isEdit && !editRole ? (
                                        roles.filter(r => r.role_id === item?.user?.role_id).map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)
                                    ) : (
                                        roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)
                                    )}
                                </select>
                                {isEdit && (
                                    <div className="mt-1.5 flex items-center gap-1.5">
                                        <input 
                                            type="checkbox" 
                                            id="editStaffRoleCheck" 
                                            checked={editRole} 
                                            onChange={e => setEditRole(e.target.checked)} 
                                            className="w-3.5 h-3.5 text-emerald-600 bg-slate-950 border-slate-800 rounded focus:ring-emerald-500"
                                        />
                                        <label htmlFor="editStaffRoleCheck" className="text-[11px] text-slate-400 font-medium">Edit Role</label>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    <div className="border-t border-slate-800 pt-4 mt-2 grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Department</label>
                            <input type="text" required value={department} onChange={e => setDepartment(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Position</label>
                            <input type="text" required value={position} onChange={e => setPosition(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Staff Category Type</label>
                            <select value={staffType} onChange={e => setStaffType(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="ADMINISTRATIVE">ADMINISTRATIVE</option>
                                <option value="TECHNICAL">TECHNICAL</option>
                                <option value="SECURITY">SECURITY</option>
                                <option value="FACILITIES">FACILITIES</option>
                                <option value="OTHER">OTHER</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Office Room Node</label>
                            <select value={officeNodeId} onChange={e => setOfficeNodeId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="">No Assigned Office</option>
                                {nodes.filter(n => n.node_type === 'OFFICE').map(n => <option key={n.node_id} value={n.node_id}>{n.room_label || `Node ${n.node_id}`}</option>)}
                            </select>
                        </div>
                    </div>

                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Submit Setup</button>
                    </div>
                </form>
            );
        }

        // 5. Visitor Profile Form
        function VisitorForm({ item, roles, onSubmit, onCancel, currentUserId }) {
            const [visitorId, setVisitorId] = useState(item?.visitor_id || "");
            const [idNumber, setIdNumber] = useState(item?.id_number || "");
            const [organization, setOrganization] = useState(item?.organization || "");
            const [visitPurpose, setVisitPurpose] = useState(item?.visit_purpose || "");
            const [accessExpiry, setAccessExpiry] = useState(item?.access_expiry || new Date(Date.now() + 24*3600*1000).toISOString().slice(0, 16));

            const [fullName, setFullName] = useState(item?.user?.full_name || "");
            const [email, setEmail] = useState(item?.user?.email || "");
            const [roleId, setRoleId] = useState(item?.user?.role_id || "");
            const [editRole, setEditRole] = useState(false);

            // Multi-role linking states
            const [linkExisting, setLinkExisting] = useState(false);
            const [userId, setUserId] = useState("");
            const [systemUsers, setSystemUsers] = useState([]);

            const isEdit = !!item;

            useEffect(() => {
                if (!isEdit) {
                    const token = localStorage.getItem("access_token");
                    fetch("/api/iam/users", {
                        headers: { "Authorization": `Bearer ${token}` }
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (Array.isArray(data)) {
                            setSystemUsers(data);
                        }
                    })
                    .catch(err => console.error("Error loading system users:", err));
                }
            }, []);

            const handleSubmit = (e) => {
                onSubmit(e, {
                    visitor_id: visitorId || null,
                    id_number: idNumber,
                    organization: organization,
                    visit_purpose: visitPurpose,
                    access_expiry: accessExpiry,
                    registered_by: currentUserId,
                    user_id: !isEdit && linkExisting && userId ? parseInt(userId) : null,
                    user: (isEdit || !linkExisting) ? {
                        full_name: fullName,
                        email: email,
                        role_id: parseInt(roleId),
                        is_active: true
                    } : null
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Visitor Profile ID</label>
                            <input type="text" disabled={isEdit} value={visitorId} onChange={e => setVisitorId(e.target.value)} placeholder="(Leave blank to auto-generate)" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-40 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Passport/National ID</label>
                            <input type="text" required disabled={isEdit} value={idNumber} onChange={e => setIdNumber(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-40 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>

                    {/* Link Existing User Toggle */}
                    {!isEdit && (
                        <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800 space-y-4 mt-2">
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-slate-300 font-bold uppercase tracking-wider">Link to Existing User Account?</span>
                                <label className="relative inline-flex items-center cursor-pointer">
                                    <input type="checkbox" checked={linkExisting} onChange={e => {
                                        setLinkExisting(e.target.checked);
                                        if (!e.target.checked) {
                                            setUserId("");
                                        }
                                    }} className="sr-only peer" />
                                    <div className="w-11 h-6 bg-slate-800 rounded-full peer peer-focus:ring-2 peer-focus:ring-emerald-500/50 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-600 peer-checked:after:bg-slate-100"></div>
                                </label>
                            </div>

                            {linkExisting && (
                                <div className="space-y-3">
                                    <div>
                                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Search Existing User (Similarity Search)</label>
                                        <AutocompleteSearch
                                            list={systemUsers}
                                            placeholder="Type name, email or user ID..."
                                            filterFn={(u, q) => (
                                                u.full_name?.toLowerCase().includes(q) ||
                                                u.email?.toLowerCase().includes(q) ||
                                                String(u.user_id).includes(q)
                                            )}
                                            renderItem={(u) => (
                                                <div>
                                                    <div className="font-bold text-slate-200">{u.full_name}</div>
                                                    <div className="text-xs text-slate-400">ID: {u.user_id} | Email: {u.email}</div>
                                                </div>
                                            )}
                                            onSelect={(u, setQ) => {
                                                setUserId(u.user_id);
                                                setQ(`${u.full_name} (${u.email})`);
                                            }}
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Linked User ID</label>
                                        <input 
                                            type="number" 
                                            value={userId}
                                            onChange={e => setUserId(e.target.value)}
                                            placeholder="(Leave blank for new user, or search/select existing user to link)"
                                            className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono"
                                        />
                                        <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                                            Leave blank for a new user. If a User ID is manually typed, the server will reject it if not found.
                                        </p>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* User Profile sub section */}
                    {(isEdit || !linkExisting) && (
                        <div className="border-t border-slate-800 pt-4 mt-2 space-y-4">
                            <span className="text-xs text-emerald-400 font-extrabold tracking-widest uppercase">Associated System User</span>
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Full Name</label>
                                <input type="text" required value={fullName} onChange={e => setFullName(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Email</label>
                                    <input type="email" required value={email} onChange={e => setEmail(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                                </div>
                            </div>
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
                                    {isEdit ? "Role" : "System Role"}
                                </label>
                                <select 
                                    required 
                                    value={roleId} 
                                    disabled={isEdit && !editRole}
                                    onChange={e => setRoleId(e.target.value)} 
                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
                                >
                                    <option value="">Select Role</option>
                                    {isEdit && !editRole ? (
                                        roles.filter(r => r.role_id === item?.user?.role_id).map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)
                                    ) : (
                                        roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)
                                    )}
                                </select>
                                {isEdit && (
                                    <div className="mt-1.5 flex items-center gap-1.5">
                                        <input 
                                            type="checkbox" 
                                            id="editVisitorRoleCheck" 
                                            checked={editRole} 
                                            onChange={e => setEditRole(e.target.checked)} 
                                            className="w-3.5 h-3.5 text-emerald-600 bg-slate-950 border-slate-800 rounded focus:ring-emerald-500"
                                        />
                                        <label htmlFor="editVisitorRoleCheck" className="text-[11px] text-slate-400 font-medium">Edit Role</label>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    <div className="border-t border-slate-800 pt-4 mt-2 grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Organization/Affiliation</label>
                            <input type="text" value={organization} onChange={e => setOrganization(e.target.value)} placeholder="e.g. Guest Company" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Access Expiry Date</label>
                            <input type="datetime-local" required value={accessExpiry} onChange={e => setAccessExpiry(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono" />
                        </div>
                    </div>

                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Purpose of Visit</label>
                        <textarea value={visitPurpose} onChange={e => setVisitPurpose(e.target.value)} placeholder="State the reason for visiting the smart campus area..." className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 h-20" />
                    </div>

                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Grant Access Pass</button>
                    </div>
                </form>
            );
        }

        // 6. Admin User Form
        function AdminForm({ item, roles, nodes, onSubmit, onCancel }) {
            const [adminId, setAdminId] = useState(item?.admin_id || "");
            const [adminType, setAdminType] = useState(item?.admin_type || "SYSTEM_ADMIN");
            const [password, setPassword] = useState("");

            // Staff promoting states
            const [userId, setUserId] = useState(item?.user_id || "");
            const [staffList, setStaffList] = useState([]);

            const isEdit = !!item;

            useEffect(() => {
                if (!isEdit) {
                    const token = localStorage.getItem("access_token");
                    fetch("/api/iam/staff", {
                        headers: { "Authorization": `Bearer ${token}` }
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (Array.isArray(data)) {
                            setStaffList(data);
                        }
                    })
                    .catch(err => console.error("Error loading staff members:", err));
                }
            }, []);

            const handleSubmit = (e) => {
                e.preventDefault();
                onSubmit(e, {
                    admin_id: adminId || null,
                    admin_type: adminType,
                    password: password || undefined,
                    user_id: !isEdit && userId ? parseInt(userId) : null
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    {isEdit && item?.user && (
                        <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800 space-y-2">
                            <span className="text-xs text-slate-400 font-bold uppercase tracking-wider block">Linked Staff Member</span>
                            <div className="text-sm font-bold text-slate-200">{item.user.full_name}</div>
                            <div className="text-xs text-slate-400">email: {item.user.email} | Email: {item.user.email}</div>
                        </div>
                    )}

                    {!isEdit && (
                        <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800 space-y-4">
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Search Existing Staff (Name, Staff ID)</label>
                                <AutocompleteSearch
                                    list={staffList}
                                    placeholder="Search by Name, Staff ID or User ID..."
                                    filterFn={(s, q) => (
                                        s.user?.full_name?.toLowerCase().includes(q) ||
                                        s.staff_id?.toLowerCase().includes(q) ||
                                        String(s.user_id).includes(q)
                                    )}
                                    renderItem={(s) => (
                                        <div>
                                            <div className="font-bold text-slate-200">{s.user?.full_name}</div>
                                            <div className="text-xs text-slate-400">Staff ID: {s.staff_id} | User ID: {s.user_id} | Dept: {s.department}</div>
                                        </div>
                                    )}
                                    onSelect={(s, setQ) => {
                                        setUserId(s.user_id);
                                        setQ(`${s.user?.full_name} (${s.staff_id})`);
                                    }}
                                />
                            </div>
                            <div>
                                <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Selected Staff User ID</label>
                                <input 
                                    type="number" 
                                    required
                                    value={userId}
                                    onChange={e => setUserId(e.target.value)}
                                    placeholder="Insert staff user ID..."
                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono"
                                />
                            </div>
                        </div>
                    )}

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Admin Authority Tier</label>
                            <select value={adminType} onChange={e => setAdminType(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="SUPER_ADMIN">SUPER ADMIN</option>
                                <option value="SYSTEM_ADMIN">SYSTEM ADMIN</option>
                                <option value="CONTENT_ADMIN">CONTENT ADMIN</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Portal Access Password</label>
                            <input 
                                type="password" 
                                required={!isEdit}
                                value={password} 
                                onChange={e => setPassword(e.target.value)} 
                                placeholder={isEdit ? "(Leave blank to keep unchanged)" : "••••••••"} 
                                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" 
                            />
                        </div>
                    </div>

                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Grant Admin Rights</button>
                    </div>
                </form>
            );
        }

        // 7. RAG Document Meta Form
        function DocumentForm({ item, onSubmit, onCancel }) {
            const [title, setTitle] = useState(item?.title || "");
            const [uploadedBy, setUploadedBy] = useState(item?.uploaded_by || 1); // default system admin user id
            const [accessLevel, setAccessLevel] = useState(item?.access_level || "PUBLIC");
            const [file, setFile] = useState(null);

            const handleSubmit = (e) => {
                e.preventDefault();
                const formData = new FormData();
                formData.append("title", title);
                formData.append("uploaded_by", uploadedBy);
                formData.append("access_level", accessLevel);
                formData.append("is_active", true);
                if (file) {
                    formData.append("file", file);
                }
                onSubmit(e, formData);
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Document Title</label>
                        <input type="text" required value={title} onChange={e => setTitle(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Document File</label>
                            <input type="file" required={!item?.document_id} onChange={e => setFile(e.target.files[0])} accept=".txt,.md,.csv" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 file:mr-4 file:py-1 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-emerald-900/30 file:text-emerald-400 hover:file:bg-emerald-900/50" />
                            {item?.file_path && !file && <p className="text-xs text-slate-500 mt-1">Current file: {item.filename}</p>}
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Access Level Clearance</label>
                            <select value={accessLevel} onChange={e => setAccessLevel(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="PUBLIC">PUBLIC</option>
                                <option value="STUDENT">STUDENT</option>
                                <option value="LECTURER">LECTURER</option>
                                <option value="ADMIN">ADMIN</option>
                            </select>
                        </div>
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Submit Document</button>
                    </div>
                </form>
            );
        }

        // 8. Device Configuration Form
        function DeviceForm({ item, nodes, onSubmit, onCancel }) {
            const [deviceId, setDeviceId] = useState(item?.device_id || "");
            const [deviceName, setDeviceName] = useState(item?.device_name || "");
            const [nodeId, setNodeId] = useState(item?.node_id || "");
            const [deviceType, setDeviceType] = useState(item?.device_type || "KIOSK");
            const [ipAddress, setIpAddress] = useState(item?.ip_address || "");

            const handleSubmit = (e) => {
                onSubmit(e, {
                    device_id: deviceId,
                    device_name: deviceName,
                    node_id: parseInt(nodeId),
                    device_type: deviceType,
                    ip_address: ipAddress || null,
                    is_active: true
                });
            };

            const isEdit = !!item;

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Device Hardware ID</label>
                            <input type="text" required disabled={isEdit} value={deviceId} onChange={e => setDeviceId(e.target.value)} placeholder="e.g. EDGE-KIOSK-01" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-40 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Device Label Name</label>
                            <input type="text" required value={deviceName} onChange={e => setDeviceName(e.target.value)} placeholder="e.g. Main Lobby Stand" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Device Node Location</label>
                            <select required value={nodeId} onChange={e => setNodeId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="">Select Node</option>
                                {nodes.map(n => <option key={n.node_id} value={n.node_id}>{n.room_label || `Node ${n.node_id}`}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Hardware Type</label>
                            <select value={deviceType} onChange={e => setDeviceType(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="KIOSK">KIOSK</option>
                                <option value="ENTRY_GATE">ENTRY GATE</option>
                                <option value="CLASSROOM">CLASSROOM</option>
                                <option value="OFFICE">OFFICE</option>
                                <option value="OTHER">OTHER</option>
                            </select>
                        </div>
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Network Address</label>
                        <input type="text" value={ipAddress} onChange={e => setIpAddress(e.target.value)} placeholder="e.g. 192.168.1.100:8001" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono" />
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Submit Setup</button>
                    </div>
                </form>
            );
        }

        // 9. Node RBAC Form
        function NodeRBACForm({ nodes, roles, onSubmit, onCancel }) {
            const [nodeId, setNodeId] = useState("");
            const [roleId, setRoleId] = useState("");

            const handleSubmit = (e) => {
                onSubmit(e, {
                    node_id: parseInt(nodeId),
                    role_id: parseInt(roleId)
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Select Campus Node Location</label>
                        <select required value={nodeId} onChange={e => setNodeId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                            <option value="">Select Node</option>
                            {nodes.map(n => <option key={n.node_id} value={n.node_id}>{n.room_label || `Node ${n.node_id}`} ({n.node_type})</option>)}
                        </select>
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Granted Role clearance level</label>
                        <select required value={roleId} onChange={e => setRoleId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                            <option value="">Select Role</option>
                            {roles.map(r => <option key={r.role_id} value={r.role_id}>{r.role_name}</option>)}
                        </select>
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Grant Clearance</button>
                    </div>
                </form>
            );
        }

        // 10. Course Registration Form
        function CourseForm({ item, programmes = [], faculties = [], onSubmit, onCancel }) {
            const isEdit = !!item;
            const [courseCode, setCourseCode] = useState(item?.course_code || "");
            const [courseName, setCourseName] = useState(item?.course_name || "");
            const [credits, setCredits] = useState(item?.credit_hours || 3);
            const [programmeId, setProgrammeId] = useState(item?.programme_id || item?.department || "");
            const [facultyId, setFacultyId] = useState(item?.faculty_id || item?.faculty || "");
            const [level, setLevel] = useState(item?.course_level || "UNDERGRADUATE");

            const findProgramme = (value) => programmes.find(p => String(p.programme_id) === String(value) || p.programme_name === value);
            const findFaculty = (value) => faculties.find(f => String(f.faculty_id) === String(value) || f.faculty_name === value);

            const handleSubmit = (e) => {
                const selectedProgramme = findProgramme(programmeId);
                const selectedFaculty = findFaculty(facultyId);
                onSubmit(e, {
                    course_code: courseCode,
                    course_name: courseName,
                    credit_hours: parseInt(credits),
                    programme_id: selectedProgramme ? selectedProgramme.programme_id : programmeId,
                    faculty_id: selectedFaculty ? selectedFaculty.faculty_id : facultyId,
                    course_level: level,
                    is_active: true
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Course Code</label>
                            <input type="text" required disabled={isEdit} value={courseCode} onChange={e => setCourseCode(e.target.value)} placeholder="e.g. TCS3111" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-55 disabled:cursor-not-allowed focus:outline-none focus:border-emerald-500 uppercase" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Credit Hours</label>
                            <input type="number" required value={credits} onChange={e => setCredits(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Course Subject Name</label>
                        <input type="text" required value={courseName} onChange={e => setCourseName(e.target.value)} placeholder="e.g. Distributed Computing Systems" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Programme</label>
                            <SearchableDropdown
                                list={programmes}
                                value={programmeId}
                                onChange={(val, item) => {
                                    setProgrammeId(val);
                                    if (item?.faculty_id) setFacultyId(item.faculty_id);
                                }}
                                placeholder="Search programme"
                                filterFn={(p, q) => p.programme_name.toLowerCase().includes(q) || p.programme_id.toLowerCase().includes(q)}
                                displayFn={p => p.programme_name}
                                valueFn={p => p.programme_id}
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Faculty</label>
                            <SearchableDropdown
                                list={faculties}
                                value={facultyId}
                                onChange={setFacultyId}
                                placeholder="Search faculty"
                                filterFn={(f, q) => f.faculty_name.toLowerCase().includes(q) || f.faculty_id.toLowerCase().includes(q)}
                                displayFn={f => f.faculty_name}
                                valueFn={f => f.faculty_id}
                            />
                        </div>
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Course Education Level</label>
                        <select value={level} onChange={e => setLevel(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                            <option value="UNDERGRADUATE">UNDERGRADUATE</option>
                            <option value="POSTGRADUATE">POSTGRADUATE</option>
                        </select>
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">
                            {isEdit ? "Update Subject" : "Submit Subject"}
                        </button>
                    </div>
                </form>
            );
        }

        // 11. Student Course Enrollment Form
        function EnrollmentForm({ item, students = [], courses = [], onSubmit, onCancel }) {
            const isEdit = !!item;
            const [studentId, setStudentId] = useState(item?.student_id || "");
            const [courseId, setCourseId] = useState(item?.course_id || "");
            const [semester, setSemester] = useState(item?.semester || 202607);
            const [academicYear, setAcademicYear] = useState(item?.academic_year || "2025/2026");

            const [studentOptions, setStudentOptions] = useState(students);
            const [courseOptions, setCourseOptions] = useState(courses);

            useEffect(() => {
                const token = localStorage.getItem("access_token");
                const headers = { "Authorization": `Bearer ${token}` };
                
                if (!students || students.length === 0) {
                    fetch("/api/iam/students", { headers })
                        .then(res => res.json())
                        .then(data => { if (Array.isArray(data)) setStudentOptions(data); })
                        .catch(() => {});
                }
                if (!courses || courses.length === 0) {
                    fetch("/api/academics/courses", { headers })
                        .then(res => res.json())
                        .then(data => { if (Array.isArray(data)) setCourseOptions(data); })
                        .catch(() => {});
                }
            }, []);

            const handleSubmit = (e) => {
                e.preventDefault();
                onSubmit(e, {
                    student_id: studentId,
                    course_id: parseInt(courseId),
                    semester: parseInt(semester),
                    academic_year: academicYear,
                    status: "ENROLLED"
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Student Profile (Search by Name or Student ID)</label>
                        <SearchableDropdown
                            list={studentOptions}
                            value={studentId}
                            onChange={(val, s) => setStudentId(val)}
                            placeholder="Search student by name, email, or student ID..."
                            filterFn={(s, q) => {
                                const name = (s.user?.full_name || s.full_name || s.user?.given_name || '').toLowerCase();
                                const email = (s.user?.email || s.email || '').toLowerCase();
                                const sid = String(s.student_id || '').toLowerCase();
                                return name.includes(q) || email.includes(q) || sid.includes(q);
                            }}
                            displayFn={s => {
                                const name = s.user?.full_name || s.full_name || (s.user?.given_name ? `${s.user.given_name} ${s.user.family_name || ''}` : '');
                                return `${s.student_id}${name ? ' — ' + name : ''}`;
                            }}
                            valueFn={s => s.student_id}
                        />
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Course (Search by Course Code or Course Name)</label>
                        <SearchableDropdown
                            list={courseOptions}
                            value={courseId}
                            onChange={(val, c) => setCourseId(val)}
                            placeholder="Search course by code, name, or ID..."
                            filterFn={(c, q) => {
                                const code = (c.course_code || '').toLowerCase();
                                const name = (c.course_name || '').toLowerCase();
                                const id = String(c.course_id || '').toLowerCase();
                                return code.includes(q) || name.includes(q) || id.includes(q);
                            }}
                            displayFn={c => `[${c.course_code}] ${c.course_name}`}
                            valueFn={c => c.course_id}
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Semester Code</label>
                            <input type="number" required value={semester} onChange={e => setSemester(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Academic Year</label>
                            <input type="text" required value={academicYear} onChange={e => setAcademicYear(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">
                            {isEdit ? "Update Enrollment" : "Register Enrollment"}
                        </button>
                    </div>
                </form>
            );
        }

        // 12. Timetable scheduling form (Includes safety check for double booking)
        function TimetableForm({ item, nodes, onSubmit, onCancel }) {
            const isEdit = !!item;
            const [courseId, setCourseId] = useState(item?.course_id || "");
            const [lecturerId, setLecturerId] = useState(item?.lecturer_id || "");
            const [dayOfWeek, setDayOfWeek] = useState(item?.day_of_week || "MONDAY");
            const [startTime, setStartTime] = useState(item?.start_time ? item.start_time.slice(0, 5) : "09:00");
            const [endTime, setEndTime] = useState(item?.end_time ? item.end_time.slice(0, 5) : "11:00");
            const [nodeId, setNodeId] = useState(item?.node_id || "");
            const [semester, setSemester] = useState(item?.semester || 202607);
            const [academicYear, setAcademicYear] = useState(item?.academic_year || "2025/2026");

            const handleSubmit = (e) => {
                onSubmit(e, {
                    course_id: parseInt(courseId),
                    lecturer_id: lecturerId,
                    day_of_week: dayOfWeek,
                    start_time: startTime.slice(0, 5) + ":00",
                    end_time: endTime.slice(0, 5) + ":00",
                    node_id: parseInt(nodeId),
                    semester: parseInt(semester),
                    academic_year: academicYear
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Course Index ID</label>
                            <input type="number" required value={courseId} onChange={e => setCourseId(e.target.value)} placeholder="e.g. 1" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Lecturer Profile ID</label>
                            <input type="text" required value={lecturerId} onChange={e => setLecturerId(e.target.value)} placeholder="e.g. LEC-20030" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>
                    
                    <div className="grid grid-cols-3 gap-3">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Day of Week</label>
                            <select value={dayOfWeek} onChange={e => setDayOfWeek(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="MONDAY">MONDAY</option>
                                <option value="TUESDAY">TUESDAY</option>
                                <option value="WEDNESDAY">WEDNESDAY</option>
                                <option value="THURSDAY">THURSDAY</option>
                                <option value="FRIDAY">FRIDAY</option>
                                <option value="SATURDAY">SATURDAY</option>
                                <option value="SUNDAY">SUNDAY</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Start Time</label>
                            <input type="time" required value={startTime} onChange={e => setStartTime(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">End Time</label>
                            <input type="time" required value={endTime} onChange={e => setEndTime(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono" />
                        </div>
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Classroom Node</label>
                            <select required value={nodeId} onChange={e => setNodeId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="">Select Room</option>
                                {nodes.filter(n => n.node_type === 'CLASSROOM').map(n => <option key={n.node_id} value={n.node_id}>{n.room_label || `Node ${n.node_id}`}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Semester Code</label>
                            <input type="number" required value={semester} onChange={e => setSemester(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Academic Year</label>
                            <input type="text" required value={academicYear} onChange={e => setAcademicYear(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>

                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">
                            {isEdit ? "Update Class Slot" : "Schedule Class Slot"}
                        </button>
                    </div>
                </form>
            );
        }

        // 13. Appointment Scheduler Form (Includes validation checks)
        function AppointmentForm({ item, nodes, onSubmit, onCancel }) {
            const [guestId, setGuestId] = useState(item?.guest_user_id || "");
            const [hostId, setHostId] = useState(item?.host_user_id || "");
            const [scheduledAt, setScheduledAt] = useState(item?.scheduled_at || new Date().toISOString().slice(0, 16));
            const [duration, setDuration] = useState(item?.duration_minutes || 30);
            const [nodeId, setNodeId] = useState(item?.node_id || "");
            const [purpose, setPurpose] = useState(item?.purpose || "");
            const [status, setStatus] = useState(item?.status || "PENDING");

            const handleSubmit = (e) => {
                onSubmit(e, {
                    guest_user_id: parseInt(guestId),
                    host_user_id: parseInt(hostId),
                    scheduled_at: scheduledAt,
                    duration_minutes: parseInt(duration),
                    node_id: nodeId ? parseInt(nodeId) : null,
                    purpose,
                    status
                });
            };

            const isEdit = !!item;

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    {isEdit && (
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Appointment Status</label>
                            <select value={status} onChange={e => setStatus(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="PENDING">PENDING</option>
                                <option value="CONFIRMED">CONFIRMED</option>
                                <option value="CANCELLED">CANCELLED</option>
                                <option value="COMPLETED">COMPLETED</option>
                            </select>
                        </div>
                    )}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Guest User Index ID</label>
                            <input type="number" required disabled={isEdit} value={guestId} onChange={e => setGuestId(e.target.value)} placeholder="e.g. 2 (verified Student)" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-40 focus:outline-none focus:border-emerald-500" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Host User Index ID</label>
                            <input type="number" required disabled={isEdit} value={hostId} onChange={e => setHostId(e.target.value)} placeholder="e.g. 3 (verified Lecturer)" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-40 focus:outline-none focus:border-emerald-500" />
                        </div>
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                        <div className="col-span-2">
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Scheduled Date & Time</label>
                            <input type="datetime-local" required value={scheduledAt} onChange={e => setScheduledAt(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Duration (mins)</label>
                            <input type="number" required value={duration} onChange={e => setDuration(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 font-mono" />
                        </div>
                    </div>
                    <div className="grid grid-cols-1 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Meeting Node Location</label>
                            <select value={nodeId} onChange={e => setNodeId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="">Select Node</option>
                                {nodes.map(n => <option key={n.node_id} value={n.node_id}>{n.room_label || `Node ${n.node_id}`} ({n.node_type})</option>)}
                            </select>
                        </div>
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Appointment Purpose</label>
                        <textarea value={purpose} onChange={e => setPurpose(e.target.value)} placeholder="State meeting notes, agenda, discussion points..." className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 h-20" />
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">Book Appointment Slot</button>
                    </div>
                </form>
            );
        }

        // 14. Role Creation Form
        function RoleForm({ item, onSubmit, onCancel }) {
            const isEdit = !!item;
            const [roleName, setRoleName] = useState(item?.role_name || "");
            const [description, setDescription] = useState(item?.description || "");

            const handleSubmit = (e) => {
                onSubmit(e, {
                    role_name: roleName.toUpperCase(),
                    description: description
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Role Name</label>
                        <input type="text" required disabled={isEdit} value={roleName} onChange={e => setRoleName(e.target.value)} placeholder="e.g. GUEST_STUDENT" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-55 disabled:cursor-not-allowed focus:outline-none focus:border-emerald-500 uppercase font-mono" />
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Description</label>
                        <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder="Explain security clearance privileges..." className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 h-24" />
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">
                            {isEdit ? "Update Role" : "Create Role"}
                        </button>
                    </div>
                </form>
            );
        }

        // 15. Faculty Form
        function FacultyForm({ item, staff = [], onSubmit, onCancel }) {
            const isEdit = !!item;
            const [facultyId, setFacultyId] = useState(item?.faculty_id || "");
            const [facultyName, setFacultyName] = useState(item?.faculty_name || "");
            const [deanId, setDeanId] = useState(item?.dean_id || "");

            const handleSubmit = (e) => {
                onSubmit(e, {
                    faculty_id: facultyId,
                    faculty_name: facultyName,
                    dean_id: deanId
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Faculty ID</label>
                        <input type="text" required disabled={isEdit} value={facultyId} onChange={e => setFacultyId(e.target.value)} placeholder="e.g. FCI" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-55 disabled:cursor-not-allowed focus:outline-none focus:border-emerald-500 uppercase font-mono" />
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Faculty Name</label>
                        <input type="text" required value={facultyName} onChange={e => setFacultyName(e.target.value)} placeholder="e.g. Faculty of Computing and Informatics" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Dean</label>
                        <select required value={deanId} onChange={e => setDeanId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                            <option value="">Select Dean</option>
                            {staff.map(s => (
                                <option key={s.staff_id} value={s.staff_id}>
                                    {s.user?.full_name ? `${s.user.full_name} (${s.staff_id})` : s.staff_id}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">
                            {isEdit ? "Update Faculty" : "Create Faculty"}
                        </button>
                    </div>
                </form>
            );
        }

        // 16. Department Form
        function DepartmentForm({ item, staff = [], onSubmit, onCancel }) {
            const isEdit = !!item;
            const [departmentId, setDepartmentId] = useState(item?.department_id || "");
            const [departmentName, setDepartmentName] = useState(item?.department_name || "");
            const [managerId, setManagerId] = useState(item?.manager_id || "");

            const handleSubmit = (e) => {
                onSubmit(e, {
                    department_id: departmentId,
                    department_name: departmentName,
                    manager_id: managerId
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Department ID</label>
                        <input type="text" required disabled={isEdit} value={departmentId} onChange={e => setDepartmentId(e.target.value)} placeholder="e.g. DEPT-CS" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-55 disabled:cursor-not-allowed focus:outline-none focus:border-emerald-500 uppercase font-mono" />
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Department Name</label>
                        <input type="text" required value={departmentName} onChange={e => setDepartmentName(e.target.value)} placeholder="e.g. Department of Computer Science" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Manager</label>
                        <select required value={managerId} onChange={e => setManagerId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                            <option value="">Select Manager</option>
                            {staff.map(s => (
                                <option key={s.staff_id} value={s.staff_id}>
                                    {s.user?.full_name ? `${s.user.full_name} (${s.staff_id})` : s.staff_id}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">
                            {isEdit ? "Update Department" : "Create Department"}
                        </button>
                    </div>
                </form>
            );
        }

        // 17. Programme Form
        function ProgrammeForm({ item, staff = [], faculties = [], onSubmit, onCancel }) {
            const isEdit = !!item;
            const [programmeId, setProgrammeId] = useState(item?.programme_id || "");
            const [programmeName, setProgrammeName] = useState(item?.programme_name || "");
            const [facultyId, setFacultyId] = useState(item?.faculty_id || "");
            const [hopId, setHopId] = useState(item?.hop_id || "");

            const handleSubmit = (e) => {
                onSubmit(e, {
                    programme_id: programmeId,
                    programme_name: programmeName,
                    faculty_id: facultyId,
                    hop_id: hopId
                });
            };

            return (
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Programme ID</label>
                        <input type="text" required disabled={isEdit} value={programmeId} onChange={e => setProgrammeId(e.target.value)} placeholder="e.g. BCS" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 disabled:opacity-55 disabled:cursor-not-allowed focus:outline-none focus:border-emerald-500 uppercase font-mono" />
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Programme Name</label>
                        <input type="text" required value={programmeName} onChange={e => setProgrammeName(e.target.value)} placeholder="e.g. Bachelor of Computer Science" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500" />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Faculty</label>
                            <select required value={facultyId} onChange={e => setFacultyId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="">Select Faculty</option>
                                {faculties.map(f => (
                                    <option key={f.faculty_id} value={f.faculty_id}>
                                        {f.faculty_name} ({f.faculty_id})
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">Head of Programme (HOP)</label>
                            <select required value={hopId} onChange={e => setHopId(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500">
                                <option value="">Select HOP</option>
                                {staff.map(s => (
                                    <option key={s.staff_id} value={s.staff_id}>
                                        {s.user?.full_name ? `${s.user.full_name} (${s.staff_id})` : s.staff_id}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>
                    <div className="flex justify-end gap-3 mt-6">
                        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancel</button>
                        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-sm transition-all duration-300">
                            {isEdit ? "Update Programme" : "Create Programme"}
                        </button>
                    </div>
                </form>
            );
        }

window.UserForm = UserForm;
window.StudentForm = StudentForm;
window.LecturerForm = LecturerForm;
window.StaffForm = StaffForm;
window.VisitorForm = VisitorForm;
window.AdminForm = AdminForm;
window.DocumentForm = DocumentForm;
window.DeviceForm = DeviceForm;
window.NodeRBACForm = NodeRBACForm;
window.CourseForm = CourseForm;
window.EnrollmentForm = EnrollmentForm;
window.TimetableForm = TimetableForm;
window.AppointmentForm = AppointmentForm;
window.RoleForm = RoleForm;
window.FacultyForm = FacultyForm;
window.DepartmentForm = DepartmentForm;
window.ProgrammeForm = ProgrammeForm;
