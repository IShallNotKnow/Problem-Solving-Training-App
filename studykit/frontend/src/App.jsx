import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext.jsx';
import { AuthProvider } from './context/AuthContext.jsx';
import { ToastProvider } from './context/ToastContext.jsx';
import ProtectedRoute from './components/ProtectedRoute.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import Footer from './components/Footer.jsx';
import HomePage from './pages/HomePage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import SignupPage from './pages/SignupPage.jsx';
import Dashboard from './pages/Dashboard.jsx';
import StudyPage from './pages/StudyPage.jsx';
import PrivacyPage from './pages/PrivacyPage.jsx';
import TermsPage from './pages/TermsPage.jsx';
import { ForgotPasswordPage, ResetPasswordPage } from './pages/ResetPasswordPage.jsx';
import { useLocation } from 'react-router'
import { ConfigProvider, theme as antTheme } from 'antd';
import { useTheme } from './context/ThemeContext.jsx';

function ThemedApp() {
    const { theme: appTheme } = useTheme();
    const location = useLocation();
    const isStudy = location.pathname.startsWith('/study');

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
                    <Route path="/" element={<HomePage />} />
                    <Route path="/login" element={<LoginPage />} />
                    <Route path="/signup" element={<SignupPage />} />
                    <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                    <Route path="/reset-password" element={<ResetPasswordPage />} />
                    <Route path="/privacy-policy" element={<PrivacyPage />} />
                    <Route path="/terms" element={<TermsPage />} />
                    <Route path="/dashboard" element={
                        <ProtectedRoute><Dashboard /></ProtectedRoute>
                    } />
                    <Route path="/study/:sessionId" element={
                        <ProtectedRoute><StudyPage /></ProtectedRoute>
                    } />
                </Routes>
                {!isStudy && <Footer />}
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