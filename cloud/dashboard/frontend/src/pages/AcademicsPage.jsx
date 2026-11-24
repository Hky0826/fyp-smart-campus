import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';

const TABS = [
  { id: 'courses', label: 'Courses' },
  { id: 'enrollments', label: 'Enrollments' },
  { id: 'timetables', label: 'Timetables' },
  { id: 'appointments', label: 'Appointments' },
  { id: 'notifications', label: 'Notifications' },
  { id: 'faculties', label: 'Faculties' },
  { id: 'departments', label: 'Departments' },
  { id: 'programmes', label: 'Programmes' },
];

export function AcademicsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'courses';
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10));
  const pageSize = [10, 25, 50, 100].includes(parseInt(searchParams.get('page_size') || '25', 10))
    ? parseInt(searchParams.get('page_size') || '25', 10)
    : 25;
  const [search, setSearch] = useState('');

  const setTab = (tabId) => {
    setSearch('');
    setSearchParams(new URLSearchParams({ tab: tabId, page: '1' }), { replace: true });
  };

  const isPaginated = activeTab === 'enrollments' || activeTab === 'notifications';

  const { data, isLoading } = useQuery({
    queryKey: ['academics', activeTab, page, pageSize, isPaginated ? search : ''],
    queryFn: () => {
      if (activeTab === 'enrollments') return cloudApi.get('/api/academics/enrollments/paginated', { page, page_size: pageSize, q: search });
      if (activeTab === 'notifications') return cloudApi.get('/api/academics/notifications/paginated', { page, page_size: pageSize, q: search });
      const epMap = {
        courses: '/api/academics/courses',
        timetables: '/api/academics/timetables',
        appointments: '/api/academics/appointments',
        faculties: '/api/refs/faculties',
        departments: '/api/refs/departments',
        programmes: '/api/refs/programmes',
      };
      return cloudApi.get(epMap[activeTab] || '/api/academics/courses');
    },
    placeholderData: (prev) => prev,
  });

  const rows = useMemo(() => {
    if (isPaginated) return data?.items ?? [];
    const list = Array.isArray(data) ? data : [];
    const q = search.trim().toLowerCase();
    if (!q) return list;
    return list.filter((item) => JSON.stringify(item).toLowerCase().includes(q));
  }, [data, isPaginated, search]);

  const columns = useMemo(() => {
    if (activeTab === 'courses') {
      return [
        { id: 'code', header: 'Code', cell: ({ row }) => <span className="font-mono font-bold text-indigo-600 dark:text-indigo-400">{row.original.course_code}</span> },
        { id: 'name', header: 'Course Name', cell: ({ row }) => <span className="font-semibold">{row.original.course_name}</span> },
        { id: 'credits', header: 'Credits', cell: ({ row }) => <span className="font-mono text-xs">{row.original.credit_hours} cr</span> },
        { id: 'level', header: 'Level', cell: ({ row }) => <StatusBadge variant="neutral">{row.original.course_level}</StatusBadge> },
      ];
    }
    if (activeTab === 'enrollments') {
      return [
        { id: 'student', header: 'Student ID', cell: ({ row }) => <span className="font-mono font-bold">{row.original.student_id}</span> },
        { id: 'course', header: 'Course', cell: ({ row }) => <span><strong className="font-mono text-indigo-600 dark:text-indigo-400 mr-1.5">{row.original.course_code}</strong>{row.original.course_name}</span> },
        { id: 'term', header: 'Term', cell: ({ row }) => <span className="text-xs text-slate-500">{row.original.academic_year} · Sem {row.original.semester}</span> },
        { id: 'status', header: 'Status', cell: ({ row }) => <StatusBadge variant="info">{row.original.status}</StatusBadge> },
      ];
    }
    if (activeTab === 'timetables') {
      return [
        { id: 'course', header: 'Course', cell: ({ row }) => <span className="font-mono font-bold">{row.original.course_code || `Course #${row.original.course_id}`}</span> },
        { id: 'day', header: 'Day & Time', cell: ({ row }) => <span className="text-xs font-mono">{row.original.day_of_week} · {row.original.start_time}–{row.original.end_time}</span> },
        { id: 'lec', header: 'Lecturer', cell: ({ row }) => <span className="font-mono text-xs">{row.original.lecturer_id}</span> },
        { id: 'room', header: 'Node', cell: ({ row }) => <span className="text-xs text-slate-500">Node #{row.original.node_id}</span> },
      ];
    }
    if (activeTab === 'appointments') {
      return [
        { id: 'id', header: 'ID', cell: ({ row }) => <span className="font-mono text-xs">#{row.original.appointment_id}</span> },
        { id: 'when', header: 'Scheduled', cell: ({ row }) => <span className="text-xs tabular-nums">{formatDateTime(row.original.scheduled_at)}</span> },
        { id: 'purpose', header: 'Purpose', cell: ({ row }) => <span className="text-sm">{row.original.purpose || '—'}</span> },
        { id: 'status', header: 'Status', cell: ({ row }) => <StatusBadge variant="info">{row.original.status}</StatusBadge> },
      ];
    }
    if (activeTab === 'notifications') {
      return [
        { id: 'title', header: 'Title', cell: ({ row }) => <span className="font-semibold">{row.original.title}</span> },
        { id: 'body', header: 'Message', cell: ({ row }) => <span className="text-xs text-slate-500 max-w-md truncate block">{row.original.body}</span> },
        { id: 'status', header: 'Delivery', cell: ({ row }) => <StatusBadge variant={row.original.status === 'SENT' ? 'success' : 'neutral'}>{row.original.status}</StatusBadge> },
        { id: 'time', header: 'Created', cell: ({ row }) => <span className="text-xs text-slate-500">{formatDateTime(row.original.created_at)}</span> },
      ];
    }
    if (activeTab === 'faculties') {
      return [
        { id: 'id', header: 'Faculty ID', cell: ({ row }) => <span className="font-mono font-bold text-xs">{row.original.faculty_id}</span> },
        { id: 'name', header: 'Faculty Name', cell: ({ row }) => <span className="font-semibold">{row.original.faculty_name}</span> },
        { id: 'dean', header: 'Dean ID', cell: ({ row }) => <span className="font-mono text-xs text-slate-500">{row.original.dean_id}</span> },
      ];
    }
    if (activeTab === 'departments') {
      return [
        { id: 'id', header: 'Department ID', cell: ({ row }) => <span className="font-mono font-bold text-xs">{row.original.department_id}</span> },
        { id: 'name', header: 'Department Name', cell: ({ row }) => <span className="font-semibold">{row.original.department_name}</span> },
        { id: 'mgr', header: 'Manager ID', cell: ({ row }) => <span className="font-mono text-xs text-slate-500">{row.original.manager_id}</span> },
      ];
    }
    return [
      { id: 'id', header: 'Programme ID', cell: ({ row }) => <span className="font-mono font-bold text-xs">{row.original.programme_id}</span> },
      { id: 'name', header: 'Programme Name', cell: ({ row }) => <span className="font-semibold">{row.original.programme_name}</span> },
      { id: 'fac', header: 'Faculty ID', cell: ({ row }) => <span className="font-mono text-xs text-slate-500">{row.original.faculty_id}</span> },
    ];
  }, [activeTab]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
          Academics & Scheduling
        </h1>
      </div>

      <div className="flex flex-wrap gap-1.5 border-b border-slate-200 dark:border-slate-800 pb-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-colors ${
              activeTab === t.id
                ? 'bg-indigo-600 text-white'
                : 'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative max-w-xs">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={`Search ${activeTab}...`}
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
      </div>

      <DataTable
        columns={columns}
        data={rows}
        loading={isLoading}
        total={isPaginated ? (data?.total ?? 0) : rows.length}
        page={isPaginated ? (data?.page ?? page) : 1}
        pageSize={isPaginated ? (data?.page_size ?? pageSize) : Math.max(rows.length, 25)}
        totalPages={isPaginated ? (data?.total_pages ?? 1) : 1}
        onPageChange={
          isPaginated
            ? (p) => {
                const next = new URLSearchParams(searchParams);
                next.set('page', String(p));
                setSearchParams(next, { replace: true });
              }
            : undefined
        }
        onPageSizeChange={
          isPaginated
            ? (sz) => {
                const next = new URLSearchParams(searchParams);
                next.set('page_size', String(sz));
                next.set('page', '1');
                setSearchParams(next, { replace: true });
              }
            : undefined
        }
      />
    </div>
  );
}
