import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext.jsx';
import { AuthProvider } from './context/AuthContext.jsx';
import { ToastProvider } from './context/ToastContext.jsx';
import ProtectedRoute from './components/ProtectedRoute.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import HomePage from './pages/HomePage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import SignupPage from './pages/SignupPage.jsx';
import Dashboard from './pages/Dashboard.jsx';
import StudyPage from './pages/StudyPage.jsx';
import { ForgotPasswordPage, ResetPasswordPage } from './pages/ResetPasswordPage.jsx';
import { ConfigProvider, theme as antTheme } from 'antd';
import { useTheme } from './context/ThemeContext.jsx';

function ThemedApp() {
    const { theme: appTheme } = useTheme();

    return (
        <ConfigProvider
            theme={{
                algorithm: appTheme === 'dark'
                    ? antTheme.darkAlgorithm
                    : antTheme.defaultAlgorithm,
                token: {
                    colorPrimary: '#185FA5',
                    borderRadius: 8,
                    fontFamily: 'inherit',
                },
            }}
        >
            <ToastProvider>
                <Routes>
                    {/* public */}
                    <Route path="/" element={<HomePage />} />
                    <Route path="/login" element={<LoginPage />} />
                    <Route path="/signup" element={<SignupPage />} />
                    <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                    <Route path="/reset-password"  element={<ResetPasswordPage />} />

                    {/* protected */}
                    <Route path="/dashboard" element={
                        <ProtectedRoute>
                            <Dashboard />
                        </ProtectedRoute>
                    } />
                    <Route path="/study/:sessionId" element={
                        <ProtectedRoute>
                            <StudyPage />
                        </ProtectedRoute>
                    } />
                </Routes>
            </ToastProvider>
        </ConfigProvider>
    );
}

export default function App() {
    return (
        <ErrorBoundary>
            <BrowserRouter>
                <ThemeProvider>
                    <AuthProvider>
                        <ThemedApp />
                    </AuthProvider>
                </ThemeProvider>
            </BrowserRouter>
        </ErrorBoundary>
    );
}