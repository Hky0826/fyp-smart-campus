import { useState } from 'react';
import { AlertCircle, CheckCircle2, Download, FileSpreadsheet, Upload, X } from 'lucide-react';
import { cloudApi } from '../../lib/cloudApi';
import { useToast } from '../../providers/ToastProvider';
import { StatusBadge } from '../ui/StatusBadge';

const SAMPLE_CSV = [
  'role,given_name,family_name,email,intake,programme_id,faculty_id,department_id,position,staff_type,id_number,organization,visit_purpose,access_expiry',
  'STUDENT,Aina,Zulkifli,aina.zulkifli@qiu.edu.my,202407,PRG-CS,FAC-CS,,,,,,,',
  'LECTURER,Daniel,Lim,daniel.lim@qiu.edu.my,,,FAC-CS,DEP-IT,Senior Lecturer,,,,,',
  'STAFF,Siti,Rahman,siti.rahman@qiu.edu.my,,,,DEP-IT,Operations Lead,ADMINISTRATIVE,,,,',
  'VISITOR,Marcus,Tan,marcus.tan@partner.org,,,,,,,IC901212,Partner Labs,Campus Audit,2026-12-31T18:00',
].join('\n');

export function CsvImportWizard({ open, onClose, onImported }) {
  const toast = useToast();
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [skipInvalid, setSkipInvalid] = useState(true);
  const [validating, setValidating] = useState(false);
  const [committing, setCommitting] = useState(false);

  if (!open) return null;

  const downloadTemplate = () => {
    const blob = new Blob([SAMPLE_CSV], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'smart-campus-users-import-template.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFileChange = async (e) => {
    const selected = e.target.files?.[0];
    if (!selected) return;
    setFile(selected);
    setPreview(null);
    setValidating(true);
    try {
      const fd = new FormData();
      fd.append('file', selected);
      const data = await cloudApi.post('/api/iam/users/import/validate', fd);
      setPreview(data);
    } catch (err) {
      toast.error(err.message || 'CSV validation failed.');
    } finally {
      setValidating(false);
    }
  };

  const handleCommit = async () => {
    if (!file || !preview || preview.valid_count === 0) return;
    setCommitting(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('skip_invalid', String(skipInvalid));
      const res = await cloudApi.post('/api/iam/users/import/commit', fd);
      toast.success(res.detail || `Imported ${res.created} user(s).`);
      onImported?.();
      setFile(null);
      setPreview(null);
      onClose();
    } catch (err) {
      toast.error(err.message || 'CSV import failed.');
    } finally {
      setCommitting(false);
    }
  };

  const resetAndClose = () => {
    setFile(null);
    setPreview(null);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-900/50 dark:bg-slate-950/75 backdrop-blur-xs p-4"
      onClick={resetAndClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-4xl max-h-[88vh] flex flex-col rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400">
              <FileSpreadsheet className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">
                Bulk CSV User Import
              </h3>
            </div>
          </div>
          <button
            type="button"
            onClick={resetAndClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5 scrollbar-thin">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200 dark:border-slate-800">
            <div>
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                1. Download CSV template
              </p>
            </div>
            <button
              type="button"
              onClick={downloadTemplate}
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200 hover:border-indigo-400 shrink-0"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download Template</span>
            </button>
          </div>

          <label className="block border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-indigo-400 dark:hover:border-indigo-500 rounded-2xl p-8 text-center cursor-pointer transition-colors bg-slate-50/50 dark:bg-slate-950/30">
            <Upload className="w-8 h-8 mx-auto text-slate-400 mb-2" />
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              {file ? file.name : '2. Choose a CSV file to validate'}
            </p>
            <p className="text-xs text-slate-500 mt-1">Max 5 MB · UTF-8 CSV · Dry-run runs automatically</p>
            <input type="file" accept=".csv,text/csv" className="hidden" onChange={handleFileChange} />
          </label>

          {validating && (
            <div className="flex items-center justify-center gap-2.5 py-6 text-sm text-slate-500">
              <span className="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
              <span>Validating rows against campus database...</span>
            </div>
          )}

          {preview && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/50">
                  <div className="text-[11px] font-bold uppercase text-slate-500">Total Rows</div>
                  <div className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tabular-nums mt-0.5">
                    {preview.total_rows}
                  </div>
                </div>
                <div className="p-3.5 rounded-xl border border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/60 dark:bg-emerald-500/10">
                  <div className="text-[11px] font-bold uppercase text-emerald-700 dark:text-emerald-400">Valid</div>
                  <div className="text-2xl font-extrabold text-emerald-700 dark:text-emerald-300 tabular-nums mt-0.5">
                    {preview.valid_count}
                  </div>
                </div>
                <div className="p-3.5 rounded-xl border border-red-200 dark:border-red-500/20 bg-red-50/60 dark:bg-red-500/10">
                  <div className="text-[11px] font-bold uppercase text-red-700 dark:text-red-400">Errors</div>
                  <div className="text-2xl font-extrabold text-red-700 dark:text-red-300 tabular-nums mt-0.5">
                    {preview.error_count}
                  </div>
                </div>
              </div>

              {preview.error_count > 0 && (
                <label className="flex items-center gap-2 text-xs font-medium text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={skipInvalid}
                    onChange={(e) => setSkipInvalid(e.target.checked)}
                    className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span>Skip invalid rows and import only the {preview.valid_count} valid user(s)</span>
                </label>
              )}

              <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden max-h-72 overflow-y-auto scrollbar-thin">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 dark:bg-slate-950 border-b border-slate-200 dark:border-slate-800 sticky top-0">
                    <tr>
                      <th className="py-2.5 px-3 font-bold text-slate-500">Row</th>
                      <th className="py-2.5 px-3 font-bold text-slate-500">Status</th>
                      <th className="py-2.5 px-3 font-bold text-slate-500">Role</th>
                      <th className="py-2.5 px-3 font-bold text-slate-500">Name & Email</th>
                      <th className="py-2.5 px-3 font-bold text-slate-500">Validation Notes</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {preview.rows.slice(0, 100).map((r) => (
                      <tr key={r.row_number} className={r.valid ? '' : 'bg-red-50/40 dark:bg-red-500/5'}>
                        <td className="py-2 px-3 font-mono text-slate-500 tabular-nums">#{r.row_number}</td>
                        <td className="py-2 px-3">
                          {r.valid ? (
                            <StatusBadge variant="success">
                              <CheckCircle2 className="w-3 h-3" /> Valid
                            </StatusBadge>
                          ) : (
                            <StatusBadge variant="danger">
                              <AlertCircle className="w-3 h-3" /> Invalid
                            </StatusBadge>
                          )}
                        </td>
                        <td className="py-2 px-3 font-mono font-bold text-slate-700 dark:text-slate-300">{r.role}</td>
                        <td className="py-2 px-3">
                          <div className="font-semibold text-slate-900 dark:text-slate-100">
                            {r.given_name} {r.family_name}
                          </div>
                          <div className="font-mono text-slate-500">{r.email}</div>
                        </td>
                        <td className="py-2 px-3 text-slate-600 dark:text-slate-400">
                          {r.valid ? 'Ready to import' : r.errors.join('; ')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-end gap-2.5 bg-slate-50/70 dark:bg-slate-950/40">
          <button
            type="button"
            onClick={resetAndClose}
            className="px-4 py-2 rounded-xl text-sm font-semibold text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!preview || preview.valid_count === 0 || (!skipInvalid && preview.error_count > 0) || committing}
            onClick={handleCommit}
            className="px-5 py-2 rounded-xl text-sm font-bold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 flex items-center gap-2"
          >
            {committing && <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />}
            <span>Import {preview?.valid_count ?? 0} User(s)</span>
          </button>
        </div>
      </div>
    </div>
  );
}
