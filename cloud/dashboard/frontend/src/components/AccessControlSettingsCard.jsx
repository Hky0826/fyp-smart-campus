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

function NumberField({ label, hint, value, onChange, min, max, step }) {
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
        value={value}
        onChange={(e) => {
          const parsed = step === 1 ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
          if (!Number.isNaN(parsed)) onChange(parsed);
        }}
        className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-1.5 text-sm font-mono"
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
    setForm(DEFAULTS);
  };

  return (
    <form
      onSubmit={handleSave}
      className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-6"
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400">
            <SlidersHorizontal className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Access Control Parameters</h2>
            <p className="text-xs text-slate-500">
              Tune recognition thresholds, anti-spoofing, door timing, and presence rules. Changes push live over WebSocket.
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

      {/* Highlighted Primary Control: Cosine Similarity Threshold */}
      <div className="rounded-2xl border border-indigo-200 dark:border-indigo-500/30 bg-indigo-50/60 dark:bg-indigo-500/10 p-4 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <div className="text-sm font-extrabold text-indigo-950 dark:text-indigo-200">
              Cosine Similarity Threshold (Recognition Threshold)
            </div>
            <p className="text-xs text-indigo-800/80 dark:text-indigo-300/80">
              Minimum cosine similarity score required to match a face. Lower = more lenient, higher = stricter (SFace default: 0.363).
            </p>
          </div>
          <input
            type="number"
            min={0.1}
            max={0.95}
            step={0.005}
            value={form.recognition_threshold}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              if (!Number.isNaN(v)) setField('recognition_threshold', v);
            }}
            className="w-28 rounded-xl border border-indigo-300 dark:border-indigo-500/40 bg-white dark:bg-slate-900 px-3 py-1.5 text-base font-mono font-bold text-indigo-700 dark:text-indigo-300 text-center"
          />
        </div>
        <input
          type="range"
          min={0.1}
          max={0.95}
          step={0.005}
          value={form.recognition_threshold}
          onChange={(e) => setField('recognition_threshold', parseFloat(e.target.value))}
          className="w-full accent-indigo-600 cursor-pointer"
        />
        <div className="flex justify-between text-[11px] font-mono text-indigo-700/70 dark:text-indigo-300/70">
          <span>0.10 (Lenient)</span>
          <span>0.363 (SFace Default)</span>
          <span>0.95 (Strict)</span>
        </div>
      </div>

      {/* Section 1: Recognition & Matching */}
      <div className="space-y-3">
        <h3 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Recognition & Matching</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <NumberField
            label="Detection Confidence"
            hint="YuNet face detector threshold"
            value={form.detection_threshold}
            onChange={(v) => setField('detection_threshold', v)}
            min={0.2}
            max={0.95}
            step={0.05}
          />
          <NumberField
            label="Min Face Size (px)"
            hint="Ignore faces smaller than this"
            value={form.min_face_size}
            onChange={(v) => setField('min_face_size', v)}
            min={24}
            max={300}
            step={1}
          />
          <NumberField
            label="Min Embedding Samples"
            hint="Frames averaged before decision"
            value={form.min_embedding_samples}
            onChange={(v) => setField('min_embedding_samples', v)}
            min={1}
            max={10}
            step={1}
          />
          <NumberField
            label="Candidate Consistency Ratio"
            hint="Agreement ratio across samples"
            value={form.candidate_consistency_ratio}
            onChange={(v) => setField('candidate_consistency_ratio', v)}
            min={0.3}
            max={1.0}
            step={0.05}
          />
          <NumberField
            label="Recognition Delay (s)"
            hint="Wait time before matching starts"
            value={form.recognition_delay_seconds}
            onChange={(v) => setField('recognition_delay_seconds', v)}
            min={0.0}
            max={10.0}
            step={0.1}
          />
        </div>
      </div>

      {/* Section 2: Liveness & Anti-Spoofing */}
      <div className="space-y-3">
        <h3 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Liveness & Anti-Spoofing (PAD)</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <ToggleField
            label="Require Liveness Check"
            hint="Block static photos and screen replays"
            checked={form.require_liveness}
            onChange={(v) => setField('require_liveness', v)}
          />
          <ToggleField
            label="Require MiniFASNet PAD Model"
            hint="Fail closed if PAD model is unavailable"
            checked={form.pad_required}
            onChange={(v) => setField('pad_required', v)}
          />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <NumberField
            label="PAD Live Threshold"
            hint="Minimum MiniFASNet live probability"
            value={form.pad_threshold}
            onChange={(v) => setField('pad_threshold', v)}
            min={0.1}
            max={0.99}
            step={0.05}
          />
          <NumberField
            label="PAD Smooth Frames"
            hint="Frames smoothed for PAD verdict"
            value={form.pad_smooth_frames}
            onChange={(v) => setField('pad_smooth_frames', v)}
            min={1}
            max={10}
            step={1}
          />
        </div>
      </div>

      {/* Section 3: Door Hardware & Audio */}
      <div className="space-y-3">
        <h3 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Door Hardware & Audio</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 items-start">
          <ToggleField
            label="Enable Door Relay"
            hint="Trigger GPIO relay on access granted"
            checked={form.door_relay_enabled}
            onChange={(v) => setField('door_relay_enabled', v)}
          />
          <ToggleField
            label="Enable Audio Feedback"
            hint="Play access granted/denied voice cues"
            checked={form.audio_enabled}
            onChange={(v) => setField('audio_enabled', v)}
          />
          <NumberField
            label="Door Unlock Duration (s)"
            hint="Relay hold time after unlock"
            value={form.door_unlock_duration_seconds}
            onChange={(v) => setField('door_unlock_duration_seconds', v)}
            min={1.0}
            max={30.0}
            step={0.5}
          />
        </div>
      </div>

      {/* Section 4: Presence & Framing */}
      <div className="space-y-3">
        <h3 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Presence & Camera Framing</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <ToggleField
            label="Presence Auto-Activation"
            hint="Wake recognition when a person dwells in zone"
            checked={form.presence_activation_enabled}
            onChange={(v) => setField('presence_activation_enabled', v)}
          />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <NumberField
            label="Presence Dwell Time (s)"
            value={form.presence_dwell_seconds}
            onChange={(v) => setField('presence_dwell_seconds', v)}
            min={0.5}
            max={10.0}
            step={0.5}
          />
          <NumberField
            label="Activation Cooldown (s)"
            value={form.presence_activation_cooldown_seconds}
            onChange={(v) => setField('presence_activation_cooldown_seconds', v)}
            min={1.0}
            max={30.0}
            step={0.5}
          />
          <NumberField
            label="Min Face Size Ratio"
            hint="Face height / frame height"
            value={form.minimum_face_size_ratio}
            onChange={(v) => setField('minimum_face_size_ratio', v)}
            min={0.05}
            max={0.5}
            step={0.01}
          />
          <NumberField
            label="Max Frontal Yaw (°)"
            value={form.frontal_face_threshold}
            onChange={(v) => setField('frontal_face_threshold', v)}
            min={5.0}
            max={60.0}
            step={1.0}
          />
          <NumberField
            label="Max Frontal Pitch (°)"
            value={form.frontal_pitch_threshold}
            onChange={(v) => setField('frontal_pitch_threshold', v)}
            min={5.0}
            max={45.0}
            step={1.0}
          />
        </div>
      </div>
    </form>
  );
}
