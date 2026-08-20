/**
 * @file NotificationPanel.js
 * @description The Notification Hub panel for triggering routing + notifications.
 */

import React from 'react';
import { isCorridorNode } from '../utils/nodeUtils';
import { NodeSelector } from './NodeSelector/NodeSelector';


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

    return (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl flex flex-col gap-3 max-h-[85vh] overflow-y-auto">
            <div className="flex justify-between items-center border-b border-slate-800 pb-2.5">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <span>🔔</span> Notification Hub
                </h3>
            </div>

            {/* Inputs Section */}
            <div className="flex flex-col gap-2.5">
                <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">🧭 Navigation Parameters</h4>
                
                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">🟢 Start Node</label>
                    <NodeSelector
                        nodes={globalNodes.filter(n => !isCorridorNode(n))}
                        value={navStartId}
                        onChange={setNavStartId}
                        placeholder="Search or select start node..."
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">🔴 Destination Node</label>
                    <NodeSelector
                        nodes={globalNodes.filter(n => !isCorridorNode(n))}
                        value={navEndId}
                        onChange={setNavEndId}
                        placeholder="Search or select destination node..."
                    />
                </div>

                <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider border-t border-slate-800/80 pt-2 mt-1">🔔 Notification Trigger Parameters</h4>

                {notifEventType !== 'visitor_navigation' && (
                    <div className="flex flex-col gap-1">
                        <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">👤 Target Host</label>
                        <select
                            value={notifTargetHostId}
                            onChange={e => setNotifTargetHostId(e.target.value)}
                            className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 w-full cursor-pointer"
                        >
                            <option value="">-- Select host --</option>
                            {notifUsers
                                .filter(u => {
                                    const r = (u.role_name || '').toUpperCase();
                                    return r === 'ADMIN' || r === 'STAFF' || r === 'LECTURER';
                                })
                                .sort((a, b) => (a.full_name || '').localeCompare(b.full_name || ''))
                                .map(u => (
                                    <option key={u.user_id} value={u.user_id}>{u.full_name} ({u.role_name || 'Host'})</option>
                            ))}
                        </select>
                    </div>
                )}

                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">👤 Selected Visitor</label>
                    <select
                        value={notifVisitorId}
                        onChange={e => {
                            const val = e.target.value;
                            setNotifVisitorId(val);
                            const selectedUser = notifUsers.find(u => String(u.user_id) === String(val));
                            if (selectedUser) {
                                // Auto-select the matching Pathfinder User Role
                                setNavRoleId(String(selectedUser.role_id));
                            }
                        }}
                        className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 w-full cursor-pointer"
                    >
                        <option value="">-- Select visitor --</option>
                        {notifUsers
                            .filter(u => {
                                const r = (u.role_name || '').toUpperCase();
                                return r === 'STUDENT' || r === 'VISITOR' || r === 'GUEST';
                            })
                            .sort((a, b) => (a.full_name || '').localeCompare(b.full_name || ''))
                            .map(u => (
                                <option key={u.user_id} value={u.user_id}>{u.full_name} ({u.role_name || 'Visitor'})</option>
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
                        <option value="visitor_navigation">Visitor Navigation</option>
                    </select>
                </div>

                {notifEventType !== 'visitor_navigation' && (
                    <div className="flex flex-col gap-1">
                        <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">💬 Custom Alert Message</label>
                        <textarea 
                            value={notifMessage} 
                            onChange={e => { setNotifMessage(e.target.value); setIsAutoMessage(false); }} 
                            rows={3}
                            className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 resize-none"
                            placeholder="Message sent to the campus host..."
                        />
                    </div>
                )}

                {/* Email Delivery Mode */}
                <div className="flex flex-col gap-1">
                    <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">📧 Email Delivery Mode</label>
                    <select
                        value={emailDeliveryMode}
                        onChange={e => setEmailDeliveryMode(e.target.value)}
                        className="bg-slate-950 border border-slate-800 rounded-md p-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-indigo-500 cursor-pointer"
                    >
                        <option value="ethereal">Ethereal Email (Sandbox)</option>
                        <option value="smtp">Real Email Delivery</option>
                    </select>
                    {emailDeliveryMode === 'smtp' && (
                        <p className="text-[9px] text-amber-400 bg-amber-950/40 border border-amber-800/50 rounded px-2 py-1.5 mt-0.5 leading-tight">
                            ⚠️ Real Email Delivery will send an actual email to the selected recipient.
                        </p>
                    )}
                    {emailDeliveryMode === 'ethereal' && (
                        <p className="text-[9px] text-slate-500 leading-tight mt-0.5">
                            Ethereal sandbox — emails are captured and previewed only. No real delivery.
                        </p>
                    )}
                </div>
            </div>

            <button
                onClick={handleGenerateRouteAndNotify}
                disabled={notifTestLoading || !navStartId || !navEndId || !navRoleId || !notifVisitorId}
                className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold rounded-md text-[11px] flex items-center justify-center gap-1.5 cursor-pointer transition-all duration-200 border-0 shadow-lg shadow-indigo-600/10 mt-1"
            >
                {notifTestLoading
                    ? '⏳ Generating & Notifying...'
                    : '🔔 Generate Route & Notify'
                }
            </button>

            {notifTestError && (
                <div className="bg-red-950 border border-red-800 rounded-lg p-2.5 text-[10px] text-red-400">
                    ⚠️ {notifTestError}
                </div>
            )}

            {/* Route & Notification Results */}
            {notifTestResult && (
                <div className="bg-indigo-950/40 border border-indigo-800/50 rounded-lg p-3 flex flex-col gap-2.5">
                    <div>
                        <p className="text-[9px] text-indigo-400 font-bold uppercase tracking-wider mb-0.5">Workflow Completed Successfully</p>
                        {notifTestResult.route && (
                            <div className="text-[10px] text-slate-300">
                                <p>🟢 Start: <strong className="text-white">{notifTestResult.route.start_node}</strong></p>
                                <p>🔴 Destination: <strong className="text-white">{notifTestResult.route.destination_node}</strong></p>
                                <p>📐 Distance: <strong className="text-teal-400">{notifTestResult.route.total_distance_m}m</strong></p>
                                <p>⏱️ Travel Time: <strong className="text-teal-400">{notifTestResult.route.estimated_time_label}</strong></p>
                            </div>
                        )}
                    </div>

                    {notifTestResult.notification && (
                        <div className="border-t border-indigo-800/40 pt-2 text-[10px] flex flex-col gap-2">
                            <p className="text-[9px] text-indigo-400 font-bold uppercase tracking-wider mb-0.5">RabbitMQ Broker Status</p>
                            {notifTestResult.notification.host && (
                                <div className="bg-slate-950/80 p-2 rounded border border-slate-800/40">
                                    <p className="font-semibold text-slate-300">👤 Host Notification</p>
                                    <p>🆔 Message ID: <code className="bg-slate-900 px-1 py-0.5 rounded text-amber-400 text-[9px]">{notifTestResult.notification.host.message_id}</code></p>
                                    <p>📢 Status: <span className="text-emerald-400 font-bold">{notifTestResult.notification.host.status}</span></p>
                                </div>
                            )}
                            {notifTestResult.notification.visitor && (
                                <div className="bg-slate-950/80 p-2 rounded border border-slate-800/40">
                                    <p className="font-semibold text-slate-300">✉️ Visitor Notification</p>
                                    <p>🆔 Message ID: <code className="bg-slate-900 px-1 py-0.5 rounded text-amber-400 text-[9px]">{notifTestResult.notification.visitor.message_id}</code></p>
                                    <p>📢 Status: <span className={notifTestResult.notification.visitor.status === 'FAILED' ? 'text-red-400 font-bold' : 'text-emerald-400 font-bold'}>{notifTestResult.notification.visitor.status}</span></p>
                                    {notifTestResult.notification.visitor.delivery_error && (
                                        <p className="text-red-400 text-[9px] mt-0.5">⚠️ {notifTestResult.notification.visitor.delivery_error}</p>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Audit Trail Logs */}
            <div className="border-t border-slate-800/80 pt-3 flex flex-col gap-2">
                <div className="flex justify-between items-center">
                    <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">🗄️ MySQL Notification Logs</h4>
                    <button
                        onClick={fetchNotifData}
                        className="text-[10px] text-indigo-400 hover:text-indigo-300 font-bold bg-indigo-950 px-2 py-1 rounded-md border border-indigo-800 cursor-pointer"
                    >
                        Refresh
                    </button>
                </div>
                {notifLogLoading ? (
                    <p className="text-[10px] text-slate-500 italic">Loading audit trail...</p>
                ) : notifLog.length === 0 ? (
                    <p className="text-[10px] text-slate-500 italic">No records found in database.</p>
                ) : (
                    <div className="flex flex-col gap-1.5 max-h-[250px] overflow-y-auto">
                        {notifLog.map((log) => {
                            const statusColors = { PENDING: 'bg-amber-950 text-amber-400 border-amber-800', SENT: 'bg-emerald-950 text-emerald-400 border-emerald-800', FAILED: 'bg-red-950 text-red-400 border-red-800' };
                            const previewUrl = log.body ? log.body.match(/https:\/\/ethereal\.email\/message\/[a-zA-Z0-9.-]+/)?.[0] : null;

                            return (
                                <div key={log.notification_id} className="bg-slate-950/60 border border-slate-800 rounded-lg p-2 flex flex-col gap-1">
                                    <div className="flex justify-between items-center">
                                        <span className="text-[10px] font-semibold text-slate-300">{log.recipient_name || `User #${log.recipient_user_id}`}</span>
                                        <span className={`text-[8px] border px-1 py-0.5 rounded font-bold uppercase ${statusColors[log.status] || 'bg-slate-800 text-slate-400'}`}>
                                            {log.status}
                                        </span>
                                    </div>
                                    <p className="text-[10px] text-slate-400 leading-normal">{log.body ? log.body.split('\n\n')[0] : ''}</p>
                                    {log.status === 'FAILED' && log.delivery_error && (
                                        <p className="text-[9px] text-red-400 font-semibold bg-red-950/40 border border-red-900/40 rounded px-1.5 py-0.5 mt-1 self-start">
                                            Reason: {log.delivery_error}
                                        </p>
                                    )}
                                    <div className="flex justify-between items-center text-[8px] text-slate-500 mt-1 border-t border-slate-900 pt-1">
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
        </div>
    );
}
