import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RotateCcw, Save, SlidersHorizontal } from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';

const DEFAULTS = {
  recognition_threshold: 0.363,
  detection_threshold: 0.6,
  min_face_size: 48,
  min_embedding_samples: 2,
  candidate_consistency_ratio: 0.65,
  recognition_delay_seconds: 1.0,
  require_liveness: true,
  pad_required: true,
  pad_threshold: 0.75,
  pad_smooth_frames: 3,
  door_relay_enabled: true,
  door_unlock_duration_seconds: 5.0,
  audio_enabled: true,
  presence_activation_enabled: true,
  presence_dwell_seconds: 3.0,
  presence_activation_cooldown_seconds: 5.0,
  minimum_face_size_ratio: 0.15,
  frontal_face_threshold: 25.0,
  frontal_pitch_threshold: 20.0,
};

function NumberField({ label, hint, value, onChange, min, max, step, disabled = false }) {
  return (
    <label className="block space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">{label}</span>
        <span className="text-[11px] font-mono text-slate-400">
          {min}–{max}
        </span>
      </div>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        value={value}
        onChange={(e) => {
          const parsed = step === 1 ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
          if (!Number.isNaN(parsed)) onChange(parsed);
        }}
        className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm font-mono disabled:opacity-50"
      />
      {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
    </label>
  );
}

function ToggleField({ label, hint, checked, onChange }) {
  return (
    <label className="flex items-center justify-between gap-3 p-3 rounded-xl border border-slate-200 dark:border-slate-800 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40">
      <div>
        <div className="text-xs font-bold text-slate-800 dark:text-slate-100">{label}</div>
        {hint && <div className="text-[11px] text-slate-500 mt-0.5">{hint}</div>}
      </div>
      <input
        type="checkbox"
        checked={Boolean(checked)}
        onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 shrink-0"
      />
    </label>
  );
}

export function AccessControlSettingsCard({ deviceId }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState(DEFAULTS);
  const [saving, setSaving] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['device-access-config', deviceId],
    queryFn: () => cloudApi.get(`/api/infra/devices/${deviceId}/access-config`),
  });

  useEffect(() => {
    if (data) {
      setForm({ ...DEFAULTS, ...data });
    }
  }, [data]);

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await cloudApi.put(`/api/infra/devices/${deviceId}/access-config`, form);
      toast.success(
        res.pushed_over_ws
          ? 'Access control settings saved and pushed live to the device.'
          : 'Access control settings saved; device will apply them on next sync.'
      );
      queryClient.invalidateQueries({ queryKey: ['device-access-config', deviceId] });
    } catch (err) {
      toast.error(err.message || 'Failed to save access control settings.');
    } finally {
      setSaving(false);
    }
  };

  const handleResetDefaults = () => {
    setForm((prev) => ({
      ...prev,
      recognition_threshold: DEFAULTS.recognition_threshold,
      require_liveness: DEFAULTS.require_liveness,
      pad_threshold: DEFAULTS.pad_threshold,
      door_relay_enabled: DEFAULTS.door_relay_enabled,
      door_unlock_duration_seconds: DEFAULTS.door_unlock_duration_seconds,
      audio_enabled: DEFAULTS.audio_enabled,
    }));
  };

  return (
    <form
      onSubmit={handleSave}
      className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-5"
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400">
            <SlidersHorizontal className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Access Control Settings</h2>
            <p className="text-xs text-slate-500">
              Essential recognition, anti-spoofing, and door controls. Saved changes push live over WebSocket.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleResetDefaults}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Defaults
          </button>
          <button
            type="submit"
            disabled={saving || isLoading}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50"
          >
            <Save className="w-3.5 h-3.5" /> {saving ? 'Saving...' : 'Save & Push Live'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <NumberField
          label="Cosine Similarity Threshold"
          hint="Higher = stricter match (SFace default: 0.363)"
          value={form.recognition_threshold}
          onChange={(v) => setField('recognition_threshold', v)}
          min={0.1}
          max={0.95}
          step={0.005}
        />
        <NumberField
          label="Anti-Spoofing Threshold"
          hint="Minimum live probability (default: 0.75)"
          value={form.pad_threshold}
          onChange={(v) => setField('pad_threshold', v)}
          min={0.1}
          max={0.99}
          step={0.05}
          disabled={!form.require_liveness}
        />
        <NumberField
          label="Door Unlock Duration (s)"
          hint="Relay hold time after unlock (default: 5.0s)"
          value={form.door_unlock_duration_seconds}
          onChange={(v) => setField('door_unlock_duration_seconds', v)}
          min={1.0}
          max={30.0}
          step={0.5}
          disabled={!form.door_relay_enabled}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <ToggleField
          label="Require Liveness Check"
          hint="Block photos and screen replays"
          checked={form.require_liveness}
          onChange={(v) => setField('require_liveness', v)}
        />
        <ToggleField
          label="Door Relay Enabled"
          hint="Trigger lock relay on access granted"
          checked={form.door_relay_enabled}
          onChange={(v) => setField('door_relay_enabled', v)}
        />
        <ToggleField
          label="Audio Feedback"
          hint="Play granted/denied voice cues"
          checked={form.audio_enabled}
          onChange={(v) => setField('audio_enabled', v)}
        />
      </div>
    </form>
  );
}
