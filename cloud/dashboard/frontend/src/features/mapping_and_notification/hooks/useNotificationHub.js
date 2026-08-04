import { useState, useEffect } from 'react';
import { getNotifications, getRecipients, routeAndNotify } from '../services/api';

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
    const [notifDataError, setNotifDataError]           = useState('');

    const fetchNotifData = async () => {
        try {
            setNotifLogLoading(true);
            setNotifDataError('');

            const [usersResult, logResult] = await Promise.allSettled([
                getRecipients(),
                getNotifications()
            ]);

            if (usersResult.status === 'fulfilled') {
                setNotifUsers(Array.isArray(usersResult.value) ? usersResult.value : []);
            } else {
                setNotifUsers([]);
                setNotifDataError(usersResult.reason?.message || 'Unable to load notification recipients.');
            }

            if (logResult.status === 'fulfilled') {
                setNotifLog(Array.isArray(logResult.value) ? logResult.value : []);
            }
        } catch (err) {
            console.error('Failed to load Notification Hub data:', err);
            setNotifDataError(err.message || 'Unable to load notification data.');
        } finally {
            setNotifLogLoading(false);
        }
    };

    useEffect(() => {
        fetchNotifData();
    }, []);

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
        if (!notifVisitorId) {
            alert('Please select a valid recipient before sending notification.');
            return;
        }
        if (!navStartId || !navEndId || !notifMessage) {
            alert('Please select start & end navigation nodes on the map and write a message.');
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
                rbac_role:           navRoleId || undefined,
                recipient_user_id:   parseInt(notifVisitorId, 10),
                title:               notifEventType.replaceAll('_', ' '),
                body:                notifMessage,
                event_type:          notifEventType,
                email_delivery_mode: emailDeliveryMode,
            };

            const res = await routeAndNotify(payload);
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
        notifDataError,
        notifLog,
        notifLogLoading,
        fetchNotifData,
        handleGenerateRouteAndNotify
    };
}
