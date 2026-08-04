const csrfToken = () => document.cookie.split('; ').find((part) => part.startsWith('csrf_token='))?.split('=')[1] || '';

export async function mappingRequest(path, options = {}) {
  const response = await fetch(`/api/mapping-notification${path}`, {
    credentials: 'include',
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken(), ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

export const getFloorplans = () => mappingRequest('/floorplans');
export const getGraph = (id) => mappingRequest(`/floorplans/${id}/graph`);
export const getNotifications = () => mappingRequest('/notifications');
export const getRecipients = () => mappingRequest('/notification-recipients');
export const previewRoute = (request) => mappingRequest('/routes/admin-preview', { method: 'POST', body: JSON.stringify(request) });
export const routeAndNotify = (request) => mappingRequest('/routes-and-notify', { method: 'POST', body: JSON.stringify(request) });
export const calculateRoute = (request) => mappingRequest('/routes', { method: 'POST', body: JSON.stringify(request) });
export const saveGraph = (id, graph) => mappingRequest(`/floorplans/${id}/graph`, { method: 'PUT', body: JSON.stringify(graph) });
export const patchFloorplan = (id, data) => mappingRequest(`/floorplans/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
export const deleteFloorplan = (id) => mappingRequest(`/floorplans/${id}`, { method: 'DELETE' });
export const detectWalls = (id, params) => mappingRequest(`/floorplans/${id}/wall-detection?${new URLSearchParams(params)}`, { method: 'POST' });
export const testNotification = (data) => mappingRequest('/notifications/test', { method: 'POST', body: JSON.stringify(data) });

export const getBuildings = () => mappingRequest('/buildings');
export const createBuilding = (data) => mappingRequest('/buildings', { method: 'POST', body: JSON.stringify(data) });
export const getGlobalNodes = () => mappingRequest('/nodes');

export async function getRoles() {
  const response = await fetch('/api/iam/roles', { credentials: 'include' });
  if (!response.ok) return [];
  const data = await response.json().catch(() => []);
  return Array.isArray(data) ? data : (data.roles || []);
}

export function getFloorplanImageUrl(id) {
  return `/api/mapping-notification/floorplans/${id}/image`;
}

export async function uploadFloorplan({ buildingId, floorLevel, scaleRatio, file }) {
  const form = new FormData();
  form.append('building_id', buildingId);
  form.append('floor_level', floorLevel);
  if (scaleRatio) form.append('scale_ratio', scaleRatio);
  form.append('image', file);
  const response = await fetch('/api/mapping-notification/floorplans', { method: 'POST', body: form, credentials: 'include', headers: { 'X-CSRF-Token': csrfToken() } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Floorplan upload failed');
  return data;
}
