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
    if (!notifPanelOpen) return null;

    const [logsOpen, setLogsOpen] = React.useState(false);

    if (!notifPanelOpen) return null;

    const startNode = globalNodes.find(n => String(n.node_id) === String(navStartId));
    const endNode = globalNodes.find(n => String(n.node_id) === String(navEndId));

    return (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 shadow-xl flex flex-col gap-2.5 max-h-[85vh] overflow-y-auto">
            <div className="flex justify-between items-center border-b border-slate-800 pb-2">
                <h3 className="text-xs font-bold text-white flex items-center gap-1.5">
                    <span>🔔</span> Notification Hub
                </h3>
            </div>

            <div className="flex flex-col gap-2">
                {/* Route Selection Summary (Synced) */}
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-2 flex flex-col gap-1">
                    <div className="flex justify-between items-center">
                        <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">🧭 Route Points</span>
                        <span className="text-[8px] bg-teal-950 text-teal-400 border border-teal-800 px-1 py-0.5 rounded font-bold uppercase">Synced</span>
                    </div>
                    <div className="flex flex-col gap-0.5 text-[10px]">
                        <p className="text-slate-300">🟢 Start: <strong className="text-white">{startNode ? startNode.room_label : (navStartId ? `Node #${navStartId}` : 'Not selected')}</strong></p>
                        <p className="text-slate-300">🔴 Dest: <strong className="text-white">{endNode ? endNode.room_label : (navEndId ? `Node #${navEndId}` : 'Not selected')}</strong></p>
                    </div>
                </div>

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">👤 Target Host</label>
                    <select
                        value={notifTargetHostId}
                        onChange={e => setNotifTargetHostId(e.target.value)}
                        className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 w-full cursor-pointer"
                    >
                        <option value="">-- Select host --</option>
                        {(notifUsers || [])
                            .sort((a, b) => (a.full_name || a.email || '').localeCompare(b.full_name || b.email || ''))
                            .map(u => (
                                <option key={u.user_id} value={u.user_id}>{u.full_name || u.email} ({u.email || u.role_name || 'User'})</option>
                        ))}
                    </select>
                </div>

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">👤 Selected Visitor</label>
                    <select
                        value={notifVisitorId}
                        onChange={e => {
                            const val = e.target.value;
                            setNotifVisitorId(val);
                            const selectedUser = notifUsers.find(u => String(u.user_id) === String(val));
                            if (selectedUser && selectedUser.role_id && setNavRoleId) {
                                setNavRoleId(String(selectedUser.role_id));
                            }
                        }}
                        className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 w-full cursor-pointer"
                    >
                        <option value="">-- Select visitor --</option>
                        {(notifUsers || [])
                            .sort((a, b) => (a.full_name || a.email || '').localeCompare(b.full_name || b.email || ''))
                            .map(u => (
                                <option key={u.user_id} value={u.user_id}>{u.full_name || u.email} ({u.email || u.role_name || 'Visitor'})</option>
                        ))}
                    </select>
                </div>

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">🏷️ Event Type</label>
                    <select
                        value={notifEventType}
                        onChange={e => setNotifEventType(e.target.value)}
                        className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 cursor-pointer"
                    >
                        <option value="appointment_routing">Appointment Routing</option>
                        <option value="visitor_arrival">Visitor Arrival</option>
                        <option value="emergency_alert">Emergency Alert</option>
                    </select>
                </div>

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">💬 Alert Message</label>
                    <textarea 
                        value={notifMessage} 
                        onChange={e => { setNotifMessage(e.target.value); setIsAutoMessage(false); }} 
                        rows={2}
                        className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 resize-none"
                        placeholder="Message sent to host..."
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">📧 Email Delivery</label>
                    <select
                        value={emailDeliveryMode}
                        onChange={e => setEmailDeliveryMode(e.target.value)}
                        className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 cursor-pointer"
                    >
                        <option value="ethereal">Ethereal Email (Sandbox)</option>
                        <option value="smtp">Real Email Delivery</option>
                    </select>
                </div>
            </div>

            <button
                onClick={handleGenerateRouteAndNotify}
                disabled={notifTestLoading || !navStartId || !navEndId || !notifTargetHostId || !notifMessage || !notifVisitorId}
                className="w-full py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold rounded-md text-[11px] flex items-center justify-center gap-1.5 cursor-pointer transition-all duration-200 border-0 shadow-lg shadow-indigo-600/10"
            >
                {notifTestLoading ? '⏳ Notifying...' : '🔔 Generate Route & Notify'}
            </button>

            {notifTestError && (
                <div className="bg-red-950 border border-red-800 rounded-lg p-2 text-[10px] text-red-400">
                    ⚠️ {notifTestError}
                </div>
            )}

            {notifTestResult && (
                <div className="bg-indigo-950/40 border border-indigo-800/50 rounded-lg p-2.5 flex flex-col gap-2">
                    <p className="text-[9px] text-indigo-400 font-bold uppercase tracking-wider">Workflow Completed</p>
                    {notifTestResult.notification && (
                        <div className="flex flex-col gap-1 text-[10px]">
                            {notifTestResult.notification.host && (
                                <div className="bg-slate-950/80 p-1.5 rounded border border-slate-800/40 flex justify-between items-center">
                                    <span className="text-slate-300 font-semibold">👤 Host:</span>
                                    <span className="text-emerald-400 font-bold">{notifTestResult.notification.host.status}</span>
                                </div>
                            )}
                            {notifTestResult.notification.visitor && (
                                <div className="bg-slate-950/80 p-1.5 rounded border border-slate-800/40 flex justify-between items-center">
                                    <span className="text-slate-300 font-semibold">✉️ Visitor:</span>
                                    <span className={notifTestResult.notification.visitor.status === 'FAILED' ? 'text-red-400 font-bold' : 'text-emerald-400 font-bold'}>{notifTestResult.notification.visitor.status}</span>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Collapsible MySQL Logs */}
            <div className="border-t border-slate-800 pt-2 flex flex-col gap-1.5">
                <div className="flex justify-between items-center">
                    <button
                        type="button"
                        onClick={() => {
                            if (!logsOpen) fetchNotifData();
                            setLogsOpen(!logsOpen);
                        }}
                        className="flex items-center gap-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider bg-transparent border-0 cursor-pointer text-left"
                    >
                        <span>🗄️ Audit Logs</span>
                        <span>{logsOpen ? '▲' : '▼'}</span>
                    </button>
                    {logsOpen && (
                        <button
                            onClick={fetchNotifData}
                            className="text-[9px] text-indigo-400 hover:text-indigo-300 font-bold bg-indigo-950 px-1.5 py-0.5 rounded border border-indigo-800 cursor-pointer"
                        >
                            Refresh
                        </button>
                    )}
                </div>

                {logsOpen && (
                    <div className="mt-1">
                        {notifLogLoading ? (
                            <p className="text-[10px] text-slate-500 italic">Loading audit trail...</p>
                        ) : (notifLog || []).length === 0 ? (
                            <p className="text-[10px] text-slate-500 italic">No records found in database.</p>
                        ) : (
                            <div className="flex flex-col gap-1.5 max-h-[200px] overflow-y-auto">
                                {(notifLog || []).map((log) => {
                                    const statusColors = { PENDING: 'bg-amber-950 text-amber-400 border-amber-800', SENT: 'bg-emerald-950 text-emerald-400 border-emerald-800', FAILED: 'bg-red-950 text-red-400 border-red-800' };
                                    const previewUrl = log.body ? log.body.match(/https:\/\/ethereal\.email\/message\/[a-zA-Z0-9.-]+/)?.[0] : null;

                                    return (
                                        <div key={log.notification_id} className="bg-slate-950/60 border border-slate-800 rounded-lg p-1.5 flex flex-col gap-1">
                                            <div className="flex justify-between items-center">
                                                <span className="text-[10px] font-semibold text-slate-300">{log.recipient_name || `User #${log.recipient_user_id}`}</span>
                                                <span className={`text-[8px] border px-1 py-0.5 rounded font-bold uppercase ${statusColors[log.status] || 'bg-slate-800 text-slate-400'}`}>
                                                    {log.status}
                                                </span>
                                            </div>
                                            <p className="text-[9.5px] text-slate-400 leading-normal">{log.body ? log.body.split('\n\n')[0] : ''}</p>
                                            {log.status === 'FAILED' && log.delivery_error && (
                                                <p className="text-[8.5px] text-red-400 font-semibold bg-red-950/40 border border-red-900/40 rounded px-1 py-0.5 self-start">
                                                    Reason: {log.delivery_error}
                                                </p>
                                            )}
                                            <div className="flex justify-between items-center text-[8px] text-slate-500 border-t border-slate-900 pt-0.5">
                                                <span>{new Date(log.created_at).toLocaleString()}</span>
                                                {previewUrl && (
                                                    <a 
                                                        href={previewUrl} 
                                                        target="_blank" 
                                                        rel="noopener noreferrer" 
                                                        className="text-indigo-400 hover:text-indigo-300 font-bold underline"
                                                    >
                                                        ✉️ Sandbox Preview
                                                    </a>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
