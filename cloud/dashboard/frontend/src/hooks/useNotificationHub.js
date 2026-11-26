/**
 * @file useNotificationHub.js
 * @description Notification Hub hook integrated with cloudApi and ToastProvider.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { cloudApi } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { MAPPING_API_BASE } from '../constants/mapConstants';

export function useNotificationHub({
  isAuthenticated,
  navStartId,
  navEndId,
  navRoleId,
  globalNodes,
  currentFloorplanId,
  setNavResult,
  setNavHighlight,
}) {
  const toast = useToast();

  const [notifPanelOpen, setNotifPanelOpen] = useState(false);
  const [notifUsers, setNotifUsers] = useState([]);
  const [notifTargetHostId, setNotifTargetHostId] = useState('');
  const [notifMessage, setNotifMessage] = useState('');
  const [notifEventType, setNotifEventType] = useState('appointment_routing');
  const [notifVisitorId, setNotifVisitorId] = useState('');
  const [notifVisitorEmail, setNotifVisitorEmail] = useState('');
  const [isAutoMessage, setIsAutoMessage] = useState(true);
  const [notifTestResult, setNotifTestResult] = useState(null);
  const [notifTestLoading, setNotifTestLoading] = useState(false);
  const [notifTestError, setNotifTestError] = useState('');
  const [notifLog, setNotifLog] = useState([]);
  const [notifLogLoading, setNotifLogLoading] = useState(false);
  const [emailDeliveryMode, setEmailDeliveryMode] = useState('ethereal');
  const pollTimerRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  const fetchNotifData = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const usersData = await cloudApi.get(`${MAPPING_API_BASE}/api/notification-users`);
      setNotifUsers(Array.isArray(usersData) ? usersData : []);

      setNotifLogLoading(true);
      const logData = await cloudApi.get(`${MAPPING_API_BASE}/api/notifications`);
      setNotifLog(Array.isArray(logData) ? logData : []);
    } catch (err) {
      console.error('Failed to load Notification Hub data:', err);
    } finally {
      setNotifLogLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (notifPanelOpen && isAuthenticated) {
      fetchNotifData();
    }
  }, [notifPanelOpen, isAuthenticated, fetchNotifData]);

  useEffect(() => {
    if (isAutoMessage) {
      if (notifVisitorId && navStartId && navEndId) {
        const visitorUser = notifUsers.find((u) => String(u.user_id) === String(notifVisitorId));
        const visitorName = visitorUser ? visitorUser.full_name : notifVisitorId || 'Visitor';

        const startNodeObj = globalNodes.find((n) => String(n.node_id) === String(navStartId));
        const startLabel = startNodeObj ? startNodeObj.room_label || `Node ${startNodeObj.node_id}` : '';

        const endNodeObj = globalNodes.find((n) => String(n.node_id) === String(navEndId));
        const endLabel = endNodeObj ? endNodeObj.room_label || `Node ${endNodeObj.node_id}` : '';

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

  const handleGenerateRouteAndNotify = async () => {
    if (!notifVisitorId) {
      toast.error('Please select a visitor before generating route.');
      return;
    }
    if (!navStartId || !navEndId || !navRoleId) {
      toast.error('Please fill in Start Node, Destination Node, and User Role.');
      return;
    }
    if (notifTargetHostId && !notifMessage) {
      toast.error('Please provide an alert message for the host notification.');
      return;
    }

    setNotifTestLoading(true);
    setNotifTestError('');
    setNotifTestResult(null);
    setNavHighlight(null);
    setNavResult(null);

    try {
      const payload = {
        current_location: navStartId,
        destination_node: navEndId,
        rbac_role: navRoleId,
        user_id: notifVisitorId,
        event_type: notifEventType,
        email_delivery_mode: emailDeliveryMode,
      };

      if (notifTargetHostId && notifEventType !== 'visitor_navigation') {
        payload.notification_trigger = {
          target_host_id: Number(notifTargetHostId),
          alert_message: notifMessage || 'Visitor navigation notification.',
        };
      }

      const data = await cloudApi.post(`${MAPPING_API_BASE}/api/navigate/admin-test`, payload);
      setNotifTestResult(data);
      setNavResult(data);
      toast.success('Route calculated and notification dispatched.');

      if (data?.visualisation?.by_floorplan && currentFloorplanId) {
        const fpData = data.visualisation.by_floorplan[String(currentFloorplanId)];
        setNavHighlight(fpData || null);
      }

      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
      pollTimerRef.current = setTimeout(async () => {
        pollTimerRef.current = null;
        try {
          const logData = await cloudApi.get(`${MAPPING_API_BASE}/api/notifications`);
          setNotifLog(Array.isArray(logData) ? logData : []);
        } catch {
          // ignore transient poll error
        }
      }, 1500);
    } catch (err) {
      const msg = err?.data?.message || err?.data?.error || err?.message || 'Request failed.';
      setNotifTestError(msg);
      toast.error(msg);
    } finally {
      setNotifTestLoading(false);
    }
  };

  return {
    notifPanelOpen,
    setNotifPanelOpen,
    notifUsers,
    notifTargetHostId,
    setNotifTargetHostId,
    notifMessage,
    setNotifMessage,
    notifEventType,
    setNotifEventType,
    notifVisitorId,
    setNotifVisitorId,
    notifVisitorEmail,
    setNotifVisitorEmail,
    isAutoMessage,
    setIsAutoMessage,
    emailDeliveryMode,
    setEmailDeliveryMode,
    notifTestResult,
    notifTestLoading,
    notifTestError,
    notifLog,
    notifLogLoading,
    fetchNotifData,
    handleGenerateRouteAndNotify,
  };
}
