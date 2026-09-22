/**
 * @file useKiosk.js
 * @description State management hook for the Kiosk Navigation View.
 *
 * Manages navigation form state, API calls to the kiosk endpoint,
 * result storage, active floor selection, and global data fetching.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { kioskAxios } from '../services/kioskApi';

export function useKiosk() {
    const [searchParams] = useSearchParams();
    const autoNavTriggeredRef = useRef(false);

    // ── Form State ─────────────────────────────────────────────────────────
    const [startId, setStartId] = useState(() => {
        const s = searchParams.get('start');
        return s ? (Number(s) || s) : '';
    });
    const [endId, setEndId] = useState(() => {
        const e = searchParams.get('end');
        return e ? (Number(e) || e) : '';
    });
    const [roleId, setRoleId] = useState(() => {
        const r = searchParams.get('role');
        return r ? (Number(r) || r) : 4; // Default to Visitor (4)
    });

    // ── Result State ───────────────────────────────────────────────────────
    const [navResult, setNavResult] = useState(null);     // navigation result from API
    const [mapContext, setMapContext] = useState(null);    // map_context from API
    const [qrSession, setQrSession] = useState(null);      // mobile QR session data from API
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    // ── Floor Selection ────────────────────────────────────────────────────
    const [activeFloorplanId, setActiveFloorplanId] = useState(null);

    // ── Global Data (for form dropdowns) ──────────────────────────────────
    const [globalNodes, setGlobalNodes] = useState([]);
    const [rolesList, setRolesList] = useState([]);

    // ── Fetch roles once on mount ─────────────────────────────────────────
    useEffect(() => {
        const fetchRoles = async () => {
            try {
                const rolesRes = await kioskAxios.get('/api/kiosk/roles');
                setRolesList(rolesRes.data || []);
            } catch (err) {
                console.warn('[useKiosk] Failed to fetch roles:', err.message);
            }
        };
        fetchRoles();
    }, []);

    // ── Fetch global nodes filtered by selected role ──────────────────────
    useEffect(() => {
        const fetchNodesForRole = async () => {
            const activeRole = roleId || 4;
            try {
                const nodesRes = await kioskAxios.get(`/api/kiosk/global-nodes?role=${encodeURIComponent(activeRole)}`);
                setGlobalNodes(nodesRes.data || []);
            } catch (err) {
                console.warn('[useKiosk] Failed to fetch role-filtered global nodes:', err.message);
            }
        };
        fetchNodesForRole();
    }, [roleId]);

    // ── Navigate ───────────────────────────────────────────────────────────
    const handleNavigate = useCallback(async (overrideStart, overrideEnd, overrideRole) => {
        const isValidId = (val) => typeof val === 'number' || (typeof val === 'string' && val.trim().length > 0);

        const sId = isValidId(overrideStart) ? overrideStart : startId;
        const eId = isValidId(overrideEnd) ? overrideEnd : endId;
        const rId = (typeof overrideRole === 'string' || typeof overrideRole === 'number') && String(overrideRole).trim().length > 0
            ? overrideRole
            : roleId;

        if (!sId || !eId) return;

        setLoading(true);
        setError('');
        setNavResult(null);
        setMapContext(null);
        setQrSession(null);
        setActiveFloorplanId(null);

        try {
            const res = await kioskAxios.post('/api/kiosk/navigate', {
                current_location: sId,
                destination_node: eId,
                rbac_role: rId || 'visitor'
            });

            const { navigation, map_context, qr_session } = res.data;
            setNavResult(navigation);
            setMapContext(map_context);
            setQrSession(qr_session || null);

            // Auto-select the first floorplan in route order
            const fpIds = Object.keys(map_context).map(Number);
            if (fpIds.length > 0) {
                const startFloorplanId = navigation.path?.[0]?.floorplan_id;
                setActiveFloorplanId(startFloorplanId || fpIds[0]);
            }
        } catch (err) {
            const msg = err.response?.data?.message || err.message || 'Navigation failed.';
            setError(msg);
        } finally {
            setLoading(false);
        }
    }, [startId, endId, roleId]);

    // ── Auto-run if URL query parameters provided ─────────────────────────
    useEffect(() => {
        const s = searchParams.get('start');
        const e = searchParams.get('end');
        const r = searchParams.get('role');
        if (s && e && !autoNavTriggeredRef.current) {
            autoNavTriggeredRef.current = true;
            handleNavigate(Number(s) || s, Number(e) || e, r || '');
        }
    }, [searchParams, handleNavigate]);

    // ── Clear ──────────────────────────────────────────────────────────────
    const clearRoute = useCallback(() => {
        setNavResult(null);
        setMapContext(null);
        setQrSession(null);
        setActiveFloorplanId(null);
        setError('');
    }, []);

    // ── Derived: ordered floorplan list ────────────────────────────────────
    const floorplanOrder = navResult?.path
        ? [...new Set(navResult.path.map(n => n.floorplan_id))]
              .filter(fpId => mapContext && mapContext[fpId])
        : [];

    // ── Derived: active map data ──────────────────────────────────────────
    const activeMapData = (mapContext && activeFloorplanId)
        ? mapContext[activeFloorplanId] || null
        : null;

    // ── Derived: active route highlight ───────────────────────────────────
    const activeRouteHighlight = (navResult?.visualisation?.by_floorplan && activeFloorplanId)
        ? navResult.visualisation.by_floorplan[String(activeFloorplanId)] || null
        : null;

    // ── Derived: has result ──────────────────────────────────────────────
    const hasResult = !!navResult;

    return {
        // Form
        startId, setStartId,
        endId, setEndId,
        roleId, setRoleId,
        // Actions
        handleNavigate, clearRoute,
        // Results
        navResult, mapContext,
        qrSession,
        loading, error,
        hasResult,
        // Floor selection
        activeFloorplanId, setActiveFloorplanId,
        floorplanOrder,
        activeMapData,
        activeRouteHighlight,
        // Global data
        globalNodes, rolesList
    };
}
