import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, Plus, Search, Trash2, Upload, X } from 'lucide-react';
import { cloudApi, formatDateTime } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';

const ACCESS_ROLES = ['VISITOR', 'STUDENT', 'LECTURER', 'STAFF', 'ADMIN'];

export function DocumentsPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [search, setSearch] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [file, setFile] = useState(null);
  const [allowedRoles, setAllowedRoles] = useState(['VISITOR']);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['rag-documents'],
    queryFn: () => cloudApi.get('/api/rag/documents'),
  });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return docs;
    return docs.filter(
      (d) => d.title?.toLowerCase().includes(q) || d.filename?.toLowerCase().includes(q)
    );
  }, [docs, search]);

  const toggleRole = (role) => {
    setAllowedRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]
    );
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file || !title.trim()) return;
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append('title', title.trim());
      fd.append('uploaded_by', '1');
      fd.append('allowed_roles', JSON.stringify(allowedRoles.length ? allowedRoles : ['VISITOR']));
      fd.append('access_level', allowedRoles[0] || 'VISITOR');
      fd.append('is_active', 'true');
      fd.append('file', file);
      await cloudApi.post('/api/rag/documents', fd);
      toast.success('Document uploaded and indexed.');
      setUploadOpen(false);
      setTitle('');
      setFile(null);
      queryClient.invalidateQueries({ queryKey: ['rag-documents'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleToggleActive = async (doc) => {
    try {
      await cloudApi.post(`/api/rag/documents/${doc.document_id}/toggle-active`, {});
      toast.success('Document status updated.');
      queryClient.invalidateQueries({ queryKey: ['rag-documents'] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await cloudApi.delete(`/api/rag/documents/${deleteTarget.document_id}`);
      toast.success('Document deleted.');
      queryClient.invalidateQueries({ queryKey: ['rag-documents'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setDeleteTarget(null);
    }
  };

  const columns = useMemo(
    () => [
      {
        id: 'doc',
        header: 'Document',
        cell: ({ row }) => (
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 flex items-center justify-center shrink-0">
              <FileText className="w-4 h-4" />
            </div>
            <div>
              <div className="font-bold text-slate-900 dark:text-slate-100">{row.original.title}</div>
              <div className="text-xs font-mono text-slate-500">{row.original.filename}</div>
            </div>
          </div>
        ),
      },
      {
        id: 'access',
        header: 'Allowed Roles',
        cell: ({ row }) => {
          const roles = row.original.allowed_roles?.length ? row.original.allowed_roles : [row.original.access_level || 'PUBLIC'];
          return (
            <div className="flex flex-wrap gap-1">
              {roles.map((r) => (
                <StatusBadge key={r} variant="info">{r}</StatusBadge>
              ))}
            </div>
          );
        },
      },
      {
        id: 'uploaded',
        header: 'Uploaded',
        cell: ({ row }) => (
          <span className="text-xs text-slate-500 tabular-nums">
            {formatDateTime(row.original.uploaded_at || row.original.created_at)}
          </span>
        ),
      },
      {
        id: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <button type="button" onClick={() => handleToggleActive(row.original)}>
            <StatusBadge variant={row.original.is_active ? 'success' : 'neutral'} dot>
              {row.original.is_active ? 'Active' : 'Archived'}
            </StatusBadge>
          </button>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        meta: { align: 'right' },
        cell: ({ row }) => (
          <button
            type="button"
            onClick={() => setDeleteTarget(row.original)}
            className="p-1.5 rounded-lg text-slate-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-500/15"
            title="Delete Document"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        ),
      },
    ],
    []
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
            Knowledge Base Documents
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Upload and govern role-restricted campus documents indexed by the RAG chatbot.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setUploadOpen(true)}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white"
        >
          <Plus className="w-4 h-4" /> Upload Document
        </button>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5">
        <div className="relative max-w-xs">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter documents..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-sm"
          />
        </div>
      </div>

      <DataTable columns={columns} data={filtered} loading={isLoading} total={filtered.length} />

      {uploadOpen && (
        <div className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-900/50 p-4" onClick={() => setUploadOpen(false)}>
          <div className="w-full max-w-lg rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-bold">Upload Knowledge Document</h3>
              <button type="button" onClick={() => setUploadOpen(false)} className="p-1 text-slate-400"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={handleUpload} className="space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Title *</label>
                <input type="text" required value={title} onChange={(e) => setTitle(e.target.value)} className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">File (PDF, DOCX, TXT, MD, CSV) *</label>
                <label className="flex items-center justify-center gap-2 border-2 border-dashed border-slate-300 dark:border-slate-700 rounded-xl p-4 cursor-pointer text-xs font-semibold text-slate-600 dark:text-slate-300">
                  <Upload className="w-4 h-4" />
                  <span>{file ? file.name : 'Choose document file'}</span>
                  <input type="file" required accept=".pdf,.docx,.doc,.txt,.md,.csv" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                </label>
              </div>
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1.5">Allowed Roles</label>
                <div className="flex flex-wrap gap-2">
                  {ACCESS_ROLES.map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => toggleRole(r)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-colors ${
                        allowedRoles.includes(r)
                          ? 'bg-indigo-600 text-white border-indigo-600'
                          : 'bg-slate-50 dark:bg-slate-950 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-800'
                      }`}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setUploadOpen(false)} className="px-4 py-2 rounded-xl text-sm font-semibold bg-slate-100 dark:bg-slate-800">Cancel</button>
                <button type="submit" disabled={saving} className="px-4 py-2 rounded-xl text-sm font-bold bg-indigo-600 text-white">{saving ? 'Uploading...' : 'Upload'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete Document"
        message={`Remove "${deleteTarget?.title}" and its indexed vector chunks?`}
        confirmLabel="Delete"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
