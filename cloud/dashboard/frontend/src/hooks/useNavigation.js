/**
 * @file useNavigation.js
 * @description Navigation tester hook for the Campus Navigation System admin panel.
 *
 * Manages:
 *  - Navigation panel open/close state
 *  - Navigation form inputs (start node, end node, role)
 *  - API call to the admin navigation test endpoint
 *  - Route result storage and highlighting data extraction
 *  - Route highlight sync when the user switches floorplans
 */

import { useState, useEffect } from 'react';
import { authAxios } from '../services/api';

/**
 * Manages all state and side effects for the Navigation Tester panel.
 *
 * @param {Object} deps
 * @param {string|null} deps.currentFloorplanId - The currently loaded floorplan ID, used to extract highlight data.
 * @returns {Object} Navigation state and handlers.
 */
export function useNavigation({ currentFloorplanId }) {
    const [navPanelOpen, setNavPanelOpen] = useState(false);
    const [navStartId, setNavStartId]     = useState('');
    const [navEndId, setNavEndId]         = useState('');
    const [navRoleId, setNavRoleId]       = useState('');
    const [navResult, setNavResult]       = useState(null);
    const [navLoading, setNavLoading]     = useState(false);
    const [navError, setNavError]         = useState('');
    const [navHighlight, setNavHighlight] = useState(null);

    /**
     * Synchronize route highlight data whenever the user switches the active floorplan.
     * Extracts the node/edge IDs for the currently visible floorplan from `navResult.visualisation`.
     */
    useEffect(() => {
        if (navResult && navResult.visualisation && navResult.visualisation.by_floorplan) {
            const fpData = navResult.visualisation.by_floorplan[String(currentFloorplanId)];
            setNavHighlight(fpData || null);
        } else {
            setNavHighlight(null);
        }
    }, [currentFloorplanId, navResult]);

    /**
     * Calls the backend admin navigation test endpoint.
     * On success, stores the full result object and extracts highlight data
     * for the currently loaded floorplan.
     */
    const handleRunNavigation = async () => {
        setNavLoading(true);
        setNavError('');
        setNavResult(null);
        setNavHighlight(null);
        try {
            const res = await authAxios.post('/api/navigate/admin-test', {
                current_location: navStartId,
                destination_node: navEndId,
                rbac_role:        navRoleId
            });
            setNavResult(res.data);

            // Extract highlight data for the currently loaded floorplan
            if (res.data.visualisation && res.data.visualisation.by_floorplan && currentFloorplanId) {
                const fpData = res.data.visualisation.by_floorplan[String(currentFloorplanId)];
                setNavHighlight(fpData || null);
            }
        } catch (err) {
            const msg = err.response?.data?.message || err.response?.data?.error || 'Navigation request failed.';
            setNavError(msg);
        } finally {
            setNavLoading(false);
        }
    };

    /**
     * Resets all navigation tester state to its default (cleared) values.
     * Called when the user clicks "Clear Route" in the Navigation Panel.
     */
    const clearNavigation = () => {
        setNavResult(null);
        setNavHighlight(null);
        setNavError('');
        setNavStartId('');
        setNavEndId('');
        setNavRoleId('');
    };

    return {
        navPanelOpen, setNavPanelOpen,
        navStartId, setNavStartId,
        navEndId, setNavEndId,
        navRoleId, setNavRoleId,
        navResult, setNavResult,
        navLoading,
        navError, setNavError,
        navHighlight, setNavHighlight,
        handleRunNavigation,
        clearNavigation
    };
}
