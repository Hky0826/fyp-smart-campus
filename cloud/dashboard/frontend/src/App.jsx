import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './providers/ThemeProvider';
import { ToastProvider } from './providers/ToastProvider';
import { AuthProvider, useAuthSession } from './providers/AuthProvider';
import { AppShell } from './components/layout/AppShell';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import { UsersPage } from './pages/UsersPage';
import { UserDetailPage } from './pages/UserDetailPage';
import { FaceIdPage } from './pages/FaceIdPage';
import { RolesPage } from './pages/RolesPage';
import { DevicesPage } from './pages/DevicesPage';
import { DeviceDetailPage } from './pages/DeviceDetailPage';
import { RbacMatrixPage } from './pages/RbacMatrixPage';
import { AccessLogsPage } from './pages/AccessLogsPage';
import { SessionsPage } from './pages/SessionsPage';
import { DocumentsPage } from './pages/DocumentsPage';
import { ChatbotLogsPage } from './pages/ChatbotLogsPage';
import { SpeechConfigPage } from './pages/SpeechConfigPage';
import { AcademicsPage } from './pages/AcademicsPage';
import { AppointmentsPage } from './pages/AppointmentsPage';

const CampusMapPage = lazy(() => import('./pages/CampusMapPage'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
  },
});

function RoleGuard({ moduleName, children }) {
  const { canAccess } = useAuthSession();
  if (!canAccess(moduleName)) {
    return <Navigate to="/dashboard/overview" replace />;
  }
  return children;
}

function AuthenticatedRoutes() {
  const { isAuthenticated, loading } = useAuthSession();

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50 dark:bg-slate-950 text-slate-500">
        <div className="w-9 h-9 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mb-3" />
        <span className="text-sm font-medium">Loading Smart Campus Console...</span>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <Routes>
      <Route path="/dashboard" element={<AppShell />}>
        <Route index element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="overview" element={<OverviewPage />} />

        <Route path="users" element={<RoleGuard moduleName="iam"><UsersPage /></RoleGuard>} />
        <Route path="users/:userId" element={<RoleGuard moduleName="iam"><UserDetailPage /></RoleGuard>} />
        <Route path="face-id" element={<RoleGuard moduleName="iam"><FaceIdPage /></RoleGuard>} />
        <Route path="roles" element={<RoleGuard moduleName="iam"><RolesPage /></RoleGuard>} />

        {/* Legacy path aliases so old bookmarks keep working */}
        <Route path="iam/users" element={<Navigate to="/dashboard/users" replace />} />
        <Route path="iam/roles" element={<Navigate to="/dashboard/roles" replace />} />
        <Route path="iam/facial-recognition" element={<Navigate to="/dashboard/face-id" replace />} />

        <Route path="devices" element={<RoleGuard moduleName="infra"><DevicesPage /></RoleGuard>} />
        <Route path="devices/:deviceId" element={<RoleGuard moduleName="infra"><DeviceDetailPage /></RoleGuard>} />
        <Route path="rbac-matrix" element={<RoleGuard moduleName="infra"><RbacMatrixPage /></RoleGuard>} />
        <Route path="access-logs" element={<RoleGuard moduleName="infra"><AccessLogsPage /></RoleGuard>} />
        <Route path="sessions" element={<RoleGuard moduleName="infra"><SessionsPage /></RoleGuard>} />

        <Route path="infra/devices" element={<Navigate to="/dashboard/devices" replace />} />
        <Route path="infra/auth-logs" element={<Navigate to="/dashboard/access-logs" replace />} />
        <Route path="infra/jwt-sessions" element={<Navigate to="/dashboard/sessions" replace />} />

        <Route path="documents" element={<RoleGuard moduleName="rag"><DocumentsPage /></RoleGuard>} />
        <Route path="chatbot-logs" element={<RoleGuard moduleName="rag"><ChatbotLogsPage /></RoleGuard>} />
        <Route path="speech-config" element={<RoleGuard moduleName="rag"><SpeechConfigPage /></RoleGuard>} />
        <Route path="rag/documents" element={<Navigate to="/dashboard/documents" replace />} />
        <Route path="rag/chatbot-queries" element={<Navigate to="/dashboard/chatbot-logs" replace />} />

        <Route path="academics/*" element={<RoleGuard moduleName="academics"><AcademicsPage /></RoleGuard>} />
        <Route path="appointments" element={<RoleGuard moduleName="academics"><AppointmentsPage /></RoleGuard>} />

        <Route
          path="mapping"
          element={
            <RoleGuard moduleName="mapping">
              <Suspense
                fallback={
                  <div className="h-[calc(100vh-4rem)] flex items-center justify-center text-sm text-slate-500">
                    Loading Campus Map Editor...
                  </div>
                }
              >
                <CampusMapPage />
              </Suspense>
            </RoleGuard>
          }
        />
        <Route path="mapping-notification" element={<Navigate to="/dashboard/mapping" replace />} />

        <Route path="*" element={<Navigate to="/dashboard/overview" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard/overview" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <AuthProvider>
            <BrowserRouter>
              <AuthenticatedRoutes />
            </BrowserRouter>
          </AuthProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
