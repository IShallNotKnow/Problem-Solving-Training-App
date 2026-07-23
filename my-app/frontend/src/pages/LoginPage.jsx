import { useState } from 'react';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { useTheme } from '../context/ThemeContext.jsx';
import './LoginPage.css';
import { supabase } from "../utils/supabase.js";

function LoginPage() {
    const { theme, toggleTheme } = useTheme();
    const { user } = useAuth();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);
    const location = useLocation();
    const navigate = useNavigate();
    const { signIn, signInWithGoogle } = useAuth();

    const params = new URLSearchParams(location.search);
    const redirectPage = params.get('redirect') || '/dashboard';

    const handleLogin = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError(null);

        try {
            await signIn(email, password);
            navigate(redirectPage); // goes to /dashboard or wherever they came from
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleGoogle = async () => {
        try {
            await signInWithGoogle(redirectPage);
        } catch (err) {
            setError(err.message);
        }
    };

    return (
        <div className="login-wrap">
            <div className="login-left">
                <button className="login-theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
                    {theme === 'dark' ? '☀' : '☾'}
                </button>
                <div className="login-brand">studykit</div>
                <div>
                    <div className="login-tagline">Turn your notes into questions worth asking.</div>
                    <div className="login-sub">Upload slides. Generate questions. Actually study.</div>
                </div>
            </div>

            <div className="login-right">
                <h1 className="login-heading">Welcome back</h1>
                <p className="login-subheading">Sign in to your account to continue</p>

                {error && <div className="login-error">{error}</div>}

                <form onSubmit={handleLogin}>
                    <div className="field">
                        <label htmlFor="email">Email</label>
                        <input
                            id="email"
                            type="email"
                            placeholder="you@university.edu"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />
                    </div>
                    <div className="field">
                        <label htmlFor="password">Password</label>
                        <input
                            id="password"
                            type="password"
                            placeholder="••••••••"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                        />
                    </div>
                    <div className="forgot">Forgot password?</div>
                    <button className="btn-primary" type="submit" disabled={loading}>
                        {loading ? 'Signing in...' : 'Sign in'}
                    </button>
                </form>

                <div className="divider">
                    <div className="divider-line" />
                    <span>or</span>
                    <div className="divider-line" />
                </div>

                <button className="btn-secondary" onClick={handleGoogle}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
                        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                    </svg>
                    Continue with Google
                </button>

                <p className="signup-nudge">
                    Don't have an account? <Link to={`/signup?redirect=${encodeURIComponent(redirectPage)}`} className="hp-nav-link">Sign up for free</Link>
                </p>
            </div>
        </div>
    );
}

export default LoginPage;