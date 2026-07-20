import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './context/ToastContext';
import ProtectedRoute from './components/ProtectedRoute';
import HomePage from './pages/HomePage';
import LoginPage from './pages/LoginPage';
import SignupPage from './pages/SignupPage';
import Dashboard from './pages/Dashboard';
import StudyPage from './pages/StudyPage';
import { ConfigProvider, theme as antTheme } from 'antd';
import { useTheme } from './context/ThemeContext';

function ThemedApp() {
    const { theme: appTheme } = useTheme();

    return (
        <ConfigProvider
            theme={{
                algorithm: appTheme === 'dark'
                    ? antTheme.darkAlgorithm
                    : antTheme.defaultAlgorithm,
                token: {
                    colorPrimary: '#7b6ef6',
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
        <BrowserRouter>
            <ThemeProvider>
                <AuthProvider>
                    <ThemedApp />
                </AuthProvider>
            </ThemeProvider>
        </BrowserRouter>
    );
}