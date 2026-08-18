/**
 * @file Header.js
 * @description Global application header for the admin dashboard.
 *
 * Provides branding, the OpenCV loading status indicator, the admin's name,
 * and the logout functionality.
 */

import React from 'react';

export function Header({ cvLoaded, cvLoadingError, adminName, handleLogout }) {
    return (
        <header className="bg-slate-900/90 backdrop-blur border-b border-slate-800 px-3 py-1.5 flex justify-between items-center shadow-md">
            <div className="flex items-center gap-2">
                <div className="w-6 h-6 bg-blue-600 rounded-md flex items-center justify-center shadow-lg shadow-blue-500/20">
                    <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M9 20l-5.447-2.724A2 2 0 013 15.556V4.444a2 2 0 011.553-1.782l5.447-1.362a2 2 0 011.553 0l5.447 1.362A2 2 0 0119 4.444v11.112a2 2 0 01-1.553 1.782L12 20M9 20l3-1.5M9 20V11m3 7.5v-8" />
                    </svg>
                </div>
                <div>
                    <h1 className="text-xs font-bold tracking-wide bg-gradient-to-r from-blue-400 to-indigo-300 bg-clip-text text-transparent">Zero-Code Map Editor</h1>
                    <p className="text-[8px] text-slate-500 font-medium">Campus Navigation System Panel</p>
                </div>
            </div>
            <div className="flex items-center gap-2">
                {/* OpenCV status pill */}
                <div className="flex items-center gap-1 px-2 py-0.5 bg-slate-950 border border-slate-800 rounded-full text-[9px] font-semibold">
                    {cvLoaded ? (
                        <>
                            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse"></span>
                            <span className="text-emerald-400">OpenCV AI Ready</span>
                        </>
                    ) : cvLoadingError ? (
                        <>
                            <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
                            <span className="text-red-400">CV Loader Error</span>
                        </>
                    ) : (
                        <>
                            <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-bounce"></span>
                            <span className="text-amber-400">Loading CV Core...</span>
                        </>
                    )}
                </div>
                <span className="text-[10px] font-semibold text-slate-300 bg-slate-850 px-2 py-0.5 rounded border border-slate-800">Welcome, {adminName}</span>
                <button onClick={handleLogout} className="px-2 py-1 bg-red-600 hover:bg-red-500 text-white font-bold rounded text-[10px] shadow-lg shadow-red-600/10 hover:shadow-red-600/25 transition-all duration-200 cursor-pointer">Logout</button>
            </div>
        </header>
    );
}
