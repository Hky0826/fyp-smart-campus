/**
 * @file useAuth.js
 * @description Authentication hook for the Campus Navigation System admin panel.
 *
 * Manages:
 *  - Admin login / logout state (token, admin name)
 *  - Login form field state and error display
 *  - axios auth interceptors (attaches JWT Bearer header, handles 401/403 globally)
 *  - Cross-tab logout via localStorage `storage` event
 *  - Session expiry timer (auto-logout when JWT exp is reached)
 *  - Initial data pre-fetch on login (roles, floorplans, global nodes)
 *
 * All side effects are cleaned up on unmount to prevent memory leaks.
 */

import { useState, useEffect } from 'react';
import axios from 'axios';
import { authAxios } from '../services/api';

const isCookieAuthenticatedPortal = typeof window !== 'undefined' &&
    (window.location.port === '8000' || window.location.pathname.includes('/static/vite') || window.location.pathname.includes('/dashboard'));
const storedAdminToken = localStorage.getItem('adminToken') || localStorage.getItem('token');

/**
 * @typedef {Object} UseAuthReturn
 * @property {string|null}    token           - The current JWT token or null if not authenticated.
 * @property {string}         adminName       - Display name of the logged-in admin.
 * @property {string}         loginEmail      - Controlled value for the login email input.
 * @property {Function}       setLoginEmail   - Setter for `loginEmail`.
 * @property {string}         loginPassword   - Controlled value for the login password input.
 * @property {Function}       setLoginPassword - Setter for `loginPassword`.
 * @property {string}         loginError      - Error message string to display on login failure.
 * @property {Function}       handleLogin     - Form submit handler for the login form.
 * @property {Function}       handleLogout    - Clears all auth state and localStorage entries.
 */

/**
 * Manages the admin authentication lifecycle.
 *
 * @param {Object} callbacks
 * @param {Function} callbacks.onLoginSuccess - Called after successful login with initial data promise.
 * @param {Function} callbacks.onLogout       - Called on logout to reset app-level state.
 * @returns {UseAuthReturn}
 */
export function useAuth({ onLoginSuccess, onLogout }) {
    const [token, setToken]               = useState(isCookieAuthenticatedPortal ? null : storedAdminToken);
    const [isAuthenticated, setIsAuthenticated] = useState(!isCookieAuthenticatedPortal && Boolean(storedAdminToken?.includes('.')));
    const [adminName, setAdminName]       = useState(localStorage.getItem('adminName') || localStorage.getItem('full_name') || 'System Administrator');
    const [loginEmail, setLoginEmail]     = useState('');
    const [loginPassword, setLoginPassword] = useState('');
    const [loginError, setLoginError]     = useState('');

    /**
     * Clears all authentication state from memory and localStorage.
     * Triggers `onLogout` callback to reset dependent app-level state.
     */
    const handleLogout = async () => {
        if (isCookieAuthenticatedPortal) {
            const csrf = document.cookie.split('; ').find(value => value.startsWith('csrf_token='));
            try {
                await axios.post('/api/auth/logout', {}, {
                    withCredentials: true,
                    headers: csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf.split('=').slice(1).join('=')) } : {},
                });
            } catch (error) {
                if (error.response?.status !== 401) {
                    alert('Sign out could not be confirmed. Please try again.');
                    return;
                }
            }
        }
        setToken(null);
        setIsAuthenticated(false);
        setAdminName('');
        localStorage.removeItem('adminToken');
        localStorage.removeItem('token');
        localStorage.removeItem('adminName');
        setLoginEmail('');
        setLoginPassword('');
        if (onLogout) onLogout();
    };

    useEffect(() => {
        if (isCookieAuthenticatedPortal) {
            axios.get('/api/auth/me', { withCredentials: true }).then(response => {
                setAdminName(response.data.user?.full_name || 'System Administrator');
                setIsAuthenticated(true);
                if (onLoginSuccess) onLoginSuccess();
            }).catch(() => setIsAuthenticated(false));
        }
    }, []);

    // Set up axios request interceptor (attach JWT), response interceptor (auto-logout on 401/403),
    // and cross-tab synchronization via `storage` event.
    useEffect(() => {
        /**
         * Handles the `storage` event to synchronize logout across browser tabs.
         * If the `adminToken` key is removed from another tab, this tab also logs out.
         * @param {StorageEvent} e
         */
        const syncLogout = (e) => {
            if (e.key === 'adminToken' && !e.newValue) handleLogout();
        };
        window.addEventListener('storage', syncLogout);

        // Attach the Bearer token to every outgoing request
        const reqIntercept = authAxios.interceptors.request.use(config => {
            const currentToken = localStorage.getItem('adminToken') || localStorage.getItem('token');
            if (currentToken) config.headers.Authorization = `Bearer ${currentToken}`;
            return config;
        });

        // Response interceptor
        const resIntercept = authAxios.interceptors.response.use(
            response => response,
            error => {
                if (error.response && error.response.status === 401) {
                    handleLogout();
                }
                return Promise.reject(error);
            }
        );

        return () => {
            window.removeEventListener('storage', syncLogout);
            authAxios.interceptors.request.eject(reqIntercept);
            authAxios.interceptors.response.eject(resIntercept);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // On token change: pre-fetch initial data and set up session expiry timer
    useEffect(() => {
        if (token) {
            setIsAuthenticated(true);
            if (onLoginSuccess) onLoginSuccess();

            // Decode JWT payload to determine remaining session time if valid JWT
            if (typeof token === 'string' && token.includes('.')) {
                try {
                    const payload = JSON.parse(atob(token.split('.')[1]));
                    const timeRemainingMs = (payload.exp * 1000) - Date.now();
                    if (timeRemainingMs <= 0) {
                        handleLogout();
                    } else {
                        const autoLogoutTimer = setTimeout(() => {
                            alert('Your session time limit has been reached. You have been securely logged out.');
                            handleLogout();
                        }, timeRemainingMs);
                        return () => clearTimeout(autoLogoutTimer);
                    }
                } catch (error) { handleLogout(); }
            } else {
                handleLogout();
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token]);

    /**
     * Handles the login form submission.
     * Posts credentials to the backend `/api/login` endpoint, stores the JWT in
     * localStorage, and updates token/adminName state on success.
     *
     * @param {React.FormEvent<HTMLFormElement>} e - The form submit event.
     */
    const handleLogin = async (e) => {
        e.preventDefault();
        try {
            const csrf = document.cookie.split('; ').find(value => value.startsWith('csrf_token='));
            const cookieHeaders = csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf.split('=').slice(1).join('=')) } : {};
            const res = isCookieAuthenticatedPortal
                ? await axios.post('/api/auth/login-json', { email: loginEmail, password: loginPassword }, { withCredentials: true, headers: cookieHeaders })
                : await axios.post('http://localhost:5000/api/login', { email: loginEmail, password: loginPassword });
            const issuedToken = isCookieAuthenticatedPortal ? null : res.data.token;
            setToken(issuedToken);
            setIsAuthenticated(true);
            setAdminName(isCookieAuthenticatedPortal ? res.data.full_name : res.data.adminName);
            if (issuedToken) {
                localStorage.setItem('adminToken', issuedToken);
                localStorage.setItem('adminName', res.data.adminName);
            } else if (onLoginSuccess) {
                onLoginSuccess();
            }
            setLoginError('');
        } catch (err) {
            setLoginError(err.response?.data?.detail || err.response?.data?.message || 'Server error.');
        }
    };

    return {
        token,
        isAuthenticated,
        adminName,
        loginEmail,
        setLoginEmail,
        loginPassword,
        setLoginPassword,
        loginError,
        handleLogin,
        handleLogout
    };
}
