import { useState, useEffect } from 'react';
import { previewRoute } from '../services/api';

export function useNavigation({ currentFloorplanId }) {
    const [navPanelOpen, setNavPanelOpen] = useState(false);
    const [navStartId, setNavStartId]     = useState('');
    const [navEndId, setNavEndId]         = useState('');
    const [navRoleId, setNavRoleId]       = useState('');
    const [navResult, setNavResult]       = useState(null);
    const [navLoading, setNavLoading]     = useState(false);
    const [navError, setNavError]         = useState('');
    const [navHighlight, setNavHighlight] = useState(null);

    useEffect(() => {
        if (navResult && navResult.visualisation && navResult.visualisation.by_floorplan) {
            const fpData = navResult.visualisation.by_floorplan[String(currentFloorplanId)];
            setNavHighlight(fpData || null);
        } else {
            setNavHighlight(null);
        }
    }, [currentFloorplanId, navResult]);

    const handleRunNavigation = async () => {
        if (!navStartId || !navEndId) {
            setNavError('Please select both Start and Destination nodes.');
            return;
        }
        setNavLoading(true);
        setNavError('');
        setNavResult(null);
        setNavHighlight(null);
        try {
            const res = await previewRoute({
                start_node_id: parseInt(navStartId, 10),
                destination_node_id: parseInt(navEndId, 10),
                rbac_role: navRoleId || undefined
            });
            setNavResult(res);

            if (res.visualisation && res.visualisation.by_floorplan && currentFloorplanId) {
                const fpData = res.visualisation.by_floorplan[String(currentFloorplanId)];
                setNavHighlight(fpData || null);
            }
        } catch (err) {
            setNavError(err.message || 'Navigation request failed.');
        } finally {
            setNavLoading(false);
        }
    };

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
