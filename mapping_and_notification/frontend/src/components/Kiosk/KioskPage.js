import React from 'react';
import { Link } from 'react-router-dom';
import { useKiosk } from '../../hooks/useKiosk';
import { useAuthContext } from '../../context/AuthContext';
import { KioskMap } from './KioskMap';
import { KioskInfoPanel } from './KioskInfoPanel';
import { KioskFloorTabs } from './KioskFloorTabs';
import { KioskNavigationForm } from './KioskNavigationForm';

export default function KioskPage() {
    const kiosk = useKiosk();
    const auth = useAuthContext();

    return (
        <div className="h-screen w-screen max-h-screen max-w-screen bg-slate-950 flex flex-col font-['Outfit'] overflow-hidden select-none">
            {/* Top Navigation Header */}
            <header className="bg-slate-900 border-b border-slate-800 px-4 py-2.5 flex justify-between items-center z-40 shrink-0 shadow-md">
                <div className="flex items-center gap-3">
                    <h1 className="text-base lg:text-lg font-bold text-white flex items-center gap-2 tracking-tight">
                        <span className="text-teal-400 text-xl">🧭</span> Campus Navigation Kiosk
                    </h1>
                    {kiosk.activeMapData && kiosk.hasResult && (
                        <div className="hidden sm:flex px-3 py-1 bg-slate-800/90 rounded-full border border-teal-500/30 items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-teal-400 shadow-[0_0_8px_rgba(20,184,166,0.8)] animate-pulse"></span>
                            <span className="text-xs font-semibold text-teal-200">
                                {kiosk.activeMapData.building_name} — Level {kiosk.activeMapData.floor_level}
                            </span>
                        </div>
                    )}
                </div>

                <div className="flex items-center gap-2.5">
                    {/* Authenticated User Status Pill */}
                    {auth.adminName && (
                        <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 bg-slate-800/80 rounded-lg border border-slate-700/60 text-xs text-slate-300">
                            <span className="text-slate-400">👤</span>
                            <span className="font-medium text-white">{auth.adminName}</span>
                        </div>
                    )}

                    {/* Admin Dashboard Return Button */}
                    <Link
                        to="/"
                        className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 text-xs font-semibold flex items-center gap-1.5 transition-colors no-underline cursor-pointer"
                        title="Return to Campus Navigation Admin Portal"
                    >
                        <span>⚙️</span>
                        <span className="hidden sm:inline">Admin Dashboard</span>
                    </Link>

                    {/* Logout Button */}
                    <button
                        onClick={auth.handleLogout}
                        className="px-2.5 py-1.5 bg-red-950/40 hover:bg-red-900/60 text-red-300 hover:text-red-100 rounded-lg border border-red-800/60 text-xs font-semibold flex items-center gap-1 transition-colors cursor-pointer"
                        title="Secure Logout"
                    >
                        <span>🚪</span>
                        <span className="hidden sm:inline">Logout</span>
                    </button>
                </div>
            </header>

            {/* Compact Top Navigation Control Ribbon */}
            <KioskNavigationForm 
                startId={kiosk.startId} setStartId={kiosk.setStartId}
                endId={kiosk.endId} setEndId={kiosk.setEndId}
                roleId={kiosk.roleId} setRoleId={kiosk.setRoleId}
                handleNavigate={kiosk.handleNavigate} 
                clearRoute={kiosk.clearRoute}
                loading={kiosk.loading} 
                error={kiosk.error}
                globalNodes={kiosk.globalNodes} 
                rolesList={kiosk.rolesList}
                hasResult={kiosk.hasResult}
            />

            {/* Single Fixed Viewport Main Workspace */}
            <main className="flex-1 min-h-0 w-full overflow-hidden relative flex flex-col bg-slate-950">
                {!kiosk.hasResult ? (
                    <div className="flex-1 flex flex-col items-center justify-center p-6 text-center z-0">
                        <div className="w-20 h-20 mb-4 rounded-2xl bg-teal-900/20 flex items-center justify-center border border-teal-500/20 shadow-[0_0_30px_rgba(20,184,166,0.12)]">
                            <span className="text-4xl">📍</span>
                        </div>
                        <h2 className="text-2xl font-bold text-white mb-2 tracking-wide">Campus Interactive Directory</h2>
                        <p className="text-sm text-slate-400 max-w-md leading-relaxed">
                            Select your starting location and destination from the control ribbon above to generate an optimized, role-permitted route schematic with turn-by-turn walking guidance.
                        </p>
                    </div>
                ) : (
                    <div className="flex-1 min-h-0 w-full grid grid-cols-1 lg:grid-cols-12 overflow-hidden bg-slate-950">
                        {/* Map Section (8 Columns) */}
                        <div className="lg:col-span-8 flex flex-col h-full min-h-0 relative border-r border-slate-800 overflow-hidden">
                            {kiosk.floorplanOrder && kiosk.floorplanOrder.length > 1 && (
                                <KioskFloorTabs 
                                    floorplanOrder={kiosk.floorplanOrder}
                                    activeFloorplanId={kiosk.activeFloorplanId}
                                    setActiveFloorplanId={kiosk.setActiveFloorplanId}
                                    mapContext={kiosk.mapContext}
                                />
                            )}
                            <div className="flex-1 min-h-0 w-full h-full relative bg-[#0f172a] overflow-hidden">
                                {kiosk.activeMapData ? (
                                    <KioskMap 
                                        mapData={kiosk.activeMapData}
                                        routeHighlight={kiosk.activeRouteHighlight}
                                        navResult={kiosk.navResult}
                                    />
                                ) : (
                                    <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">
                                        Loading map visualization...
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Route Summary & Directions Section (4 Columns) */}
                        <div className="lg:col-span-4 flex flex-col h-full min-h-0 bg-slate-900 overflow-hidden border-l border-slate-800/80 shadow-2xl">
                            <KioskInfoPanel 
                                navResult={kiosk.navResult}
                                activeFloorplanId={kiosk.activeFloorplanId}
                                mapContext={kiosk.mapContext}
                                qrSession={kiosk.qrSession}
                            />
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
}
