import { useState, useEffect } from 'react';
import { getNotifications, getRecipients, previewRoute } from '../services/api';

export function useNotificationHub({
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

    const fetchNotifData = async () => {
        try {
            setNotifLogLoading(true);
            const [usersRes, logRes] = await Promise.all([
                getRecipients().catch(() => []),
                getNotifications().catch(() => [])
            ]);
            setNotifUsers(usersRes);
            setNotifLog(logRes);
        } catch (err) {
            console.error('Failed to load Notification Hub data:', err);
        } finally {
            setNotifLogLoading(false);
        }
    };

    useEffect(() => {
        if (notifPanelOpen) {
            fetchNotifData();
        }
    }, [notifPanelOpen]);

    useEffect(() => {
        if (isAutoMessage) {
            if (notifVisitorId && navStartId && navEndId) {
                const visitorUser  = notifUsers.find(u => String(u.user_id) === String(notifVisitorId));
                const visitorName  = visitorUser ? (visitorUser.full_name || visitorUser.email) : (notifVisitorId || 'Visitor');

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

    const handleGenerateRouteAndNotify = async () => {
        if (!notifTargetHostId || !notifVisitorId) {
            alert('Please select both a valid host and visitor before generating route.');
            return;
        }
        if (!navStartId || !navEndId || !navRoleId || !notifMessage) {
            alert('Please fill in both navigation inputs and notification parameters.');
            return;
        }

        setNotifTestLoading(true);
        setNotifTestError('');
        setNotifTestResult(null);
        setNavHighlight(null);
        setNavResult(null);

        try {
            const payload = {
                start_node_id:       parseInt(navStartId, 10),
                destination_node_id: parseInt(navEndId, 10),
                rbac_role:           navRoleId,
                user_id:             parseInt(notifVisitorId, 10),
                event_type:          notifEventType,
                email_delivery_mode: emailDeliveryMode,
                notification_trigger: {
                    target_host_id: Number(notifTargetHostId),
                    alert_message:  notifMessage
                }
            };

            const res = await previewRoute(payload);
            setNotifTestResult(res);
            setNavResult(res);

            if (res.visualisation && res.visualisation.by_floorplan && currentFloorplanId) {
                const fpData = res.visualisation.by_floorplan[String(currentFloorplanId)];
                setNavHighlight(fpData || null);
            }

            setTimeout(async () => {
                try {
                    const logRes = await getNotifications();
                    setNotifLog(logRes);
                } catch (_) {}
            }, 1500);

        } catch (err) {
            setNotifTestError(err.message || 'Request failed.');
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
