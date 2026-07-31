import React from 'react';
import { isCorridorNode } from '../utils/nodeUtils';
import { NodeSelector } from './NodeSelector';

export function NotificationPanel({
    notifPanelOpen,
    navStartId, setNavStartId,
    navEndId, setNavEndId,
    navRoleId, setNavRoleId,
    globalNodes, rolesList,
    notifUsers,
    notifTargetHostId, setNotifTargetHostId,
    notifVisitorId, setNotifVisitorId,
    notifEventType, setNotifEventType,
    notifMessage, setNotifMessage, setIsAutoMessage,
    emailDeliveryMode, setEmailDeliveryMode,
    handleGenerateRouteAndNotify,
    notifTestLoading, notifTestError, notifTestResult,
    fetchNotifData,
    notifLogLoading, notifLog
}) {
    return (
        <div className="flex flex-col gap-3">
            {/* CARD 1: TEST NOTIFICATION */}
            <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-3 shadow-xl flex flex-col gap-2.5">
                <h3 className="text-[10px] font-bold text-slate-300 uppercase tracking-wider">
                    TEST NOTIFICATION
                </h3>

                <div className="flex flex-col gap-2">
                    <div className="flex flex-col gap-1">
                        <label className="text-[9px] text-slate-400 font-semibold">Recipient</label>
                        <select
                            value={notifVisitorId}
                            onChange={e => {
                                const val = e.target.value;
                                setNotifVisitorId(val);
                                const selectedUser = (notifUsers || []).find(u => String(u.user_id) === String(val));
                                if (selectedUser && selectedUser.role_id && setNavRoleId) {
                                    setNavRoleId(String(selectedUser.role_id));
                                }
                            }}
                            className="bg-slate-950 border border-slate-800 rounded-md px-2 py-1 text-[10px] text-slate-200 focus:outline-none focus:border-indigo-500 w-full cursor-pointer h-7"
                        >
                            <option value="">-- Select Recipient --</option>
                            {(notifUsers || [])
                                .sort((a, b) => (a.full_name || a.email || '').localeCompare(b.full_name || b.email || ''))
                                .map(u => (
                                    <option key={u.user_id} value={u.user_id}>{u.full_name || u.email} ({u.email || u.role_name || 'User'})</option>
                            ))}
                        </select>
                    </div>

                    <div className="flex flex-col gap-1">
                        <label className="text-[9px] text-slate-400 font-semibold">Subject / Event</label>
                        <select
                            value={notifEventType}
                            onChange={e => setNotifEventType(e.target.value)}
                            className="bg-slate-950 border border-slate-800 rounded-md px-2 py-1 text-[10px] text-slate-200 focus:outline-none focus:border-indigo-500 cursor-pointer h-7"
                        >
                            <option value="appointment_routing">Campus route notification</option>
                            <option value="visitor_arrival">Visitor Arrival Alert</option>
                            <option value="emergency_alert">Emergency Campus Broadcast</option>
                        </select>
                    </div>

                    <div className="flex flex-col gap-1">
                        <label className="text-[9px] text-slate-400 font-semibold">Message</label>
                        <textarea 
                            value={notifMessage} 
                            onChange={e => { setNotifMessage(e.target.value); setIsAutoMessage && setIsAutoMessage(false); }} 
                            rows={2}
                            className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[10px] text-slate-200 focus:outline-none focus:border-indigo-500 resize-none"
                            placeholder="A route notification is ready."
                        />
                    </div>

                    <div className="flex flex-col gap-1">
                        <label className="text-[9px] text-slate-400 font-semibold">Email Mode</label>
                        <select
                            value={emailDeliveryMode}
                            onChange={e => setEmailDeliveryMode(e.target.value)}
                            className="bg-slate-950 border border-slate-800 rounded-md px-2 py-1 text-[10px] text-slate-200 focus:outline-none focus:border-indigo-500 cursor-pointer h-7"
                        >
                            <option value="ethereal">Ethereal Email (Sandbox)</option>
                            <option value="smtp">Real Email Delivery</option>
                        </select>
                    </div>
                </div>

                <button
                    onClick={handleGenerateRouteAndNotify}
                    disabled={notifTestLoading || !navStartId || !navEndId || !notifVisitorId}
                    className="w-full py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold rounded-md text-[10px] flex items-center justify-center gap-1.5 cursor-pointer transition-all duration-200 border-0 shadow-lg shadow-indigo-600/10 mt-0.5"
                >
                    {notifTestLoading ? 'Sending Notification...' : 'Send Notification'}
                </button>

                {notifTestError && (
                    <div className="bg-red-950 border border-red-800 rounded-lg p-2 text-[9px] text-red-400">
                        ⚠️ {notifTestError}
                    </div>
                )}
            </div>

            {/* CARD 2: DELIVERY AUDIT LOG */}
            <div className="bg-[#111827] border border-slate-800/80 rounded-xl p-3 shadow-xl flex flex-col gap-2">
                <div className="flex justify-between items-center border-b border-slate-800 pb-1.5">
                    <h3 className="text-[10px] font-bold text-slate-300 uppercase tracking-wider">
                        DELIVERY AUDIT LOG
                    </h3>
                    <button
                        onClick={fetchNotifData}
                        className="text-[9px] text-indigo-400 hover:text-indigo-300 font-bold bg-transparent border-0 cursor-pointer"
                    >
                        Refresh
                    </button>
                </div>

                <div className="mt-0.5">
                    {notifLogLoading ? (
                        <p className="text-[9px] text-slate-500 italic">Loading audit trail...</p>
                    ) : (notifLog || []).length === 0 ? (
                        <p className="text-[9px] text-slate-500 italic">No notification delivery records found.</p>
                    ) : (
                        <div className="flex flex-col gap-1.5 max-h-[220px] overflow-y-auto pr-0.5">
                            {(notifLog || []).map((log) => {
                                const statusColors = { PENDING: 'bg-amber-950 text-amber-400 border-amber-800', SENT: 'bg-emerald-950 text-emerald-400 border-emerald-800', FAILED: 'bg-red-950 text-red-400 border-red-800' };
                                const previewUrl = log.body ? log.body.match(/https:\/\/ethereal\.email\/message\/[a-zA-Z0-9.-]+/)?.[0] : null;

                                return (
                                    <div key={log.notification_id} className="bg-slate-950 border border-slate-800/80 rounded-lg p-2 flex flex-col gap-1">
                                        <div className="flex justify-between items-center">
                                            <span className="text-[9.5px] font-bold text-slate-200 truncate max-w-[130px]">{log.recipient_name || `User #${log.recipient_user_id}`}</span>
                                            <span className={`text-[8px] border px-1 py-0.5 rounded font-bold uppercase ${statusColors[log.status] || 'bg-slate-800 text-slate-400'}`}>
                                                {log.status}
                                            </span>
                                        </div>
                                        <p className="text-[9px] text-slate-400 leading-normal line-clamp-2">{log.body ? log.body.split('\n\n')[0] : ''}</p>
                                        <div className="flex justify-between items-center text-[8px] text-slate-500 border-t border-slate-900/80 pt-1 mt-0.5">
                                            <span>{new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                                            {previewUrl && (
                                                <a 
                                                    href={previewUrl} 
                                                    target="_blank" 
                                                    rel="noopener noreferrer" 
                                                    className="text-teal-400 hover:text-teal-300 font-bold underline"
                                                >
                                                    Preview Link
                                                </a>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
