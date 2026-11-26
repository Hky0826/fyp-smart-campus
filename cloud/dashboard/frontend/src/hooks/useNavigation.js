/**
 * @file useNavigation.js
 * @description Navigation tester hook integrated with cloudApi.
 */

import { useState, useEffect } from 'react';
import { cloudApi } from '../lib/cloudApi';
import { MAPPING_API_BASE } from '../constants/mapConstants';

export function useNavigation({ currentFloorplanId }) {
  const [navPanelOpen, setNavPanelOpen] = useState(false);
  const [navStartId, setNavStartId] = useState('');
  const [navEndId, setNavEndId] = useState('');
  const [navRoleId, setNavRoleId] = useState('');
  const [navResult, setNavResult] = useState(null);
  const [navLoading, setNavLoading] = useState(false);
  const [navError, setNavError] = useState('');
  const [navHighlight, setNavHighlight] = useState(null);

  useEffect(() => {
    if (navResult?.visualisation?.by_floorplan && currentFloorplanId) {
      const fpData = navResult.visualisation.by_floorplan[String(currentFloorplanId)];
      setNavHighlight(fpData || null);
    } else {
      setNavHighlight(null);
    }
  }, [currentFloorplanId, navResult]);

  const handleRunNavigation = async () => {
    setNavLoading(true);
    setNavError('');
    setNavResult(null);
    setNavHighlight(null);
    try {
      const data = await cloudApi.post(`${MAPPING_API_BASE}/api/navigate/admin-test`, {
        current_location: navStartId,
        destination_node: navEndId,
        rbac_role: navRoleId,
      });
      setNavResult(data);

      if (data?.visualisation?.by_floorplan && currentFloorplanId) {
        const fpData = data.visualisation.by_floorplan[String(currentFloorplanId)];
        setNavHighlight(fpData || null);
      }
    } catch (err) {
      const msg = err?.data?.message || err?.data?.error || err?.message || 'Navigation request failed.';
      setNavError(msg);
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
    navPanelOpen,
    setNavPanelOpen,
    navStartId,
    setNavStartId,
    navEndId,
    setNavEndId,
    navRoleId,
    setNavRoleId,
    navResult,
    setNavResult,
    navLoading,
    navError,
    setNavError,
    navHighlight,
    setNavHighlight,
    handleRunNavigation,
    clearNavigation,
  };
}
