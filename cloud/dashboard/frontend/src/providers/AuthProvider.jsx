import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { cloudApi, setUnauthorizedHandler } from '../lib/cloudApi';

const AuthContext = createContext({
  admin: null,
  loading: true,
  isAuthenticated: false,
  login: async () => {},
  logout: async () => {},
  canAccess: () => false,
});

export function AuthProvider({ children }) {
  const [admin, setAdmin] = useState(null);
  const [loading, setLoading] = useState(true);

  const clearSession = useCallback(() => {
    setAdmin(null);
    localStorage.removeItem('admin_type');
    localStorage.removeItem('email');
    localStorage.removeItem('full_name');
    localStorage.removeItem('admin_id');
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(clearSession);
    let active = true;
    cloudApi
      .get('/api/auth/me')
      .then((data) => {
        if (!active) return;
        const normalized = {
          admin_id: data.admin_id,
          admin_type: data.admin_type || '',
          email: data.user?.email || data.email || '',
          full_name: data.user?.full_name || data.full_name || 'Admin',
          user_id: data.user_id || data.user?.user_id,
        };
        setAdmin(normalized);
        localStorage.setItem('admin_type', normalized.admin_type);
        localStorage.setItem('email', normalized.email);
        localStorage.setItem('full_name', normalized.full_name);
        localStorage.setItem('admin_id', String(normalized.admin_id || ''));
      })
      .catch(() => {
        if (active) setAdmin(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [clearSession]);

  const login = async (email, password) => {
    const formData = new URLSearchParams();
    formData.append('email', email);
    formData.append('password', password);
    const data = await cloudApi.post('/api/auth/login', formData);
    const normalized = {
      admin_id: data.admin_id,
      admin_type: data.admin_type || '',
      email: data.email || email,
      full_name: data.full_name || 'Admin',
    };
    setAdmin(normalized);
    localStorage.setItem('admin_type', normalized.admin_type);
    localStorage.setItem('email', normalized.email);
    localStorage.setItem('full_name', normalized.full_name);
    localStorage.setItem('admin_id', String(normalized.admin_id || ''));
    return normalized;
  };

  const logout = async () => {
    try {
      await cloudApi.post('/api/auth/logout', {});
    } catch {
      // ignore network error on logout
    }
    clearSession();
  };

  const canAccess = useCallback(
    (moduleName) => {
      if (!admin) return false;
      const role = admin.admin_type;
      if (moduleName === 'overview') return true;
      if (role === 'SUPER_ADMIN') return true;
      if (role === 'CONTENT_ADMIN') return moduleName === 'rag';
      if (role === 'SYSTEM_ADMIN') return ['iam', 'academics'].includes(moduleName);
      return false;
    },
    [admin]
  );

  return (
    <AuthContext.Provider
      value={{
        admin,
        loading,
        isAuthenticated: Boolean(admin),
        login,
        logout,
        canAccess,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuthSession() {
  return useContext(AuthContext);
}
