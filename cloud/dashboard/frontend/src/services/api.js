import axios from 'axios';

// When running inside the dashboard (port 8000), use relative reverse-proxy baseURL to satisfy Content Security Policy (connect-src 'self')
const isSameOriginProxy = typeof window !== 'undefined' && (window.location.port === '8000' || window.location.pathname.includes('/static/vite') || window.location.pathname.includes('/dashboard'));

export const authAxios = axios.create({
    baseURL: isSameOriginProxy ? '/api/mapping-notification' : 'http://localhost:5000'
});