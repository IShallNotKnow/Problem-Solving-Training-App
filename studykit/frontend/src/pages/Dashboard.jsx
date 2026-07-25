import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { useTheme } from '../context/ThemeContext.jsx';
import { FiPlus, FiBook, FiClock, FiTrash2, FiSun, FiMoon, FiLogOut } from 'react-icons/fi';
import { apiFetch } from '../utils/api.js'
import './Dashboard.css';

function formatRelativeTime(dateStr) {
    if (!dateStr) return '';
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    return new Date(dateStr).toLocaleDateString();
}

export default function Dashboard() {
    const { theme, toggleTheme } = useTheme();
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [deletingId, setDeletingId] = useState(null);
    const [error, setError] = useState(null);
    const navigate = useNavigate();
    const { signOut } = useAuth();
    const creating = useState(false);
    const redirect = '/';

    useEffect(() => {
        fetchSessions();
    }, []);

    const fetchSessions = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await apiFetch('/sessions');
            setSessions(data);
        } catch {
            setError('Could not load your sessions. Check your connection and try again.');
        } finally {
            setLoading(false);
        }
    };

    const handleNewSession = async () => {
        const session = await apiFetch("/sessions", {
            method: "POST",
            body: JSON.stringify({
                label: "Untitled Session",
            }),
        });

        navigate(`/study/${session.session_id}`);
    };

    const handleDelete = async (e, sessionId) => {
        e.stopPropagation();
        setDeletingId(sessionId);
        try {
            await apiFetch(`/sessions/${sessionId}`, { method: 'DELETE' });
            setSessions(prev => prev.filter(s => s.session_id !== sessionId));
        } catch {
            setError('Could not delete session.');
        } finally {
            setDeletingId(null);
        }
    };

    const handleSignOut = async () => {
        try {
            await signOut();
            navigate(redirect);
        } catch (err) {
            console.error(err);
        }
    }

    const getSessionProgress = (session) => {
        const total = session.questions_count || 0;
        const done = session.current_question_index || 0;
        if (total === 0) return null;
        return { done, total, pct: Math.round((done / total) * 100) };
    };

    return (
        <div className="dash-wrap">
            <header className="dash-header">
                <div className="dash-header-inner">
                    <span className="dash-brand">studykit</span>
                    <div className="dash-header-actions">
                        
                        <button
                            className="dash-theme-btn"
                            onClick={toggleTheme}
                            aria-label="Toggle theme"
                        >
                            {theme === 'dark' ? <FiSun size={16} /> : <FiMoon size={16} />}
                        </button>
                        <button
                            className="dash-signout-btn"
                            onClick={handleSignOut}
                            aria-label="Sign out"
                        >
                            <FiLogOut size={15} />
                            Sign out
                        </button>
                        <button
                            className="dash-new-btn"
                            onClick={handleNewSession}
                            disabled={creating}
                        >
                            <FiPlus size={15} />
                            New session
                        </button>
                    </div>
                </div>
            </header>

            <main className="dash-main">
                <div className="dash-intro">
                    <h1 className="dash-title">Your sessions</h1>
                    <p className="dash-sub">Pick up where you left off, or start something new.</p>
                </div>

                {error && (
                    <div className="dash-error">
                        {error}
                        <button onClick={fetchSessions} className="dash-error-retry">Retry</button>
                    </div>
                )}

                {loading ? (
                    <div className="dash-skeleton-grid">
                        {[1, 2, 3].map(i => (
                            <div key={i} className="dash-skeleton-card" />
                        ))}
                    </div>
                ) : sessions.length === 0 ? (
                    <div className="dash-empty">
                        <div className="dash-empty-icon">
                            <FiBook size={32} />
                        </div>
                        <p className="dash-empty-title">No sessions yet</p>
                        <p className="dash-empty-sub">Upload slides or paste notes to generate your first study set.</p>
                        <button className="dash-new-btn" onClick={handleNewSession}>
                            <FiPlus size={15} />
                            Start studying
                        </button>
                    </div>
                ) : (
                    <div className="dash-grid">
                        <button
                            className="dash-card dash-card--new"
                            onClick={handleNewSession}
                            disabled={creating}
                        >
                            <FiPlus size={24} className="dash-card-new-icon" />
                            <span>New session</span>
                        </button>

                        {sessions.map((session) => {
                            const progress = getSessionProgress(session);
                            const isDeleting = deletingId === session.session_id;

                            return (
                                <div
                                    key={session.session_id}
                                    className={`dash-card dash-card--session ${
                                        isDeleting ? "is-deleting" : ""
                                    }`}
                                >
                                    <Link
                                        to={`/study/${session.session_id}`}
                                        className="dash-card-link"
                                        aria-disabled={isDeleting}
                                        onClick={(e) => {
                                            if (isDeleting) {
                                                e.preventDefault();
                                            }
                                        }}
                                    >
                                        <div className="dash-card-top">
                                            <div className="dash-card-icon">
                                                <FiBook size={16} />
                                            </div>
                                        </div>

                                        <div className="dash-card-body">
                                            <p className="dash-card-title">
                                                {session.label || "Untitled session"}
                                            </p>

                                            {progress ? (
                                                <div className="dash-card-progress">
                                                    <div className="dash-progress-bar">
                                                        <div
                                                            className="dash-progress-fill"
                                                            style={{ width: `${progress.pct}%` }}
                                                        />
                                                    </div>

                                                    <span className="dash-progress-label">
                                                        {progress.done}/{progress.total} questions
                                                    </span>
                                                </div>
                                            ) : (
                                                <span className="dash-card-badge">
                                                    Ready to generate
                                                </span>
                                            )}
                                        </div>

                                        <div className="dash-card-footer">
                                            <FiClock size={11} />
                                            <span>
                                                {formatRelativeTime(
                                                    session.last_active_at || session.created_at
                                                )}
                                            </span>
                                        </div>
                                    </Link>

                                    <button
                                        type="button"
                                        className="dash-card-delete"
                                        onClick={(e) => handleDelete(e, session.session_id)}
                                        aria-label="Delete session"
                                        disabled={isDeleting}
                                    >
                                        <FiTrash2 size={14} />
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                )}
            </main>
        </div>
    );
}