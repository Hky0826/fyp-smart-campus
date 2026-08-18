import axios from 'axios';

// When running inside the dashboard (port 8000), use relative reverse-proxy baseURL to satisfy Content Security Policy (connect-src 'self')
const isSameOriginProxy = typeof window !== 'undefined' && (window.location.port === '8000' || window.location.pathname.includes('/static/vite') || window.location.pathname.includes('/dashboard'));

export const authAxios = axios.create({
    baseURL: isSameOriginProxy ? '/api/mapping-notification' : 'http://localhost:5000',
    withCredentials: true
});

// Auto-inject CSRF and session headers on every request
authAxios.interceptors.request.use(config => {
    const currentToken = localStorage.getItem('adminToken') || localStorage.getItem('token') || 'dashboard-admin-session';
    if (currentToken) {
        config.headers['Authorization'] = `Bearer ${currentToken}`;
    }
    
    if (typeof document !== 'undefined') {
        const csrf = document.cookie.split('; ').find(v => v.startsWith('csrf_token='));
        if (csrf) {
            config.headers['X-CSRF-Token'] = decodeURIComponent(csrf.split('=').slice(1).join('='));
        }
    }
    return config;
});