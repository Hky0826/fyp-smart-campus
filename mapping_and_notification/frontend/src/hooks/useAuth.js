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
    const [token, setToken]               = useState(localStorage.getItem('adminToken') || null);
    const [adminName, setAdminName]       = useState(localStorage.getItem('adminName') || '');
    const [loginEmail, setLoginEmail]     = useState('');
    const [loginPassword, setLoginPassword] = useState('');
    const [loginError, setLoginError]     = useState('');

    /**
     * Clears all authentication state from memory and localStorage.
     * Triggers `onLogout` callback to reset dependent app-level state.
     */
    const handleLogout = () => {
        setToken(null);
        setAdminName('');
        localStorage.removeItem('adminToken');
        localStorage.removeItem('adminName');
        setLoginEmail('');
        setLoginPassword('');
        if (onLogout) onLogout();
    };

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
            const currentToken = localStorage.getItem('adminToken');
            if (currentToken) config.headers.Authorization = `Bearer ${currentToken}`;
            return config;
        });

        // Auto-logout if the server returns 401 (expired) or 403 (forbidden)
        const resIntercept = authAxios.interceptors.response.use(
            response => response,
            error => {
                if (error.response && (error.response.status === 401 || error.response.status === 403)) {
                    handleLogout();
                    alert('Session expired or unauthorized. Please log in again.');
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
            if (onLoginSuccess) onLoginSuccess();

            // Decode JWT payload to determine remaining session time
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
            } catch (error) {
                console.error('Failed to decode token.');
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
            const res = await axios.post('http://localhost:5000/api/login', {
                email: loginEmail,
                password: loginPassword
            });
            setToken(res.data.token);
            setAdminName(res.data.adminName);
            localStorage.setItem('adminToken', res.data.token);
            localStorage.setItem('adminName', res.data.adminName);
            setLoginError('');
        } catch (err) {
            setLoginError(err.response?.data?.message || 'Server error.');
        }
    };

    return {
        token,
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
