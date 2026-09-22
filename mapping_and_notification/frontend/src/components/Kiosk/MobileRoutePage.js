/**
 * @file MobileRoutePage.js
 * @description Dedicated mobile-friendly navigation view for users who scanned
 * the kiosk QR code. Displays the role-filtered route schematic and turn-by-turn guidance.
 */

import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import { KioskMap } from './KioskMap';

export default function MobileRoutePage() {
    const { token } = useParams();
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [navResult, setNavResult] = useState(null);
    const [mapContext, setMapContext] = useState(null);
    const [sessionInfo, setSessionInfo] = useState(null);
    const [activeFloorplanId, setActiveFloorplanId] = useState(null);
    const [remainingSeconds, setRemainingSeconds] = useState(null);

    // ── Fetch session data from backend ──────────────────────────────────────
    useEffect(() => {
        let isMounted = true;

        async function fetchSession() {
            setLoading(true);
            setError(null);

            // Dynamically determine backend host matching the current client hostname
            const backendHost = window.location.hostname || 'localhost';
            const apiBase = `http://${backendHost}:5000`;

            try {
                const res = await axios.get(`${apiBase}/api/kiosk/session/${token}`);
                if (!isMounted) return;

                const { navigation, map_context, session_info } = res.data;
                setNavResult(navigation);
                setMapContext(map_context);
                setSessionInfo(session_info);

                // Auto-select starting floorplan
                const fpIds = Object.keys(map_context || {}).map(Number);
                if (fpIds.length > 0) {
                    const startFpId = navigation?.path?.[0]?.floorplan_id;
                    setActiveFloorplanId(startFpId || fpIds[0]);
                }

                // Initialize remaining time
                if (session_info?.expires_at) {
                    const diff = Math.max(0, Math.floor((new Date(session_info.expires_at).getTime() - Date.now()) / 1000));
                    setRemainingSeconds(diff);
                }
            } catch (err) {
                if (!isMounted) return;
                const msg = err.response?.data?.message || 'Failed to load navigation session. Please scan a new QR code.';
                setError(msg);
            } finally {
                if (isMounted) setLoading(false);
            }
        }

        if (token) {
            fetchSession();
        } else {
            setError('Invalid session token.');
            setLoading(false);
        }

        return () => {
            isMounted = false;
        };
    }, [token]);

    // ── Live Countdown Timer ────────────────────────────────────────────────
    useEffect(() => {
        if (remainingSeconds === null || remainingSeconds <= 0) return;

        const interval = setInterval(() => {
            setRemainingSeconds(prev => {
                if (prev <= 1) {
                    clearInterval(interval);
                    setError('This navigation session has expired. Please calculate a new route on the kiosk.');
                    return 0;
                }
                return prev - 1;
            });
        }, 1000);

        return () => clearInterval(interval);
    }, [remainingSeconds]);

    // Format remaining time (mm:ss)
    const formatRemaining = (seconds) => {
        if (seconds == null || seconds <= 0) return '00:00';
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    };

    // ── Floor order derivation ──────────────────────────────────────────────
    const floorplanOrder = navResult?.path
        ? [...new Set(navResult.path.map(n => n.floorplan_id))]
              .filter(fpId => mapContext && mapContext[fpId])
        : [];

    const activeMapData = (mapContext && activeFloorplanId)
        ? mapContext[activeFloorplanId] || null
        : null;

    const activeRouteHighlight = (navResult?.visualisation?.by_floorplan && activeFloorplanId)
        ? navResult.visualisation.by_floorplan[String(activeFloorplanId)] || null
        : null;

    const icons = { 
        start: '🟢', 
        walk: '⬆️', 
        turn: (action) => action === 'left' ? '↰' : '↱', 
        transition: (action) => action === 'elevator' ? '🛗' : action === 'stairwell' ? '🪜' : '🚪', 
        arrive: '🏁' 
    };

    const colors = { 
        start: 'text-teal-700 font-bold', 
        walk: 'text-slate-700', 
        turn: 'text-amber-700 font-bold', 
        transition: 'text-purple-700 font-bold', 
        arrive: 'text-emerald-700 font-bold' 
    };

    // ── Loading State ───────────────────────────────────────────────────────
    if (loading) {
        return (
            <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6 text-center font-['Outfit']">
                <div className="w-16 h-16 rounded-2xl bg-teal-50 border border-teal-200 flex items-center justify-center text-3xl mb-4 animate-pulse">
                    🧭
                </div>
                <h2 className="text-lg font-bold text-slate-900 mb-1">Loading Campus Route...</h2>
                <p className="text-xs text-slate-500">Retrieving your role-authorised navigation data</p>
            </div>
        );
    }

    // ── Error / Expired State ───────────────────────────────────────────────
    if (error || !navResult) {
        return (
            <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6 text-center font-['Outfit']">
                <div className="w-16 h-16 rounded-2xl bg-amber-50 border border-amber-200 flex items-center justify-center text-3xl mb-4">
                    ⏱️
                </div>
                <h2 className="text-xl font-bold text-slate-900 mb-2">Session Expired or Invalid</h2>
                <p className="text-xs text-slate-600 max-w-sm mb-6 leading-relaxed">
                    {error || 'This mobile navigation session is no longer active. For your privacy and security, QR sessions automatically expire after 15 minutes.'}
                </p>
                <div className="bg-white border border-slate-200 rounded-xl p-4 max-w-sm w-full text-left mb-6 shadow-sm">
                    <p className="text-xs font-semibold text-slate-800 mb-1.5 flex items-center gap-1.5">
                        <span className="text-teal-600">💡</span> How to get a new route:
                    </p>
                    <ol className="text-[11px] text-slate-600 list-decimal list-inside space-y-1">
                        <li>Visit any physical Campus Navigation Kiosk.</li>
                        <li>Select your origin and destination.</li>
                        <li>Scan the fresh QR code on the kiosk screen.</li>
                    </ol>
                </div>
                <Link 
                    to="/kiosk" 
                    className="px-5 py-2.5 bg-teal-600 hover:bg-teal-500 text-white rounded-xl text-xs font-semibold transition-colors no-underline shadow-md cursor-pointer"
                >
                    Go to Kiosk View
                </Link>
            </div>
        );
    }

    const { route_summary, instructions } = navResult;

    return (
        <div className="min-h-screen bg-slate-50 text-slate-800 font-['Outfit'] flex flex-col antialiased">
            {/* Mobile Header Bar */}
            <header className="sticky top-0 z-30 bg-white/95 backdrop-blur-md border-b border-slate-200 px-4 py-3 flex items-center justify-between shadow-xs">
                <div className="flex items-center gap-2">
                    <span className="text-lg text-teal-600">🧭</span>
                    <div>
                        <h1 className="text-sm font-bold text-slate-900 leading-tight">Mobile Walking Guide</h1>
                        <p className="text-[10px] text-slate-500">Campus Interactive Directory</p>
                    </div>
                </div>

                {remainingSeconds != null && (
                    <div className="flex items-center gap-1.5 bg-slate-100 px-2.5 py-1 rounded-full border border-teal-300 text-[11px] font-mono">
                        <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse"></span>
                        <span className="text-teal-800 font-semibold">{formatRemaining(remainingSeconds)}</span>
                    </div>
                )}
            </header>

            {/* Main Content Scroll Area */}
            <main className="flex-1 p-3.5 max-w-lg mx-auto w-full flex flex-col gap-3.5">
                {/* Route Summary Card */}
                <div className="bg-white rounded-2xl p-4 border border-slate-200 shadow-sm flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] font-bold text-teal-700 bg-teal-50 border border-teal-200 px-2 py-0.5 rounded uppercase tracking-wider">Active Route</span>
                            {sessionInfo?.rbac_role && (
                                <span className="text-[9px] font-medium text-slate-600 bg-slate-100 px-2 py-0.5 rounded capitalize">
                                    {sessionInfo.rbac_role}
                                </span>
                            )}
                        </div>
                        {activeMapData && (
                            <span className="text-[10px] font-semibold text-slate-700 bg-slate-100 px-2.5 py-0.5 rounded-full border border-slate-200">
                                {activeMapData.building_name} • Level {activeMapData.floor_level}
                            </span>
                        )}
                    </div>

                    <div className="bg-slate-50 rounded-xl p-3 border border-slate-200 flex flex-col gap-1.5">
                        <div className="flex items-center gap-2 text-xs">
                            <span className="px-1.5 py-0.5 rounded bg-teal-100 text-teal-800 text-[10px] font-bold uppercase tracking-wider shrink-0">Start</span>
                            <span className="font-semibold text-slate-900 truncate">{route_summary?.start_label}</span>
                        </div>
                        <div className="text-slate-400 text-xs pl-2.5 leading-none">↓</div>
                        <div className="flex items-center gap-2 text-xs">
                            <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 text-[10px] font-bold uppercase tracking-wider shrink-0">Destination</span>
                            <span className="font-semibold text-slate-900 truncate">{route_summary?.destination_label}</span>
                        </div>
                    </div>

                    {/* Metrics 3-Col Grid */}
                    <div className="grid grid-cols-3 gap-2">
                        <div className="bg-slate-50 rounded-xl p-2 text-center border border-slate-200">
                            <p className="text-[9px] text-slate-500 uppercase tracking-wider">Distance</p>
                            <p className="text-sm font-bold text-teal-700 mt-0.5">{route_summary?.total_distance_m}m</p>
                        </div>
                        <div className="bg-slate-50 rounded-xl p-2 text-center border border-slate-200">
                            <p className="text-[9px] text-slate-500 uppercase tracking-wider">Est. Time</p>
                            <p className="text-sm font-bold text-teal-700 mt-0.5">{route_summary?.estimated_time_label}</p>
                        </div>
                        <div className="bg-slate-50 rounded-xl p-2 text-center border border-slate-200">
                            <p className="text-[9px] text-slate-500 uppercase tracking-wider">Transitions</p>
                            <p className="text-sm font-bold text-amber-700 mt-0.5">
                                {(route_summary?.floor_transitions || 0) + (route_summary?.building_transitions || 0)}
                            </p>
                        </div>
                    </div>
                </div>

                {/* Multi-Floor Navigation Tabs */}
                {floorplanOrder.length > 1 && (
                    <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
                        {floorplanOrder.map(fpId => {
                            const fpData = mapContext[fpId];
                            const isActive = fpId === activeFloorplanId;
                            return (
                                <button
                                    key={fpId}
                                    onClick={() => setActiveFloorplanId(fpId)}
                                    className={`px-3 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all cursor-pointer border ${
                                        isActive
                                            ? 'bg-teal-600 text-white border-teal-500 shadow-sm'
                                            : 'bg-white text-slate-600 hover:text-slate-900 border-slate-200'
                                    }`}
                                >
                                    {fpData?.building_name || 'Building'} • Level {fpData?.floor_level}
                                </button>
                            );
                        })}
                    </div>
                )}

                {/* Interactive Schematic Route Map */}
                <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm flex flex-col">
                    <div className="px-3.5 py-2 border-b border-slate-200 flex items-center justify-between text-xs bg-slate-50">
                        <span className="font-bold text-slate-800 flex items-center gap-1.5">
                            <span>🗺️</span> Schematic Map
                        </span>
                        <span className="text-[10px] text-slate-500">Pinch or drag to explore</span>
                    </div>

                    <div className="h-72 sm:h-80 w-full relative bg-slate-100">
                        {activeMapData ? (
                            <KioskMap 
                                mapData={activeMapData}
                                routeHighlight={activeRouteHighlight}
                                navResult={navResult}
                            />
                        ) : (
                            <div className="h-full flex items-center justify-center text-slate-500 text-xs">
                                No map visualization available for this floor.
                            </div>
                        )}
                    </div>
                </div>

                {/* Turn-by-Turn Steps List */}
                <div className="bg-white rounded-2xl p-4 border border-slate-200 shadow-sm flex flex-col gap-2.5">
                    <div className="flex items-center justify-between">
                        <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                            <span>🚶</span> Turn-by-Turn Directions
                        </h3>
                        <span className="text-[10px] font-bold text-slate-600 bg-slate-100 px-2 py-0.5 rounded-full border border-slate-200">
                            {instructions?.length || 0} Steps
                        </span>
                    </div>

                    <div className="flex flex-col gap-2 mt-1">
                        {instructions?.map((step, idx) => {
                            const icon = step.type === 'turn' || step.type === 'transition' ? icons[step.type](step.action) : icons[step.type];
                            const colorClass = colors[step.type] || 'text-slate-800';
                            const isActiveFloor = step.floorplan_id === activeFloorplanId;

                            return (
                                <div 
                                    key={idx} 
                                    className={`flex gap-3 items-start p-3 rounded-xl border transition-colors ${
                                        isActiveFloor 
                                            ? 'bg-teal-50/70 border-teal-300 shadow-xs' 
                                            : 'bg-slate-50 border-slate-200'
                                    }`}
                                >
                                    <span className="text-xl mt-0.5 w-6 text-center shrink-0">{icon || '•'}</span>
                                    <div className="flex flex-col min-w-0 flex-1">
                                        <p className={`text-xs font-medium ${colorClass} leading-snug`}>{step.description}</p>
                                        <div className="flex items-center gap-2 mt-1 text-[10px] text-slate-500">
                                            {step.distance_m ? <span className="font-semibold text-slate-700">{step.distance_m}m</span> : null}
                                            {step.building_name && step.floor_level != null ? (
                                                <span className="text-indigo-600">{step.building_name} Floor {step.floor_level}</span>
                                            ) : null}
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Footer Note */}
                <footer className="text-center py-4 text-[10px] text-slate-400">
                    Campus Navigation System • Kiosk Companion View
                </footer>
            </main>
        </div>
    );
}

