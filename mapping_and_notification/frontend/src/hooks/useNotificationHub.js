/**
 * @file useNotificationHub.js
 * @description Notification Hub hook for the Campus Navigation System admin panel.
 *
 * Manages:
 *  - Notification panel open/close state
 *  - Notification users dropdown data
 *  - Notification form fields (host, visitor, event type, alert message)
 *  - Automatic alert message generation based on form selections
 *  - Triggering the route + notification workflow via the API
 *  - Fetching and displaying the MySQL notification audit trail
 */

import { useState, useEffect } from 'react';
import { authAxios } from '../services/api';

/**
 * Manages all state and side effects for the Notification Hub panel.
 *
 * @param {Object} deps
 * @param {string|null}   deps.token            - Current JWT token (used to gate API calls).
 * @param {string}        deps.navStartId       - Currently selected start node ID (shared with navigation panel).
 * @param {string}        deps.navEndId         - Currently selected destination node ID (shared with navigation panel).
 * @param {string}        deps.navRoleId        - Currently selected role ID (shared with navigation panel).
 * @param {Array}         deps.globalNodes      - All nodes across all floorplans (for label resolution).
 * @param {string|null}   deps.currentFloorplanId - The current floorplan ID (for highlight extraction).
 * @param {Function}      deps.setNavResult     - Setter to propagate nav result to the canvas highlight layer.
 * @param {Function}      deps.setNavHighlight  - Setter to apply the route highlight on the canvas.
 * @returns {Object} Notification hub state and handlers.
 */
export function useNotificationHub({
    token,
    navStartId,
    navEndId,
    navRoleId,
    globalNodes,
    currentFloorplanId,
    setNavResult,
    setNavHighlight
}) {
    const [notifPanelOpen, setNotifPanelOpen]           = useState(false);
    const [notifUsers, setNotifUsers]                   = useState([]);
    const [notifTargetHostId, setNotifTargetHostId]     = useState('');
    const [notifMessage, setNotifMessage]               = useState('');
    const [notifEventType, setNotifEventType]           = useState('appointment_routing');
    const [notifVisitorId, setNotifVisitorId]           = useState('');
    const [notifVisitorEmail, setNotifVisitorEmail]     = useState('');
    const [isAutoMessage, setIsAutoMessage]             = useState(true);
    const [notifTestResult, setNotifTestResult]         = useState(null);
    const [notifTestLoading, setNotifTestLoading]       = useState(false);
    const [notifTestError, setNotifTestError]           = useState('');
    const [notifLog, setNotifLog]                       = useState([]);
    const [notifLogLoading, setNotifLogLoading]         = useState(false);
    const [emailDeliveryMode, setEmailDeliveryMode]     = useState('ethereal');

    /**
     * Fetches the notification audit log and user list from the API.
     * Called when the notification panel opens and after a test notification is sent.
     */
    const fetchNotifData = async () => {
        if (!token) return;
        try {
            const usersRes = await authAxios.get('/api/notification-users');
            setNotifUsers(usersRes.data);

            setNotifLogLoading(true);
            const logRes = await authAxios.get('/api/notifications');
            setNotifLog(logRes.data);
        } catch (err) {
            console.error('Failed to load Notification Hub data:', err);
        } finally {
            setNotifLogLoading(false);
        }
    };

    // Auto-fetch data when the notification panel is opened
    useEffect(() => {
        if (notifPanelOpen && token) {
            fetchNotifData();
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [notifPanelOpen, token]);

    /**
     * Automatically generates an alert message template based on the selected
     * visitor, nodes, and event type. Only activates when `isAutoMessage` is true.
     * Is disabled (and the message is preserved) once the user manually edits the textarea.
     */
    useEffect(() => {
        if (isAutoMessage) {
            if (notifVisitorId && navStartId && navEndId) {
                const visitorUser  = notifUsers.find(u => String(u.user_id) === String(notifVisitorId));
                const visitorName  = visitorUser ? visitorUser.full_name : (notifVisitorId || 'Visitor');

                const startNodeObj = globalNodes.find(n => String(n.node_id) === String(navStartId));
                const startLabel   = startNodeObj ? (startNodeObj.room_label || `Node ${startNodeObj.node_id}`) : '';

                const endNodeObj   = globalNodes.find(n => String(n.node_id) === String(navEndId));
                const endLabel     = endNodeObj ? (endNodeObj.room_label || `Node ${endNodeObj.node_id}`) : '';

                let generated = '';
                if (notifEventType === 'appointment_routing') {
                    generated = `Your visitor ${visitorName} has arrived at ${startLabel} and is currently navigating to ${endLabel}.`;
                } else if (notifEventType === 'visitor_arrival') {
                    generated = `Your visitor ${visitorName} has successfully arrived at ${endLabel}.`;
                } else if (notifEventType === 'emergency_alert') {
                    generated = `An emergency has been detected involving your visitor ${visitorName} at ${startLabel}. Please take the necessary action immediately.`;
                } else {
                    generated = `Your visitor ${visitorName} has arrived at ${startLabel} and is currently navigating to ${endLabel}.`;
                }
                setNotifMessage(generated);
            } else {
                setNotifMessage('');
            }
        }
    }, [notifVisitorId, notifUsers, notifEventType, navStartId, navEndId, globalNodes, isAutoMessage]);

    useEffect(() => {
        if (notifEventType === 'visitor_navigation') {
            setNotifTargetHostId('');
            setNotifMessage('');
        }
    }, [notifEventType]);

    /**
     * Triggers the full route + notification workflow via the admin test endpoint.
     * On success, updates the canvas highlight and polls the notification log
     * after a 1.5-second delay to allow the consumer worker to process the event.
     */
    const handleGenerateRouteAndNotify = async () => {
        if (!notifVisitorId) {
            alert('Please select a visitor before generating route.');
            return;
        }
        if (!navStartId || !navEndId || !navRoleId) {
            alert('Please fill in the navigation inputs (start, destination, role).');
            return;
        }
        if (notifTargetHostId && !notifMessage) {
            alert('Please provide an alert message for the host notification.');
            return;
        }

        setNotifTestLoading(true);
        setNotifTestError('');
        setNotifTestResult(null);
        setNavHighlight(null);
        setNavResult(null);

        try {
            const payload = {
                current_location:    navStartId,
                destination_node:    navEndId,
                rbac_role:           navRoleId,
                user_id:             notifVisitorId,
                event_type:          notifEventType,
                email_delivery_mode: emailDeliveryMode,
            };

            // Only include host notification trigger when a host is selected and it's not a visitor-only event
            if (notifTargetHostId && notifEventType !== 'visitor_navigation') {
                payload.notification_trigger = {
                    target_host_id: Number(notifTargetHostId),
                    alert_message:  notifMessage || `Visitor navigation notification.`
                };
            }

            const res = await authAxios.post('/api/navigate/admin-test', payload);
            setNotifTestResult(res.data);
            setNavResult(res.data);

            // Update the canvas highlight to show the computed route
            if (res.data.visualisation && res.data.visualisation.by_floorplan && currentFloorplanId) {
                const fpData = res.data.visualisation.by_floorplan[String(currentFloorplanId)];
                setNavHighlight(fpData || null);
            }

            // Poll notification logs after delay to allow consumer processing
            setTimeout(async () => {
                try {
                    const logRes = await authAxios.get('/api/notifications');
                    setNotifLog(logRes.data);
                } catch (_) {}
            }, 1500);

        } catch (err) {
            const msg = err.response?.data?.message || err.response?.data?.error || 'Request failed.';
            setNotifTestError(msg);
        } finally {
            setNotifTestLoading(false);
        }
    };

    return {
        notifPanelOpen, setNotifPanelOpen,
        notifUsers,
        notifTargetHostId, setNotifTargetHostId,
        notifMessage, setNotifMessage,
        notifEventType, setNotifEventType,
        notifVisitorId, setNotifVisitorId,
        notifVisitorEmail, setNotifVisitorEmail,
        isAutoMessage, setIsAutoMessage,
        emailDeliveryMode, setEmailDeliveryMode,
        notifTestResult,
        notifTestLoading,
        notifTestError,
        notifLog,
        notifLogLoading,
        fetchNotifData,
        handleGenerateRouteAndNotify
    };
}
