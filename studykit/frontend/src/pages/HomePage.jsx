import { Link } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import './HomePage.css';

function HomePage() {
    const { theme, toggleTheme } = useTheme();
    const { user } = useAuth();

    return (
        <div className="hp">
            <nav className="hp-nav">
                <div className="hp-brand">studykit</div>
                <div className="hp-nav-links">
                    <a href="#how-it-works" className="hp-nav-link">How it works</a>
                    <button className="hp-theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
                        {theme === 'dark' ? '☀' : '☾'}
                    </button>
                    {user ? (
                        <Link to="/dashboard" className="hp-nav-link">Dashboard</Link>
                    ) : (
                        <Link to="/login" className="hp-nav-link">Sign in</Link>
                    )}
                    <Link to="/signup" className="hp-nav-btn">Get started</Link>
                </div>
            </nav>

            <section className="hp-hero">
                <div className="hp-eyebrow">AI-powered study tool</div>
                <h1 className="hp-title">
                    Your notes, turned into questions <em>worth asking</em>
                </h1>
                <p className="hp-sub">
                    Upload your lecture slides or paste your notes. Get study questions
                    tailored to what your professor actually cares about.
                </p>
                <div className="hp-actions">
                    <Link to="/signup" className="btn-hero">Upload your first slides</Link>
                    <a href="#how-it-works" className="btn-ghost">See how it works</a>
                </div>
            </section>

            <section className="hp-steps" id="how-it-works">
                <div className="hp-section-label">How it works</div>
                <div className="hp-steps-grid">
                    <div className="hp-step-card">
                        <div className="hp-step-num">01</div>
                        <div className="hp-step-title">Upload your slides</div>
                        <div className="hp-step-desc">
                            Drop in a PDF or paste your notes directly. Works with any format.
                        </div>
                    </div>
                    <div className="hp-step-card">
                        <div className="hp-step-num">02</div>
                        <div className="hp-step-title">We read what matters</div>
                        <div className="hp-step-desc">
                            AI extracts key concepts, even from dense or messy lecture slides.
                        </div>
                    </div>
                    <div className="hp-step-card">
                        <div className="hp-step-num">03</div>
                        <div className="hp-step-title">Study with real questions</div>
                        <div className="hp-step-desc">
                            Get a mix of factual, applied, and problem-solving questions to actually prepare.
                        </div>
                    </div>
                </div>
            </section>

            <section className="hp-problem">
                <div className="hp-problem-inner">
                    <div>
                        <div className="hp-section-label">Problem solving</div>
                        <h2 className="hp-problem-title">
                            Don&apos;t just memorize. Learn to <em>think through it.</em>
                        </h2>
                        <p className="hp-problem-desc">
                            For some classes, flashcards just aren&apos;t enough. Studykit generates novel
                            practice problems that test how you apply concepts, not just whether
                            you remember them.
                        </p>
                    </div>
                    <div className="hp-features">
                        <div className="hp-feature">
                            <div className="hp-feature-icon">⌥</div>
                            <div>
                                <div className="hp-feature-title">Coding problems from your slides</div>
                                <div className="hp-feature-desc">
                                    Generates original problems matching the concepts your professor covered.
                                </div>
                            </div>
                        </div>
                        <div className="hp-feature">
                            <div className="hp-feature-icon">∑</div>
                            <div>
                                <div className="hp-feature-title">Worked solutions included</div>
                                <div className="hp-feature-desc">
                                    Every problem comes with a step-by-step solution so you can check your reasoning.
                                </div>
                            </div>
                        </div>
                        <div className="hp-feature">
                            <div className="hp-feature-icon">⇅</div>
                            <div>
                                <div className="hp-feature-title">Adjustable difficulty</div>
                                <div className="hp-feature-desc">
                                    Start easy, ramp up. Dial in the difficulty to match where you are.
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {user && (
                <section className="hp-recent">
                    <div className="hp-section-row">
                        <div className="hp-section-title">Recent study sets</div>
                        <Link to="/dashboard" className="hp-section-action">View all</Link>
                    </div>
                    <div className="hp-empty">
                        <div className="hp-empty-title">No study sets yet</div>
                        <div className="hp-empty-sub">Upload your first set of slides to get started.</div>
                    </div>
                </section>
            )}
        </div>
    );
}

export default HomePage;