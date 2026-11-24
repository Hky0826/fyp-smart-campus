import { useState } from 'react';
import { Camera, Film, ScanFace, Upload, X } from 'lucide-react';
import { cloudApi } from '../../lib/cloudApi';
import { useToast } from '../../providers/ToastProvider';

const POSES = [
  { id: 'front', label: 'Front (also refreshes low-light template)' },
  { id: 'left_30', label: 'Turn left 30°' },
  { id: 'right_30', label: 'Turn right 30°' },
  { id: 'left_60', label: 'Turn left 60°' },
  { id: 'right_60', label: 'Turn right 60°' },
  { id: 'slightly_up', label: 'Look slightly up' },
];

export function FaceEnrollModal({ open, user, onClose, onEnrolled }) {
  const toast = useToast();
  const [method, setMethod] = useState('photo');
  const [pose, setPose] = useState('front');
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [busy, setBusy] = useState(false);

  if (!open || !user) return null;

  const cleanup = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl('');
    setFile(null);
    onClose();
  };

  const handleFilePick = (e) => {
    const picked = e.target.files?.[0];
    if (!picked) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(picked);
    if (method === 'photo') {
      setPreviewUrl(URL.createObjectURL(picked));
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      if (method === 'photo') {
        fd.append('pose', pose);
        await cloudApi.post(`/api/iam/users/${user.user_id}/enroll-face`, fd);
        toast.success(`Face ID (${pose}) enrolled for ${user.full_name}.`);
      } else {
        await cloudApi.post(`/api/iam/users/${user.user_id}/enroll-video`, fd);
        toast.success(`Face ID video enrolled for ${user.full_name}.`);
      }
      onEnrolled?.();
      cleanup();
    } catch (err) {
      toast.error(err.message || 'Face enrollment failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-900/50 dark:bg-slate-950/75 backdrop-blur-xs p-4"
      onClick={cleanup}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400">
              <ScanFace className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">Face ID Enrollment</h3>
              <p className="text-xs text-slate-500">{user.full_name} · #{user.user_id}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={cleanup}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-1.5 p-1 rounded-xl bg-slate-100 dark:bg-slate-950 border border-slate-200 dark:border-slate-800">
            <button
              type="button"
              onClick={() => { setMethod('photo'); setFile(null); setPreviewUrl(''); }}
              className={`py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-colors ${
                method === 'photo'
                  ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
                  : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
              }`}
            >
              <Camera className="w-3.5 h-3.5" /> Photo Pose
            </button>
            <button
              type="button"
              onClick={() => { setMethod('video'); setFile(null); setPreviewUrl(''); }}
              className={`py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-colors ${
                method === 'video'
                  ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
                  : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
              }`}
            >
              <Film className="w-3.5 h-3.5" /> Rotation Video
            </button>
          </div>

          {method === 'photo' && (
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-600 dark:text-slate-400 mb-1.5">
                Pose Angle
              </label>
              <select
                value={pose}
                onChange={(e) => setPose(e.target.value)}
                className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100"
              >
                {POSES.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          <label className="block border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-indigo-400 rounded-2xl p-6 text-center cursor-pointer bg-slate-50/50 dark:bg-slate-950/30">
            {previewUrl ? (
              <img src={previewUrl} alt="Preview" className="mx-auto max-h-48 rounded-xl object-cover" />
            ) : (
              <>
                <Upload className="w-7 h-7 mx-auto text-slate-400 mb-2" />
                <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                  {file ? file.name : method === 'photo' ? 'Choose a clear face photo' : 'Choose a short head-rotation video'}
                </p>
              </>
            )}
            <input
              type="file"
              accept={method === 'photo' ? 'image/*' : 'video/*'}
              className="hidden"
              onChange={handleFilePick}
            />
          </label>

          <div className="flex items-center justify-end gap-2.5 pt-2">
            <button
              type="button"
              onClick={cleanup}
              className="px-4 py-2 rounded-xl text-sm font-semibold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!file || busy}
              className="px-5 py-2 rounded-xl text-sm font-bold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 flex items-center gap-2"
            >
              {busy && <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />}
              <span>{busy ? 'Embedding...' : 'Save Face ID'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
