import { useEffect, useState } from 'react';
import { CheckCircle2, Download, QrCode, X } from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';

export function DevicePairingModal({ details, onClose, onPaired }) {
  const toast = useToast();
  const [paired, setPaired] = useState(false);
  const [showManual, setShowManual] = useState(false);

  useEffect(() => {
    setPaired(Boolean(details?.paired));
    setShowManual(false);
  }, [details?.device_id, details?.pairing_code]);

  useEffect(() => {
    if (!details?.device_id || paired) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const latest = await cloudApi.get(`/api/infra/devices/${details.device_id}`);
        if (!cancelled && latest?.pairing_claimed_at) {
          setPaired(true);
          toast.success(`Device "${latest.device_name || latest.device_id}" paired and online!`);
          onPaired?.(latest);
        }
      } catch {
        // ignore transient poll errors
      }
    };
    const timer = setInterval(poll, 2500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [details?.device_id, paired, toast, onPaired]);

  if (!details) return null;

  let resolvedCloudUrl = window.location.origin;
  if (details.pairing_qr_payload) {
    try {
      const parsed = JSON.parse(details.pairing_qr_payload);
      if (parsed?.cloud_url) resolvedCloudUrl = parsed.cloud_url;
    } catch {
      // fall back to window.location.origin
    }
  }

  const handleDownloadProvisionJson = () => {
    const payload = {
      cloud_url: resolvedCloudUrl,
      device_id: details.device_id,
      device_name: details.device_name || details.device_id,
      device_secret: details.secret,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `provision-${details.device_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/75 backdrop-blur-sm p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl rounded-2xl border border-slate-200 dark:border-amber-500/40 bg-white dark:bg-slate-900 p-6 shadow-2xl my-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 mb-5">
          <div className="flex items-start gap-3">
            <div
              className={`p-2.5 rounded-xl border ${
                paired
                  ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/30'
                  : 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-500/30'
              }`}
            >
              {paired ? <CheckCircle2 className="w-5 h-5" /> : <QrCode className="w-5 h-5" />}
            </div>
            <div>
              <h3 className="text-lg font-extrabold text-slate-900 dark:text-slate-100">
                Pair {details.device_name || details.device_id}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {paired
                  ? 'Device has claimed its credentials and is syncing with the cloud.'
                  : 'Hold this QR code in front of the Access Control kiosk or Surveillance camera, or enter the 8-character pairing code.'}
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-slate-400 hover:text-slate-600">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="mb-4">
          <span
            className={`inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold border ${
              paired
                ? 'bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30'
                : 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-500/30'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${paired ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse'}`} />
            {paired ? 'Paired & Online' : 'Waiting for device...'}
          </span>
        </div>

        {!paired && details.pairing_code && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-center rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 p-4 mb-4">
            <div className="flex flex-col items-center justify-center">
              {details.pairing_qr_svg_data_uri ? (
                <img
                  src={details.pairing_qr_svg_data_uri}
                  alt="Device pairing QR code"
                  className="w-44 h-44 rounded-xl bg-white p-2 border border-slate-200 shadow-sm"
                />
              ) : (
                <div className="w-44 h-44 rounded-xl bg-slate-200 dark:bg-slate-800 flex items-center justify-center text-xs text-slate-500 text-center p-4">
                  QR unavailable — use pairing code
                </div>
              )}
              <span className="text-[11px] text-slate-500 mt-2">Expires in 15 minutes</span>
            </div>
            <div className="space-y-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">
                Pairing Code
              </div>
              <div className="font-mono text-2xl font-extrabold tracking-widest text-slate-900 dark:text-white bg-white dark:bg-slate-900 border border-indigo-200 dark:border-indigo-500/30 rounded-xl px-4 py-3 text-center select-all">
                {details.pairing_code}
              </div>
              <ol className="list-decimal list-inside text-xs text-slate-600 dark:text-slate-300 space-y-1">
                <li>
                  <span className="font-semibold">Access Control:</span> Hold QR in front of kiosk camera or type the code.
                </li>
                <li>
                  <span className="font-semibold">Surveillance:</span> Hold QR in front of camera or open{' '}
                  <span className="font-mono text-indigo-600 dark:text-indigo-300">/setup</span>.
                </li>
              </ol>
            </div>
          </div>
        )}

        <div className="space-y-1.5 text-xs mb-4">
          <div className="flex justify-between gap-4">
            <span className="text-slate-500">Device ID</span>
            <span className="font-mono font-bold text-indigo-600 dark:text-indigo-300">{details.device_id}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-slate-500">Cloud URL</span>
            <span className="font-mono text-slate-700 dark:text-slate-200">{resolvedCloudUrl}</span>
          </div>
        </div>

        {details.secret && (
          <div className="mb-5">
            <button
              type="button"
              onClick={() => setShowManual((prev) => !prev)}
              className="text-xs font-semibold text-slate-500 hover:text-amber-600 dark:hover:text-amber-300 underline"
            >
              {showManual ? 'Hide manual secret (advanced)' : 'Show manual secret / download provision.json'}
            </button>
            {showManual && (
              <div className="mt-2 rounded-xl border border-amber-300 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 p-3.5 space-y-2.5">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-amber-800 dark:text-amber-300 mb-1">
                    One-time secret
                  </div>
                  <div className="font-mono text-xs text-amber-900 dark:text-amber-100 break-all select-all">
                    {details.secret}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleDownloadProvisionJson}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white dark:bg-slate-800 border border-amber-300 dark:border-amber-500/30 text-xs font-semibold text-amber-900 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-slate-700"
                >
                  <Download className="w-3.5 h-3.5" />
                  Download provision.json
                </button>
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className={`px-4 py-2 rounded-xl text-xs font-bold ${
              paired ? 'bg-emerald-600 hover:bg-emerald-700 text-white' : 'bg-indigo-600 hover:bg-indigo-700 text-white'
            }`}
          >
            {paired ? 'Done' : 'Close'}
          </button>
        </div>
      </div>
    </div>
  );
}
