/**
 * @file NotificationPanel.jsx
 * @description Notification Hub drawer panel with 2 clean tabs:
 *  - Dispatch: configure route + host/visitor notification test and delivery mode
 *  - Audit Trail: live MySQL notification delivery log with Ethereal sandbox preview links
 */

import { useState } from 'react';
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  ExternalLink,
  History,
  Loader2,
  Mail,
  RefreshCw,
  Send,
  TestTube2,
} from 'lucide-react';
import { isCorridorNode } from '../utils/nodeUtils';
import { formatDateTime } from '../lib/cloudApi';
import { NodeSelector } from './NodeSelector/NodeSelector';

export function NotificationPanel({
  notifPanelOpen,
  navStartId,
  setNavStartId,
  navEndId,
  setNavEndId,
  navRoleId,
  setNavRoleId,
  globalNodes,
  notifUsers,
  notifTargetHostId,
  setNotifTargetHostId,
  notifVisitorId,
  setNotifVisitorId,
  notifEventType,
  setNotifEventType,
  notifMessage,
  setNotifMessage,
  setIsAutoMessage,
  emailDeliveryMode,
  setEmailDeliveryMode,
  handleGenerateRouteAndNotify,
  notifTestLoading,
  notifTestError,
  notifTestResult,
  fetchNotifData,
  notifLogLoading,
  notifLog,
}) {
  const [activeTab, setActiveTab] = useState('dispatch');

  if (!notifPanelOpen) return null;

  const destinationNodes = globalNodes.filter((n) => !isCorridorNode(n));

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 space-y-2.5 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 flex items-center justify-center">
              <Bell className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
              Notification Hub
            </h3>
          </div>
          <button
            type="button"
            onClick={fetchNotifData}
            className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title="Refresh users & delivery logs"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${notifLogLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {/* Sub-tabs */}
        <div className="grid grid-cols-2 p-1 rounded-xl bg-slate-100 dark:bg-slate-950 border border-slate-200 dark:border-slate-800">
          <button
            type="button"
            onClick={() => setActiveTab('dispatch')}
            className={`py-1.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-all ${
              activeTab === 'dispatch'
                ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
                : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            <Send className="w-3 h-3" />
            <span>Dispatch</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('logs')}
            className={`py-1.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-all ${
              activeTab === 'logs'
                ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-xs'
                : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            <History className="w-3 h-3" />
            <span>Audit Trail</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300 tabular-nums">
              {notifLog.length}
            </span>
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
        {activeTab === 'dispatch' ? (
          <>
            <div className="space-y-3">
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                  Start Location
                </label>
                <NodeSelector
                  nodes={destinationNodes}
                  value={navStartId}
                  onChange={setNavStartId}
                  placeholder="Search start location..."
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                  Destination
                </label>
                <NodeSelector
                  nodes={destinationNodes}
                  value={navEndId}
                  onChange={setNavEndId}
                  placeholder="Search destination..."
                />
              </div>

              <div className="pt-2 border-t border-slate-200 dark:border-slate-800 space-y-3">
                <div>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    Event Type
                  </label>
                  <select
                    value={notifEventType}
                    onChange={(e) => setNotifEventType(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    <option value="appointment_routing">Appointment Routing</option>
                    <option value="visitor_arrival">Visitor Arrival</option>
                    <option value="emergency_alert">Emergency Alert</option>
                    <option value="visitor_navigation">Visitor Navigation (Visitor Only)</option>
                  </select>
                </div>

                {notifEventType !== 'visitor_navigation' && (
                  <div>
                    <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                      Target Host
                    </label>
                    <select
                      value={notifTargetHostId}
                      onChange={(e) => setNotifTargetHostId(e.target.value)}
                      className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500 cursor-pointer"
                    >
                      <option value="">-- Select campus host --</option>
                      {notifUsers
                        .filter((u) => {
                          const r = (u.role_name || '').toUpperCase();
                          return r === 'ADMIN' || r === 'STAFF' || r === 'LECTURER';
                        })
                        .sort((a, b) => (a.full_name || '').localeCompare(b.full_name || ''))
                        .map((u) => (
                          <option key={u.user_id} value={u.user_id}>
                            {u.full_name} ({u.role_name || 'Host'})
                          </option>
                        ))}
                    </select>
                  </div>
                )}

                <div>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    Selected Visitor
                  </label>
                  <select
                    value={notifVisitorId}
                    onChange={(e) => {
                      const val = e.target.value;
                      setNotifVisitorId(val);
                      const selectedUser = notifUsers.find(
                        (u) => String(u.user_id) === String(val)
                      );
                      if (selectedUser) {
                        setNavRoleId(String(selectedUser.role_id));
                      }
                    }}
                    className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    <option value="">-- Select visitor / student --</option>
                    {notifUsers
                      .filter((u) => {
                        const r = (u.role_name || '').toUpperCase();
                        return r === 'STUDENT' || r === 'VISITOR' || r === 'GUEST';
                      })
                      .sort((a, b) => (a.full_name || '').localeCompare(b.full_name || ''))
                      .map((u) => (
                        <option key={u.user_id} value={u.user_id}>
                          {u.full_name} ({u.role_name || 'Visitor'})
                        </option>
                      ))}
                  </select>
                </div>

                {notifEventType !== 'visitor_navigation' && (
                  <div>
                    <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                      Host Alert Message
                    </label>
                    <textarea
                      value={notifMessage}
                      onChange={(e) => {
                        setNotifMessage(e.target.value);
                        setIsAutoMessage(false);
                      }}
                      rows={3}
                      placeholder="Message sent to the campus host..."
                      className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500 resize-none"
                    />
                  </div>
                )}

                {/* Email Delivery Mode */}
                <div>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    Email Delivery Mode
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => setEmailDeliveryMode('ethereal')}
                      className={`p-2.5 rounded-xl border text-left transition-all ${
                        emailDeliveryMode === 'ethereal'
                          ? 'border-indigo-500 bg-indigo-50/70 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300'
                          : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-600 dark:text-slate-400'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 text-xs font-bold">
                        <TestTube2 className="w-3.5 h-3.5" />
                        <span>Sandbox</span>
                      </div>
                      <span className="text-[10px] opacity-80 block mt-0.5">Ethereal preview</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setEmailDeliveryMode('smtp')}
                      className={`p-2.5 rounded-xl border text-left transition-all ${
                        emailDeliveryMode === 'smtp'
                          ? 'border-amber-500 bg-amber-50/70 dark:bg-amber-500/15 text-amber-800 dark:text-amber-300'
                          : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-600 dark:text-slate-400'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 text-xs font-bold">
                        <Mail className="w-3.5 h-3.5" />
                        <span>Real SMTP</span>
                      </div>
                      <span className="text-[10px] opacity-80 block mt-0.5">Live inbox delivery</span>
                    </button>
                  </div>
                  {emailDeliveryMode === 'smtp' && (
                    <p className="text-[11px] text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 rounded-lg px-2.5 py-1.5 mt-2">
                      Real SMTP mode will send an actual email to the selected recipient.
                    </p>
                  )}
                </div>
              </div>

              <button
                type="button"
                onClick={handleGenerateRouteAndNotify}
                disabled={
                  notifTestLoading || !navStartId || !navEndId || !navRoleId || !notifVisitorId
                }
                className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-xs font-bold flex items-center justify-center gap-2 transition-colors shadow-xs"
              >
                {notifTestLoading ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Generating &amp; Notifying...</span>
                  </>
                ) : (
                  <>
                    <Send className="w-3.5 h-3.5" />
                    <span>Generate Route &amp; Notify</span>
                  </>
                )}
              </button>
            </div>

            {notifTestError && (
              <div className="rounded-xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/40 p-3 flex items-start gap-2 text-xs text-red-700 dark:text-red-400">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{notifTestError}</span>
              </div>
            )}

            {notifTestResult && (
              <div className="rounded-xl border border-indigo-200 dark:border-indigo-500/30 bg-indigo-50/50 dark:bg-indigo-950/30 p-3.5 space-y-3">
                <div className="flex items-center gap-1.5 text-xs font-bold text-indigo-700 dark:text-indigo-300">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Workflow Dispatched</span>
                </div>
                {notifTestResult.route && (
                  <div className="text-xs text-slate-700 dark:text-slate-300 space-y-1">
                    <p>
                      <span className="text-slate-500">Route:</span>{' '}
                      <strong>{notifTestResult.route.start_node}</strong> →{' '}
                      <strong>{notifTestResult.route.destination_node}</strong>
                    </p>
                    <p className="tabular-nums">
                      <span className="text-slate-500">Metrics:</span>{' '}
                      <strong className="text-teal-600 dark:text-teal-400">
                        {notifTestResult.route.total_distance_m}m
                      </strong>{' '}
                      ({notifTestResult.route.estimated_time_label})
                    </p>
                  </div>
                )}

                {notifTestResult.notification && (
                  <div className="pt-2 border-t border-indigo-200/70 dark:border-indigo-500/20 space-y-2 text-[11px]">
                    {notifTestResult.notification.host && (
                      <div className="rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-2.5">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-slate-800 dark:text-slate-200">
                            Host Notification
                          </span>
                          <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400">
                            {notifTestResult.notification.host.status}
                          </span>
                        </div>
                        <code className="text-[10px] text-slate-500 break-all">
                          {notifTestResult.notification.host.message_id}
                        </code>
                      </div>
                    )}
                    {notifTestResult.notification.visitor && (
                      <div className="rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-2.5">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-slate-800 dark:text-slate-200">
                            Visitor Notification
                          </span>
                          <span
                            className={`text-[10px] font-bold ${
                              notifTestResult.notification.visitor.status === 'FAILED'
                                ? 'text-red-600 dark:text-red-400'
                                : 'text-emerald-600 dark:text-emerald-400'
                            }`}
                          >
                            {notifTestResult.notification.visitor.status}
                          </span>
                        </div>
                        <code className="text-[10px] text-slate-500 break-all">
                          {notifTestResult.notification.visitor.message_id}
                        </code>
                        {notifTestResult.notification.visitor.delivery_error && (
                          <p className="text-[10px] text-red-600 dark:text-red-400 mt-1">
                            {notifTestResult.notification.visitor.delivery_error}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        ) : (
          /* Audit Trail Tab */
          <div className="space-y-2.5">
            {notifLogLoading ? (
              <div className="py-10 text-center text-xs text-slate-400 flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading delivery audit trail...
              </div>
            ) : notifLog.length === 0 ? (
              <div className="py-10 text-center text-xs text-slate-400">
                No notification records found yet.
              </div>
            ) : (
              notifLog.map((log) => {
                const statusStyles = {
                  PENDING:
                    'bg-amber-50 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-500/30',
                  QUEUED:
                    'bg-sky-50 dark:bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-200 dark:border-sky-500/30',
                  SENT: 'bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30',
                  FAILED:
                    'bg-red-50 dark:bg-red-500/15 text-red-700 dark:text-red-400 border-red-200 dark:border-red-500/30',
                };
                const previewUrl = log.body
                  ? log.body.match(/https:\/\/ethereal\.email\/message\/[a-zA-Z0-9.-]+/)?.[0]
                  : null;

                return (
                  <div
                    key={log.notification_id}
                    className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60 p-3 space-y-1.5"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-bold text-slate-800 dark:text-slate-200 truncate">
                        {log.recipient_name || `User #${log.recipient_user_id}`}
                      </span>
                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase shrink-0 ${
                          statusStyles[log.status] ||
                          'bg-slate-100 dark:bg-slate-800 text-slate-500 border-slate-200 dark:border-slate-700'
                        }`}
                      >
                        {log.status}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-600 dark:text-slate-400 leading-relaxed">
                      {log.body ? log.body.split('\n\n')[0] : ''}
                    </p>
                    {log.status === 'FAILED' && log.delivery_error && (
                      <p className="text-[10px] font-semibold text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 rounded-lg px-2 py-1">
                        Error: {log.delivery_error}
                      </p>
                    )}
                    <div className="flex items-center justify-between pt-1.5 border-t border-slate-200/70 dark:border-slate-800/80 text-[10px] text-slate-400">
                      <span>{formatDateTime(log.created_at)}</span>
                      {previewUrl && (
                        <a
                          href={previewUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-indigo-600 dark:text-indigo-400 hover:underline font-bold"
                        >
                          <span>Preview</span>
                          <ExternalLink className="w-2.5 h-2.5" />
                        </a>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
}
