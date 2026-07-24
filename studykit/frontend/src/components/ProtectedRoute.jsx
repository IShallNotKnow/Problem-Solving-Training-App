import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export default function ProtectedRoute({ children }) {
    const { user, loading } = useAuth();
    const location = useLocation();

    if (loading) {
        return (
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100vh',
                background: 'var(--bg)',
            }}>
                <div className="sp-loading">
                    <span /><span /><span />
                </div>
            </div>
        );
    }

    if (!user) {
        // preserve the page they tried to visit so login can redirect back
        return <Navigate to={`/login?redirect=${location.pathname}`} replace />;
    }

    return children;
}