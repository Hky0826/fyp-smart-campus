/**
 * @file MapManagerCard.jsx
 * @description Left Floorplans Drawer for the Campus Map Studio.
 * Displays grouped Buildings & Floors, Floorplan Metadata Editor, Wall Overlay Settings,
 * and a clean modal for uploading new floorplan images.
 */

import { useMemo, useState } from 'react';
import {
  Building2,
  Eye,
  EyeOff,
  Layers,
  Loader2,
  Plus,
  Search,
  Settings2,
  SlidersHorizontal,
  Trash2,
  Upload,
  X,
} from 'lucide-react';

export function MapManagerCard({
  // Create form
  buildingName,
  setBuildingName,
  floorLevel,
  setFloorLevel,
  scaleRatio,
  setScaleRatio,
  fileInputRef,
  handleImageUpload,
  isUploading,

  // Manage maps
  floorplansList,
  currentFloorplanId,
  loadFloorplanData,
  editBuildingName,
  setEditBuildingName,
  editFloorLevel,
  setEditFloorLevel,
  editScaleRatio,
  setEditScaleRatio,
  handleUpdateFloorplan,
  handleDeleteMap,

  // Wall Overlay
  wallSensitivity,
  setWallSensitivity,
  showWallOverlay,
  setShowWallOverlay,
  fetchWallMask,
  isFetchingWallMask,

  // Modal external control
  uploadModalOpen,
  setUploadModalOpen,
}) {
  const [search, setSearch] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [editExpanded, setEditExpanded] = useState(false);

  // Group floorplans by building name
  const groupedFloorplans = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = floorplansList.filter((fp) => {
      if (!q) return true;
      return (
        (fp.building_name || '').toLowerCase().includes(q) ||
        `floor ${fp.floor_level}`.includes(q) ||
        `f${fp.floor_level}`.includes(q)
      );
    });
    const map = new Map();
    for (const fp of filtered) {
      const b = fp.building_name || 'Unassigned';
      if (!map.has(b)) map.set(b, []);
      map.get(b).push(fp);
    }
    return Array.from(map.entries());
  }, [floorplansList, search]);

  const handleFilePicked = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setSelectedFile(f);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(f));
  };

  const handleUploadSubmit = async (e) => {
    e.preventDefault();
    const ok = await handleImageUpload(selectedFile);
    if (ok) {
      setSelectedFile(null);
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        setPreviewUrl(null);
      }
      setUploadModalOpen(false);
    }
  };

  const closeUploadModal = () => {
    if (isUploading) return;
    setSelectedFile(null);
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }
    setUploadModalOpen(false);
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800">
      {/* Drawer Header */}
      <div className="px-3.5 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <Layers className="w-4 h-4 text-indigo-600 dark:text-indigo-400 shrink-0" />
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-200 truncate">
            Floorplans
          </h2>
          <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 tabular-nums">
            {floorplansList.length}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setUploadModalOpen(true)}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-bold bg-indigo-600 hover:bg-indigo-700 text-white transition-colors shadow-xs"
          title="Upload a new floorplan"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>New</span>
        </button>
      </div>

      {/* Search Floorplans */}
      <div className="p-2.5 border-b border-slate-100 dark:border-slate-800/80 shrink-0">
        <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950">
          <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter buildings or floors..."
            className="flex-1 bg-transparent border-0 outline-none text-xs text-slate-900 dark:text-slate-100 placeholder:text-slate-400"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch('')}
              className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Floorplans List */}
      <div className="flex-1 overflow-y-auto p-2.5 space-y-3 scrollbar-thin">
        {groupedFloorplans.length === 0 ? (
          <div className="text-center py-8 px-3">
            <Building2 className="w-8 h-8 text-slate-300 dark:text-slate-700 mx-auto mb-2" />
            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">
              {search ? 'No matching floorplans' : 'No floorplans yet'}
            </p>
            {!search && (
              <button
                type="button"
                onClick={() => setUploadModalOpen(true)}
                className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-500/25 transition-colors"
              >
                <Upload className="w-3.5 h-3.5" />
                Upload First Floorplan
              </button>
            )}
          </div>
        ) : (
          groupedFloorplans.map(([building, floors]) => (
            <div key={building} className="space-y-1">
              <div className="px-2 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                <Building2 className="w-3 h-3" />
                <span className="truncate">{building}</span>
              </div>
              <div className="space-y-0.5">
                {floors.map((fp) => {
                  const isActive = String(fp.floorplan_id) === String(currentFloorplanId);
                  return (
                    <button
                      key={fp.floorplan_id}
                      type="button"
                      onClick={() => loadFloorplanData(String(fp.floorplan_id))}
                      className={`w-full flex items-center justify-between px-2.5 py-2 rounded-xl text-left text-xs transition-all ${
                        isActive
                          ? 'bg-indigo-50 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 font-bold border border-indigo-200 dark:border-indigo-500/30'
                          : 'text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800/70 font-medium border border-transparent'
                      }`}
                    >
                      <span className="truncate">Floor {fp.floor_level}</span>
                      <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 shrink-0">
                        #{fp.floorplan_id}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Active Floorplan Controls (Metadata & Wall Overlay) */}
      {currentFloorplanId && (
        <div className="border-t border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/50 p-3 space-y-3 shrink-0">
          {/* Wall Overlay Section */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
                <SlidersHorizontal className="w-3 h-3 text-indigo-500" />
                Wall Mask Overlay
              </span>
              <button
                type="button"
                onClick={() => setShowWallOverlay((v) => !v)}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold transition-colors ${
                  showWallOverlay
                    ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300'
                    : 'bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                }`}
              >
                {showWallOverlay ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
                {showWallOverlay ? 'Visible' : 'Hidden'}
              </button>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between items-center text-[11px]">
                <span className="text-slate-500 dark:text-slate-400">Sensitivity</span>
                <span className="font-mono font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1 tabular-nums">
                  {isFetchingWallMask && <Loader2 className="w-3 h-3 animate-spin text-indigo-500" />}
                  {wallSensitivity}
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="255"
                value={wallSensitivity}
                onChange={(e) => setWallSensitivity(parseInt(e.target.value, 10))}
                onMouseUp={() => fetchWallMask(currentFloorplanId, wallSensitivity)}
                onTouchEnd={() => fetchWallMask(currentFloorplanId, wallSensitivity)}
                disabled={!showWallOverlay || isFetchingWallMask}
                className="w-full h-1.5 bg-slate-200 dark:bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-600 disabled:opacity-40"
              />
            </div>
          </div>

          {/* Floorplan Metadata Accordion */}
          <div className="pt-2 border-t border-slate-200 dark:border-slate-800">
            <button
              type="button"
              onClick={() => setEditExpanded((v) => !v)}
              className="w-full flex items-center justify-between text-[11px] font-bold text-slate-600 dark:text-slate-300 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
            >
              <span className="flex items-center gap-1.5">
                <Settings2 className="w-3.5 h-3.5" />
                Floorplan Settings
              </span>
              <span className="text-[10px] text-slate-400">{editExpanded ? 'Hide' : 'Edit'}</span>
            </button>

            {editExpanded && (
              <div className="mt-2.5 space-y-2">
                <div>
                  <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">
                    Building Name
                  </label>
                  <input
                    type="text"
                    value={editBuildingName}
                    onChange={(e) => setEditBuildingName(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">
                      Floor
                    </label>
                    <input
                      type="number"
                      value={editFloorLevel}
                      onChange={(e) => setEditFloorLevel(e.target.value)}
                      className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">
                      Scale (px→m)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      value={editScaleRatio}
                      onChange={(e) => setEditScaleRatio(e.target.value)}
                      className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                </div>
                <div className="flex gap-2 pt-1">
                  <button
                    type="button"
                    onClick={handleUpdateFloorplan}
                    className="flex-1 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold transition-colors"
                  >
                    Update
                  </button>
                  <button
                    type="button"
                    onClick={handleDeleteMap}
                    className="px-2.5 py-1.5 rounded-lg border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/50 text-xs font-bold transition-colors"
                    title="Delete floorplan"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Upload New Floorplan Modal */}
      {uploadModalOpen && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/50 dark:bg-slate-950/75 backdrop-blur-xs p-4"
          onClick={closeUploadModal}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 flex items-center justify-center">
                  <Upload className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                    Upload New Floorplan
                  </h3>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    Register a building floor image for campus routing
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={closeUploadModal}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleUploadSubmit} className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">
                  Building Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Block A, TTS, ASB"
                  value={buildingName}
                  onChange={(e) => setBuildingName(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Floor Level
                  </label>
                  <input
                    type="number"
                    required
                    placeholder="e.g. 1"
                    value={floorLevel}
                    onChange={(e) => setFloorLevel(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Scale (px to m)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    value={scaleRatio}
                    onChange={(e) => setScaleRatio(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1.5">
                  Floorplan Image (PNG / JPEG)
                </label>
                <label className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-indigo-400 dark:hover:border-indigo-500 bg-slate-50/70 dark:bg-slate-950/60 p-4 cursor-pointer transition-colors">
                  {previewUrl ? (
                    <div className="w-full space-y-2 text-center">
                      <img
                        src={previewUrl}
                        alt="Floorplan preview"
                        className="max-h-36 mx-auto rounded-lg object-contain border border-slate-200 dark:border-slate-800"
                      />
                      <p className="text-[11px] font-medium text-slate-600 dark:text-slate-300 truncate">
                        {selectedFile?.name}
                      </p>
                    </div>
                  ) : (
                    <>
                      <Upload className="w-6 h-6 text-slate-400 mb-1.5" />
                      <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                        Click to choose an image file
                      </span>
                      <span className="text-[11px] text-slate-400 mt-0.5">PNG or JPEG</span>
                    </>
                  )}
                  <input
                    type="file"
                    ref={fileInputRef}
                    accept="image/png, image/jpeg"
                    onChange={handleFilePicked}
                    disabled={isUploading}
                    className="hidden"
                  />
                </label>
              </div>

              <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-slate-100 dark:border-slate-800">
                <button
                  type="button"
                  onClick={closeUploadModal}
                  disabled={isUploading}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 dark:text-slate-300 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isUploading || !selectedFile || !buildingName.trim() || floorLevel === ''}
                  className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 flex items-center gap-2 transition-colors"
                >
                  {isUploading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>{isUploading ? 'Uploading...' : 'Upload Floorplan'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
