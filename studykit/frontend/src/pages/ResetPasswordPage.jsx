import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext.jsx';
import { supabase } from '../utils/supabase.js';
import { FiSun, FiMoon, FiEye, FiEyeOff } from 'react-icons/fi';
import './ResetPasswordPage.css';
import './LoginPage.css'

// ── ForgotPasswordPage ────────────────────────────────────────────────────────
export function ForgotPasswordPage() {
    const { theme, toggleTheme } = useTheme();
    const [email, setEmail]       = useState('');
    const [loading, setLoading]   = useState(false);
    const [sent, setSent]         = useState(false);
    const [error, setError]       = useState(null);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError(null);

        const { error } = await supabase.auth.resetPasswordForEmail(email, {
            redirectTo: `${window.location.origin}/reset-password`,
        });

        // Always show success — don't reveal whether the email exists
        if (error && error.status !== 400) {
            setError('Something went wrong. Please try again.');
        } else {
            setSent(true);
        }

        setLoading(false);
    };

    if (sent) {
        return (
            <div className="login-wrap">
                <div className="login-left">
                    <button
                        className="login-theme-toggle"
                        onClick={toggleTheme}
                        aria-label="Toggle theme"
                    >
                        {theme === 'dark' ? <FiSun size={14} /> : <FiMoon size={14} />}
                    </button>
                    <span className="login-brand">studykit</span>
                    <div>
                        <p className="login-tagline">Check your inbox.</p>
                        <p className="login-sub">
                            A reset link is on its way if that address is registered.
                        </p>
                    </div>
                </div>

                <div className="login-right">
                    <h1 className="login-heading">Email sent</h1>
                    <p className="login-subheading">
                        Click the link in the email to set a new password.
                        It expires in one hour.
                    </p>
                    <p className="reset-resend-note">
                        Didn't receive it?{' '}
                        <button
                            className="reset-link-btn"
                            onClick={() => setSent(false)}
                        >
                            Send again
                        </button>
                    </p>
                    <div className="signup-nudge" style={{ marginTop: 32 }}>
                        <Link to="/login">Back to sign in</Link>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="login-wrap">
            <div className="login-left">
                <button
                    className="login-theme-toggle"
                    onClick={toggleTheme}
                    aria-label="Toggle theme"
                >
                    {theme === 'dark' ? <FiSun size={14} /> : <FiMoon size={14} />}
                </button>
                <span className="login-brand">studykit</span>
                <div>
                    <p className="login-tagline">Forgot your password?</p>
                    <p className="login-sub">
                        Enter your email and we'll send you a reset link.
                    </p>
                </div>
            </div>

            <div className="login-right">
                <h1 className="login-heading">Reset password</h1>
                <p className="login-subheading">
                    We'll email you a secure link to set a new one.
                </p>

                {error && <div className="login-error">{error}</div>}

                <form onSubmit={handleSubmit}>
                    <div className="field">
                        <label htmlFor="email">Email</label>
                        <input
                            id="email"
                            type="email"
                            autoComplete="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            placeholder="you@example.com"
                            required
                        />
                    </div>

                    <button
                        type="submit"
                        className="btn-primary"
                        disabled={loading || !email.trim()}
                    >
                        {loading ? 'Sending…' : 'Send reset link'}
                    </button>
                </form>

                <div className="signup-nudge">
                    Remembered it? <Link to="/login">Sign in</Link>
                </div>
            </div>
        </div>
    );
}


// ── ResetPasswordPage ─────────────────────────────────────────────────────────
export function ResetPasswordPage() {
    const { theme, toggleTheme } = useTheme();
    const navigate = useNavigate();

    const [isRecovery, setIsRecovery]     = useState(false);
    const [invalidToken, setInvalidToken] = useState(false);
    const [password, setPassword]         = useState('');
    const [confirm, setConfirm]           = useState('');
    const [showPw, setShowPw]             = useState(false);
    const [showConfirm, setShowConfirm]   = useState(false);
    const [loading, setLoading]           = useState(false);
    const [error, setError]               = useState(null);
    const [done, setDone]                 = useState(false);

    useEffect(() => {
        // Supabase exchanges the token in the URL hash and fires PASSWORD_RECOVERY
        const { data: { subscription } } = supabase.auth.onAuthStateChange(
            (event) => {
                if (event === 'PASSWORD_RECOVERY') {
                    setIsRecovery(true);
                }
            }
        );

        // If no token arrives within 3 s the link is missing or expired
        const timeout = setTimeout(() => {
            setInvalidToken((prev) => !prev && !isRecovery);
        }, 3000);

        return () => {
            subscription.unsubscribe();
            clearTimeout(timeout);
        };
    }, []);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError(null);

        if (password.length < 6) {
            setError('Password must be at least 6 characters.');
            return;
        }
        if (password !== confirm) {
            setError('Passwords do not match.');
            return;
        }

        setLoading(true);
        const { error } = await supabase.auth.updateUser({ password });
        setLoading(false);

        if (error) {
            setError(error.message || 'Could not update password. The link may have expired.');
            return;
        }

        setDone(true);
        // Sign out so the recovery session doesn't persist as a normal one
        await supabase.auth.signOut();
        setTimeout(() => navigate('/login'), 2500);
    };

    // ── invalid / expired token ───────────────────────────────────────────────
    if (invalidToken) {
        return (
            <div className="login-wrap">
                <div className="login-left">
                    <button className="login-theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
                        {theme === 'dark' ? <FiSun size={14} /> : <FiMoon size={14} />}
                    </button>
                    <span className="login-brand">studykit</span>
                    <div>
                        <p className="login-tagline">Link expired.</p>
                        <p className="login-sub">Reset links are valid for one hour.</p>
                    </div>
                </div>
                <div className="login-right">
                    <h1 className="login-heading">Invalid reset link</h1>
                    <p className="login-subheading">
                        This link has expired or already been used.
                        Request a new one and try again.
                    </p>
                    <Link to="/forgot-password" className="btn-primary reset-block-btn">
                        Request a new link
                    </Link>
                    <div className="signup-nudge">
                        <Link to="/login">Back to sign in</Link>
                    </div>
                </div>
            </div>
        );
    }

    // ── success ───────────────────────────────────────────────────────────────
    if (done) {
        return (
            <div className="login-wrap">
                <div className="login-left">
                    <button className="login-theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
                        {theme === 'dark' ? <FiSun size={14} /> : <FiMoon size={14} />}
                    </button>
                    <span className="login-brand">studykit</span>
                    <div>
                        <p className="login-tagline">All set.</p>
                        <p className="login-sub">Your password has been updated.</p>
                    </div>
                </div>
                <div className="login-right">
                    <h1 className="login-heading">Password updated</h1>
                    <p className="login-subheading">
                        Redirecting you to sign in…
                    </p>
                </div>
            </div>
        );
    }

    // ── loading / waiting for token ───────────────────────────────────────────
    if (!isRecovery) {
        return (
            <div className="login-wrap">
                <div className="login-left">
                    <button className="login-theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
                        {theme === 'dark' ? <FiSun size={14} /> : <FiMoon size={14} />}
                    </button>
                    <span className="login-brand">studykit</span>
                    <div>
                        <p className="login-tagline">One moment.</p>
                        <p className="login-sub">Verifying your reset link.</p>
                    </div>
                </div>
                <div className="login-right">
                    <div className="reset-verifying">
                        <div className="sp-loading">
                            <span /><span /><span />
                        </div>
                        <p className="login-subheading" style={{ marginTop: 16 }}>
                            Verifying link…
                        </p>
                    </div>
                </div>
            </div>
        );
    }

    // ── main form ─────────────────────────────────────────────────────────────
    return (
        <div className="login-wrap">
            <div className="login-left">
                <button
                    className="login-theme-toggle"
                    onClick={toggleTheme}
                    aria-label="Toggle theme"
                >
                    {theme === 'dark' ? <FiSun size={14} /> : <FiMoon size={14} />}
                </button>
                <span className="login-brand">studykit</span>
                <div>
                    <p className="login-tagline">Choose a new password.</p>
                    <p className="login-sub">Make it something you'll remember.</p>
                </div>
            </div>

            <div className="login-right">
                <h1 className="login-heading">New password</h1>
                <p className="login-subheading">
                    At least 6 characters. You'll be signed in after saving.
                </p>

                {error && <div className="login-error">{error}</div>}

                <form onSubmit={handleSubmit}>
                    <div className="field">
                        <label htmlFor="password">New password</label>
                        <div className="reset-pw-wrap">
                            <input
                                id="password"
                                type={showPw ? 'text' : 'password'}
                                autoComplete="new-password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                placeholder="········"
                                required
                            />
                            <button
                                type="button"
                                className="reset-pw-toggle"
                                onClick={() => setShowPw((v) => !v)}
                                aria-label={showPw ? 'Hide password' : 'Show password'}
                            >
                                {showPw ? <FiEyeOff size={14} /> : <FiEye size={14} />}
                            </button>
                        </div>
                    </div>

                    <div className="field">
                        <label htmlFor="confirm">Confirm password</label>
                        <div className="reset-pw-wrap">
                            <input
                                id="confirm"
                                type={showConfirm ? 'text' : 'password'}
                                autoComplete="new-password"
                                value={confirm}
                                onChange={(e) => setConfirm(e.target.value)}
                                placeholder="········"
                                required
                            />
                            <button
                                type="button"
                                className="reset-pw-toggle"
                                onClick={() => setShowConfirm((v) => !v)}
                                aria-label={showConfirm ? 'Hide password' : 'Show password'}
                            >
                                {showConfirm ? <FiEyeOff size={14} /> : <FiEye size={14} />}
                            </button>
                        </div>
                    </div>

                    <button
                        type="submit"
                        className="btn-primary"
                        disabled={loading || !password || !confirm}
                    >
                        {loading ? 'Saving…' : 'Save new password'}
                    </button>
                </form>
            </div>
        </div>
    );
}