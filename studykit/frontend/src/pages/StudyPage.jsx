import { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import { apiFetch, apiUpload } from '../utils/api.js';
import { FiPaperclip, FiArrowLeft, FiSun, FiMoon, FiAlertTriangle } from 'react-icons/fi';
import MarkdownMessage from '../components/MarkdownMessage.jsx';
import { IoSend } from 'react-icons/io5';
import { Switch } from 'antd';
import './StudyPage.css';

export default function StudyPage() {
    const { sessionId } = useParams();
    const navigate = useNavigate();
    const { theme, toggleTheme } = useTheme();
    const toast = useToast();

    const [sessionState, setSessionState] = useState(null);
    const [messages, setMessages] = useState([]);
    const [mode, setMode] = useState('idle'); // 'idle' | 'answer' | 'chat' | 'complete'
    const [inputText, setInputText] = useState('');
    const [inputError, setInputError] = useState(null);
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [sessionLoading, setSessionLoading] = useState(true);
    const [sessionError, setSessionError] = useState(null);       // full page error state
    const [retryError, setRetryError] = useState(null);           // retry banner error

    const inputRef = useRef(null);
    const messagesEndRef = useRef(null);

    // ── init ──────────────────────────────────────────────────
    useEffect(() => {
        const initSession = async () => {
            try {
                const state = await apiFetch(`/sessions/${sessionId}`);
                setSessionState(state);

                if (state.chat_history?.length > 0) {
                    const loadedMessages = state.chat_history.map(msg => ({
                        role: msg.role || (msg.type === 'human' ? 'user' : 'assistant'),
                        content: msg.content || msg.text || '',
                        type: msg.type || 'text',
                        file: msg.file || null,
                        score: msg.score,
                        misconception: msg.misconception,
                    }));
                    setMessages(loadedMessages);
                }

                const loadedQuestions = Array.isArray(state?.questions) ? state.questions : [];
                const index = state?.current_question_index ?? 0;
                if (loadedQuestions.length === 0) {
                    // Session exists but generation produced nothing usable — let the
                    // user upload/paste again rather than showing an empty study view.
                    setMode('idle');
                } else if (index >= loadedQuestions.length) {
                    setMode('complete');
                } else {
                    setMode('answer');
                }
            } catch (err) {
                // 404 = new session, not a real error
                if (err.status === 404) return;
                // 403 or 500 = broken, show full page error
                setSessionError(
                    err.status === 403
                        ? "You don't have access to this session."
                        : 'Could not load this session. Please try again.'
                );
            } finally {
                setSessionLoading(false);
                scrollToBottom();
            }
        };

        initSession();
    }, [sessionId]);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    // ── mode toggle ───────────────────────────────────────────
    const handleModeToggle = (newMode) => {
        const questions = sessionState?.questions;
        const index = sessionState?.current_question_index;
        if (newMode === 'answer' && (!questions?.length || index >= questions.length)) return;
        setMode(newMode);
    };

    // ── upload + generate ─────────────────────────────────────
    const handleUploadAndGenerate = async () => {
        const currentInput = inputText;
        const currentFile = file;
        const label = currentInput.slice(0, 30) || currentFile?.name || 'Study set';

        setMessages(prev => [...prev, {
            role: 'user',
            content: currentInput,
            file: currentFile?.name || null,
        }]);
        setInputText('');
        setFile(null);
        setRetryError(null);
        if (inputRef.current) inputRef.current.value = '';
        setLoading(true);

        if (currentFile) {
            try {
                const formData = new FormData();
                formData.append('file', currentFile);
                await apiUpload(
                    `/sessions/${sessionId}/upload?label=${encodeURIComponent(label)}`,
                    formData
                );
            } catch (err) {
                setLoading(false);
                setRetryError({
                    message: 'Upload failed — please try again.',
                    onRetry: () => { setRetryError(null); handleUploadAndGenerate(); },
                });
                return;
            }
        }

        // captured in closure so retry can call without re-uploading
        await handleGenerateAndPoll(sessionId, label, currentFile ? '' : currentInput);
    };

    const handleGenerateAndPoll = async (sessionId, label, rawMarkdown) => {
        setLoading(true);
        try {
            const { job_id } = await apiFetch(`/sessions/${sessionId}/generate`, {
                method: 'POST',
                body: JSON.stringify({ label, raw_markdown: rawMarkdown }),
            });

            const result = await pollGeneration(sessionId, job_id);
            const questions = Array.isArray(result?.questions) ? result.questions : [];

            if (questions.length === 0) {
                // Validation terminated early with nothing usable — stay in idle so the
                // user can retry or supply different material, instead of an empty study view.
                setSessionState(prev => ({ ...prev, questions: [], current_question_index: 0 }));
                setMode('idle');
                setRetryError({
                    message: "Couldn't build questions from this material. Try a different file or add more detail.",
                    onRetry: () => {
                        setRetryError(null);
                        handleGenerateAndPoll(sessionId, label, rawMarkdown);
                    },
                });
                return;
            }

            setSessionState(prev => ({
                ...prev,
                questions,
                current_question_index: 0,
            }));
            setMessages(prev => [...prev, {
                role: 'assistant',
                content: questions,
                type: 'questions',
                partial: result?.status === 'failed_validation',
            }]);
            setMode('answer');
            setRetryError(null);
        } catch (err) {
            setRetryError({
                message: err.status < 500
                    ? err.message
                    : 'Generation failed — please try again.',
                onRetry: () => {
                    setRetryError(null);
                    handleGenerateAndPoll(sessionId, label, rawMarkdown);
                },
            });
        } finally {
            setLoading(false);
            scrollToBottom();
        }
    };

    async function pollGeneration(sessionId, jobId, intervalMs = 2000, maxWaitMs = 180000) {
        const deadline = Date.now() + maxWaitMs;
        while (Date.now() < deadline) {
            await new Promise(r => setTimeout(r, intervalMs));
            const data = await apiFetch(`/sessions/${sessionId}/generate/${jobId}`);

            if (data.status === 'generated') return data;           // GenerationResultDTO
            if (data.status === 'failed_validation') return data;   // has questions, but flagged
            if (data.status === 'error') throw new Error(data.message || 'Generation failed');
            // 'queued' or 'in_progress' → keep polling
        }
        throw new Error('Generation timed out — please try again.');
    }

    // ── reset + regenerate ────────────────────────────────────
    const handleReset = async () => {
        setLoading(true);
        try {
            await apiFetch(`/sessions/${sessionId}/reset`, { method: 'POST' });
        } catch (err) {
            setLoading(false);
            const msg = err.status < 500
                ? err.message
                : 'Could not reset this session — please try again.';
            toast.error(msg);
            return;
        }
        // /generate is asynchronous (202 + job_id) — must poll, not read questions directly.
        await handleGenerateAndPoll(sessionId, sessionState?.label ?? 'Study set', '');
    };

    // ── answer ────────────────────────────────────────────────
    

    const handleAnswer = async (choiceIndex = null) => {
        const currentInput = inputText;
        const currentQuestion = sessionState?.questions?.[sessionState?.current_question_index];
        if (!currentQuestion) return;

        const isMCQ = currentQuestion.question_type === 'MCQ';
        if (isMCQ) {
            const choiceLetter = String.fromCharCode(65 + choiceIndex);
            const choiceText = currentQuestion.choices[choiceIndex];
            setMessages(prev => [...prev, {
                role: 'user',
                content: `${choiceLetter}. ${choiceText}`,
            }]);
        }

        if (!isMCQ) {
            setMessages(prev => [...prev, {
                role: 'user',
                content: currentInput
            }]);
        }

        setInputText('');
        setLoading(true);

        try {
            const body = {
                question_id: currentQuestion.question_id,
                ...(isMCQ
                    ? { choice_index: choiceIndex }
                    : { response: currentInput })
            };

            const data = await apiFetch(`/sessions/${sessionId}/answer`, {
                method: 'POST',
                body: JSON.stringify(body),
            });

            setMessages(prev => [...prev, {
                role: 'assistant',
                content: data.feedback,
                score: data.score,
                misconception: data.misconception,
                type: 'answer_feedback',
            }]);

            const nextIndex = (sessionState?.current_question_index ?? 0) + 1;
            const total = sessionState?.questions?.length ?? 0;

            setSessionState(prev => ({
                ...prev,
                current_question_index: nextIndex,
            }));

            if (nextIndex >= total) {
                setMode('complete');
            }
        } catch (err) {
            setMessages(prev => [...prev, {
                role: 'assistant',
                content:
                    err.status < 500
                        ? err.message
                        : 'Could not submit your answer — please try again.',
                type: 'error',
            }]);
        } finally {
            setLoading(false);
            scrollToBottom();
        }
    };

    // ── chat ──────────────────────────────────────────────────
    const handleChat = async () => {
        const currentInput = inputText;

        setMessages(prev => [...prev, { role: 'user', content: currentInput }]);
        setInputText('');
        setLoading(true);

        try {
            const data = await apiFetch(`/sessions/${sessionId}/chat`, {
                method: 'POST',
                body: JSON.stringify({ user_message: currentInput }),
            });

            setMessages(prev => [...prev, {
                role: 'assistant',
                content: data.reply,
                type: 'chat_response',
            }]);
        } catch (err) {
            // error bubble — direct reply to user's chat message
            setMessages(prev => [...prev, {
                role: 'assistant',
                content: err.status < 500
                    ? err.message
                    : 'Something went wrong — please try again.',
                type: 'error',
            }]);
        } finally {
            setLoading(false);
            scrollToBottom();
        }
    };

    // ── send router ───────────────────────────────────────────
    const validateInput = (text, currentMode) => {
        if (currentMode === 'answer' && currentQuestion?.question_type !== 'MCQ') {
            if (!text.trim()) return 'Answer cannot be empty';
            if (text.trim().length < 3) return 'Answer is too short';
        }
        if (currentMode === 'chat') {
            if (!text.trim()) return 'Message cannot be empty';
        }
        return null;
    };

    const handleSend = async () => {
        if (!inputText.trim() && !file) return;

        if (mode === 'answer' || mode === 'chat') {
            const error = validateInput(inputText, mode);
            if (error) {
                setInputError(error);
                return;
            }
        }

        setInputError(null);

        if (file || mode === 'idle') {
            await handleUploadAndGenerate();
        } else if (mode === 'answer') {
            await handleAnswer();
        } else {
            await handleChat();
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!loading) handleSend();
        }
    };

    // ── derived ───────────────────────────────────────────────
    // Single normalized source of truth — every render path below reads this
    // instead of sessionState.questions, which may be undefined mid-flight.
    const questions = Array.isArray(sessionState?.questions) ? sessionState.questions : [];
    const questionCount = questions.length;
    const answeredCount = Math.min(sessionState?.current_question_index ?? 0, questionCount);

    const hasActiveQuestions =
        questionCount > 0 && (sessionState?.current_question_index ?? 0) < questionCount;

    const currentQuestion = hasActiveQuestions
        ? questions[sessionState.current_question_index]
        : null;
    
    const isMcqAnswerMode =
        mode === 'answer' &&
        currentQuestion?.question_type === 'MCQ';

    const sessionTitle = sessionState?.label || 'New session';

    const placeholder =
        mode === 'answer' && currentQuestion
            ? currentQuestion.question_type === 'MCQ'
                ? ''
                : `Answer Q${sessionState.current_question_index + 1}...`
            : mode === 'chat'
            ? 'Ask studykit anything...'
            : 'Paste notes or attach a file to get started...';

    // ── full page loading ─────────────────────────────────────
    if (sessionLoading) {
        return (
            <div className="sp-wrap sp-loading-screen">
                <div className="sp-loading">
                    <span /><span /><span />
                </div>
            </div>
        );
    }

    // ── full page error (403, 500, unrecoverable) ─────────────
    if (sessionError) {
        return (
            <div className="sp-wrap sp-error-screen">
                <div className="sp-error-state">
                    <div className="sp-error-icon">
                        <FiAlertTriangle size={28} />
                    </div>
                    <p className="sp-error-title">Something went wrong</p>
                    <p className="sp-error-sub">{sessionError}</p>
                    <button
                        className="sp-error-back"
                        onClick={() => navigate('/dashboard')}
                    >
                        <FiArrowLeft size={14} />
                        Back to dashboard
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="sp-wrap">
            {/* ── header ── */}
            <div className="sp-topbar">
                <header className="sp-header">
                    <button
                        className="sp-back-btn"
                        onClick={() => navigate('/dashboard')}
                        aria-label="Back to dashboard"
                    >
                        <FiArrowLeft size={16} />
                        Sessions
                    </button>
                    <span className="sp-session-title">{sessionTitle}</span>
                    <button
                        className="sp-theme-btn"
                        onClick={toggleTheme}
                        aria-label="Toggle theme"
                    >
                        {theme === 'dark' ? <FiSun size={15} /> : <FiMoon size={15} />}
                    </button>
                </header>

                {/* ── progress bar ── */}
                {questionCount > 0 && (
                    <div className="sp-progress-wrap">
                        <div className="sp-progress-track">
                            <div
                                className="sp-progress-fill"
                                style={{
                                    width: `${Math.min((answeredCount / questionCount) * 100, 100)}%`
                                }}
                            />
                        </div>
                        <span className="sp-progress-label">
                            {answeredCount}/{questionCount}
                        </span>
                    </div>
                )}
            </div>

            {/* ── messages ── */}
            <main className="sp-main">
                <div className="sp-messages">
                    {messages.length === 0 && (
                        <div className="sp-empty">
                            <div className="sp-empty-icon">⌥</div>
                            <div className="sp-empty-title">Upload your slides or paste your notes</div>
                            <div className="sp-empty-sub">
                                studykit will generate study questions based on what you share.
                            </div>
                        </div>
                    )}

                    {messages.map((msg, i) => (
                        <div key={i} className={`sp-message sp-message--${msg.role}`}>
                            <div className={`sp-message-bubble ${msg.type === 'error' ? 'sp-message-bubble--error' : ''}`}>
                                {msg.file && (
                                    <div className="sp-file-tag">
                                        <FiPaperclip size={12} />
                                        {msg.file}
                                    </div>
                                )}

                                {msg.type === 'questions' ? (
                                    (() => {
                                        const qs = Array.isArray(msg.content) ? msg.content : [];
                                        return (
                                            <div className="sp-questions">
                                                <p className="sp-questions-label">
                                                    {qs.length === 0
                                                        ? 'No questions could be generated from this material.'
                                                        : `${qs.length} question${qs.length === 1 ? '' : 's'} generated — starting below.`}
                                                </p>
                                                {msg.partial && qs.length > 0 && (
                                                    <p className="sp-questions-partial">
                                                        Some questions didn’t pass quality checks, so this set is shorter than usual.
                                                    </p>
                                                )}
                                                <div className="sp-questions-preview">
                                                    {qs.slice(0, 3).map((q, qi) => (
                                                        <div key={q.question_id ?? qi} className="sp-question-chip">
                                                            <span className="sp-question-chip-num">Q{qi + 1}</span>
                                                            <span className="sp-question-chip-type">{q.question_type}</span>
                                                        </div>
                                                    ))}
                                                    {qs.length > 3 && (
                                                        <span className="sp-question-chip sp-question-chip--more">
                                                            +{qs.length - 3} more
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })()
                                ) : msg.type === 'answer_feedback' ? (
                                    <div className="sp-feedback">
                                        <div className={`sp-score-badge sp-score-badge--${msg.score >= 0.85 ? 'correct' : msg.score >= 0.5 ? 'partial' : 'incorrect'}`}>
                                            {msg.score >= 0.85 ? '✓ Correct' : msg.score >= 0.5 ? '~ Partial' : '✗ Incorrect'}
                                            <span className="sp-score-pct">{Math.round(msg.score * 100)}%</span>
                                        </div>
                                        <p className="sp-feedback-text">{msg.content}</p>
                                        {msg.misconception && (
                                            <p className="sp-misconception">
                                                Common mistake: {msg.misconception}
                                            </p>
                                        )}
                                    </div>
                                ) : msg.role === 'assistant' ? (
                                    <MarkdownMessage isDark={theme === 'dark'}>{String(msg.content)}</MarkdownMessage>
                                ) : (
                                    <span>{msg.content}</span>
                                )}
                            </div>
                        </div>
                    ))}

                    {/* ── current question card ── */}
                    {currentQuestion && mode === 'answer' && (
                        <div className="sp-question-card">
                            <div className="sp-question-card-header">
                                <span className="sp-question-num">
                                    Q{sessionState.current_question_index + 1} of {questionCount}
                                </span>
                                <span className="sp-question-type-badge">{currentQuestion.question_type}</span>
                            </div>
                            <p className="sp-question-prompt">{currentQuestion.prompt}</p>
                            {currentQuestion.question_type === 'MCQ' && currentQuestion.choices && (
                                <div className="sp-choices">
                                    {currentQuestion.choices.map((choice, ci) => (
                                        <button
                                            key={ci}
                                            type="button"
                                            className="sp-choice"
                                            disabled={loading}
                                            onClick={() => handleAnswer(ci)}
                                        >
                                            <span className="sp-choice-letter">
                                                {String.fromCharCode(65 + ci)}
                                            </span>

                                            <span>{choice}</span>
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {loading && (
                        <div className="sp-message sp-message--assistant">
                            <div className="sp-message-bubble">
                                <div className="sp-loading">
                                    <span /><span /><span />
                                </div>
                            </div>
                        </div>
                    )}

                    <div ref={messagesEndRef} />
                </div>
            </main>

            {/* ── retry banner (upload/generate failure) ── */}
            {retryError && (
                <div className="sp-retry-banner">
                    <div className="sp-retry-banner-inner">
                        <div className="sp-retry-left">
                            <FiAlertTriangle size={14} />
                            <span>{retryError.message}</span>
                        </div>
                        <div className="sp-retry-actions">
                            <button
                                className="sp-retry-btn"
                                onClick={retryError.onRetry}
                                disabled={loading}
                            >
                                {loading ? 'Retrying...' : 'Retry'}
                            </button>
                            <button
                                className="sp-retry-dismiss"
                                onClick={() => setRetryError(null)}
                                aria-label="Dismiss"
                            >
                                ✕
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* ── completion banner or input ── */}
            {mode === 'complete' ? (
                <div className="sp-completion-banner">
                    <div className="sp-completion-banner-inner">
                        <div className="sp-completion-text">
                            <p className="sp-completion-title">Session complete</p>
                            <p className="sp-completion-sub">
                                {questionCount} question{questionCount === 1 ? '' : 's'} answered
                            </p>
                        </div>
                        <div className="sp-completion-actions">
                            <button
                                className="sp-completion-btn--primary"
                                onClick={handleReset}
                                disabled={loading}
                            >
                                {loading ? 'Generating...' : 'Generate new questions'}
                            </button>
                            <Link to="/dashboard" className="sp-completion-btn--ghost">
                                Back to dashboard
                            </Link>
                        </div>
                    </div>
                </div>
            ) : (
                <div className="sp-input-wrap">
                    {hasActiveQuestions && (
                        <div className="sp-toggle-row">
                            <Switch
                                checked={mode === 'chat'}
                                checkedChildren="💬 Chat"
                                unCheckedChildren="📝 Answer"
                                onChange={(checked) => handleModeToggle(checked ? 'chat' : 'answer')}
                            />
                        </div>
                    )}

                    <div className="sp-input-box">
                        <input
                            type="file"
                            hidden
                            ref={inputRef}
                            onChange={(e) => {
                                if (e.target.files.length > 0) setFile(e.target.files[0]);
                            }}
                        />

                        {file && (
                            <div className="sp-file-preview">
                                <FiPaperclip size={12} />
                                <span>{file.name}</span>
                                <button onClick={() => {
                                    setFile(null);
                                    if (inputRef.current) inputRef.current.value = '';
                                }}>✕</button>
                            </div>
                        )}

                        <div className="sp-input-row">
                            {mode === 'idle' && (
                                <button
                                    className="sp-attach-btn"
                                    type="button"
                                    onClick={() => inputRef.current?.click()}
                                    aria-label="Attach file"
                                >
                                    <FiPaperclip size={18} />
                                </button>
                            )}

                            {!isMcqAnswerMode && (
                                <>
                                    <textarea
                                        className={`sp-textarea ${inputError ? 'sp-textarea--error' : ''}`}
                                        value={inputText}
                                        onChange={(e) => {
                                            setInputText(e.target.value);
                                            if (inputError) setInputError(null);
                                        }}
                                        onKeyDown={handleKeyDown}
                                        placeholder={placeholder}
                                        rows={1}
                                        disabled={loading}
                                    />

                                    <button
                                        className="sp-send-btn"
                                        type="button"
                                        onClick={handleSend}
                                        disabled={(!inputText.trim() && !file) || loading}
                                    >
                                        <IoSend size={18} />
                                    </button>
                                </>
                            )}
                        </div>
                    </div>

                    {inputError && (
                        <p className="sp-input-error">{inputError}</p>
                    )}

                    <div className="sp-input-hint">
                        {mode === 'answer'
                            ? currentQuestion?.question_type === 'MCQ'
                                ? 'Select an answer above · Switch to Chat for hints'
                                : 'Enter to submit answer · Shift+Enter for new line'
                            : 'Enter to send · Shift+Enter for new line'}
                    </div>
                </div>
            )}
        </div>
    );
}