import { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import { getAccessToken, apiFetch, apiUpload, apiBaseUrl } from '../utils/api.js';
import { FiPaperclip, FiArrowLeft, FiSun, FiMoon, FiAlertTriangle } from 'react-icons/fi';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import MarkdownMessage from '../components/MarkdownMessage.jsx';
import { IoSend } from 'react-icons/io5';
import { Switch } from 'antd';
import './StudyPage.css';

// ── state enums ───────────────────────────────────────────────
// Module-level so they're created once (STATUS used to be re-created every render).

/** What the page is showing / what the input box does. */
const MODE = Object.freeze({
    IDLE: 'idle',           // no questions yet — input uploads material
    LOADING: 'loading',     // every received question answered, more still streaming in
    ANSWER: 'answer',       // answering the current question
    CHAT: 'chat',           // free-form chat about the material
    COMPLETE: 'complete',   // every question answered, nothing more coming
});

/** Lifecycle of the initial session fetch. Replaces `sessionLoading` (bool). */
const SESSION_STATUS = Object.freeze({
    LOADING: 'loading',
    READY: 'ready',
    ERROR: 'error',
});

/** What the page is currently waiting on. Replaces `loading` (bool). */
const ACTIVITY = Object.freeze({
    NONE: 'none',
    UPLOADING: 'uploading',
    GENERATING: 'generating',
    SUBMITTING_ANSWER: 'submitting_answer',
    SENDING_CHAT: 'sending_chat',
    RESETTING: 'resetting',
});

/**
 * State of a question-generation job. Replaces `generationComplete` (bool) and
 * the per-message `partial` flag (bool), which conflated "still streaming"
 * with "finished but some questions failed validation".
 * IDLE = not generating (never started, reset, or the stream ended early).
 */
const GENERATION = Object.freeze({
    IDLE: 'idle',
    STREAMING: 'streaming',
    COMPLETE: 'complete',
    FAILED_VALIDATION: 'failed_validation',
});

// After the last loaded question is answered: wait only if the stream is
// still open and may deliver more; otherwise the session is done.
const modeAfterLastQuestion = (generationStatus) =>
    generationStatus === GENERATION.STREAMING ? MODE.LOADING : MODE.COMPLETE;

export default function StudyPage() {
    const { sessionId } = useParams();
    const navigate = useNavigate();
    const { theme, toggleTheme } = useTheme();
    const toast = useToast();

    const [sessionState, setSessionState] = useState(null);
    const [messages, setMessages] = useState([]);
    const [mode, setMode] = useState(MODE.IDLE);
    const [inputText, setInputText] = useState('');
    const [inputError, setInputError] = useState(null);
    const [file, setFile] = useState(null);
    const [activity, setActivity] = useState(ACTIVITY.NONE);
    const [sessionStatus, setSessionStatus] = useState(SESSION_STATUS.LOADING);
    const [sessionError, setSessionError] = useState(null);       // message shown when sessionStatus === ERROR
    const [retryError, setRetryError] = useState(null);           // retry banner error
    const [generationStatus, setGenerationStatus] = useState(GENERATION.IDLE);

    // Binary view of `activity` for the many "disable while busy" checks.
    const isBusy = activity !== ACTIVITY.NONE;

    const inputRef = useRef(null);
    const controllerRef = useRef(null);
    const messagesEndRef = useRef(null);

    // ── init ──────────────────────────────────────────────────
    useEffect(() => {
        const initSession = async () => {
            try {
                let state = await apiFetch(`/sessions/${sessionId}`);

                // Create study set if session doesn't have one yet
                if (!state.study_set_id) {
                    await apiFetch(`/sessions/${sessionId}/study-set`, {
                        method: 'POST',
                    });
                    state = await apiFetch(`/sessions/${sessionId}`);
                }

                setSessionState(state);

                // Restore chat history if session was previously active
                if (state.chat_history?.length > 0 && state.questions?.length > 0) {
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
                const position = state?.current_position ?? 0;

                if (loadedQuestions.length === 0) {
                    setMode(MODE.IDLE);
                } else if (position >= loadedQuestions.length) {
                    setMode(modeAfterLastQuestion(generationStatus));
                } else {
                    setMode(MODE.ANSWER);
                }

                setSessionStatus(SESSION_STATUS.READY);
            } catch (err) {
                if (err.status === 404) {
                    // Unchanged from before: a 404 skips the error screen and
                    // renders the normal shell.
                    setSessionStatus(SESSION_STATUS.READY);
                    return;
                }
                setSessionError(
                    err.status === 403
                        ? "You don't have access to this session."
                        : 'Could not load this session. Please try again.'
                );
                setSessionStatus(SESSION_STATUS.ERROR);
            } finally {
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
        const index = sessionState?.current_position;
        if (newMode === MODE.ANSWER && (!questions?.length || index >= questions.length)) return;
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
        setActivity(ACTIVITY.UPLOADING);

        if (currentFile) {
            try {
                const formData = new FormData();
                if (currentInput) formData.append('raw_markdown', currentInput);
                formData.append('file', currentFile);

                await apiUpload(
                    `/sessions/${sessionId}/upload`,
                    formData
                );
            } catch (err) {
                setActivity(ACTIVITY.NONE);
                setRetryError({
                    message: 'Upload failed — please try again.',
                    onRetry: () => { setRetryError(null); handleUploadAndGenerate(); },
                });
                return;
            }
        } else if (currentInput) {
            try {
                const formData = new FormData();
                formData.append('raw_markdown', currentInput);
                await apiUpload(`/sessions/${sessionId}/upload`, formData);
            } catch (err) {
                setActivity(ACTIVITY.NONE);
                setRetryError({
                    message: 'Upload failed — please try again.',
                    onRetry: () => { setRetryError(null); handleUploadAndGenerate(); },
                });
                return;
            }
        }

        // captured in closure so retry can call without re-uploading
        await handleGenerate(sessionId, label, currentFile ? '' : currentInput);
    };

    const handleGenerate = async (sessionId, label, rawMarkdown) => {
        console.log('[generate] handleGenerate called', { sessionId });

        // Abort any existing stream
        if (controllerRef.current) {
            console.log('[generate] aborting existing stream before new generation');
            controllerRef.current.abort();
            controllerRef.current = null;
        }

        setActivity(ACTIVITY.GENERATING);
        setRetryError(null);

        try {
            console.log('[generate] enqueuing job');
            const { job_id } = await apiFetch(`/sessions/${sessionId}/generate`, {
                method: 'POST',
                body: JSON.stringify({ label, raw_markdown: rawMarkdown }),
            });
            console.log('[generate] job enqueued', { job_id });

            const token = await getAccessToken();
            console.log('[generate] opening stream');
            await streamGeneration(sessionId, token, label, rawMarkdown);
            console.log('[generate] stream resolved');

        } catch (err) {
            console.error('[generate] caught error', err);
            // A missing status means the request never reached the server
            // (network/CORS/CSP), which is a different failure than a 5xx.
            const message =
                err.isNetworkError || err.status === 0
                    ? err.message
                    : typeof err.status === 'number' && err.status < 500
                        ? err.message
                        : 'Generation failed — please try again.';
            setRetryError({
                message,
                onRetry: () => {
                    setRetryError(null);
                    handleGenerate(sessionId, label, rawMarkdown);
                },
            });
        } finally {
            setActivity(ACTIVITY.NONE);
            // Stream is over. If it never reached job_complete (error / drop),
            // we're no longer generating; and if the user was parked waiting
            // for more questions, nothing more is coming.
            setGenerationStatus(prev => prev === GENERATION.STREAMING ? GENERATION.IDLE : prev);
            setMode(prev => prev === MODE.LOADING ? MODE.COMPLETE : prev);
            scrollToBottom();
        }
    };

    const streamGeneration = (sessionId, token, label, rawMarkdown) => {
        console.log('[stream] streamGeneration called', { sessionId });

        return new Promise((resolve, reject) => {
            const questions = [];
            const controller = new AbortController();
            controllerRef.current = controller;

            setGenerationStatus(GENERATION.STREAMING);
            console.log('[stream] opening fetchEventSource');

            fetchEventSource(
                `${apiBaseUrl}/sessions/${sessionId}/stream`, {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Accept': 'text/event-stream',
                },
                signal: controller.signal,

                onopen(response) {
                    console.log('[stream] onopen', { status: response.status, ok: response.ok });
                    if (!response.ok) {
                        throw new Error(`Stream failed: ${response.status}`);
                    }
                },

                onmessage(e) {
                    console.log('[stream] onmessage', { event: e.event, dataLength: e.data?.length });
                    if (e.event === 'heartbeat') { return; }

                    else if (e.event === 'question_approved') {
                        const question = JSON.parse(e.data);
                        questions.push(question);
                        console.log('[stream] question received', {
                            question_id: question.question_id,
                            total: questions.length
                        });

                        setSessionState(prev => ({
                            ...prev,
                            questions: [...prev.questions, question],
                        }));

                        setMode(prev => prev === MODE.LOADING ? MODE.ANSWER : prev);

                        if (questions.length === 1) {
                            setMessages(prev => [...prev, {
                                role: 'assistant',
                                content: questions,
                                type: 'questions',
                                generation: GENERATION.STREAMING,
                            }]);
                            setMode(MODE.ANSWER);
                        } else {
                            setMessages(prev => prev.map(msg =>
                                msg.type === 'questions'
                                    ? { ...msg, content: [...questions] }
                                    : msg
                            ));
                        }

                    } else if (e.event === 'job_complete') {
                        console.log('[stream] job_complete received', { questionsReceived: questions.length });
                        const { status } = JSON.parse(e.data);
                        const finalStatus = status === 'failed_validation'
                            ? GENERATION.FAILED_VALIDATION
                            : GENERATION.COMPLETE;
                        setGenerationStatus(finalStatus);

                        if (questions.length === 0) {
                            setMode(MODE.IDLE);
                            setRetryError({
                                message: "Couldn't build questions from this material.",
                                onRetry: () => {
                                    setRetryError(null);
                                    handleGenerate(sessionId, label, rawMarkdown);
                                },
                            });
                        } else {
                            setMessages(prev => prev.map(msg =>
                                msg.type === 'questions'
                                    ? { ...msg, content: [...questions], generation: finalStatus }
                                    : msg
                            ));
                        }

                        resolve();
                        console.log('[stream] resolved, aborting controller');
                        controller.abort();
                    }
                },

                onerror(err) {
                    console.error('[stream] onerror', {
                        name: err?.name,
                        message: err?.message,
                        aborted: controller.signal.aborted,
                        questionsReceived: questions.length,
                    });

                    if (controller.signal.aborted) {
                        resolve();
                        return;
                    }

                    if (questions.length === 0) {
                        reject(new Error('Stream disconnected before any questions arrived'));
                    } else {
                        resolve();
                    }
                },
            });
        });
    };

    // ── reset + regenerate ────────────────────────────────────
    const resetSessionState = async () => {
        await apiFetch(`/sessions/${sessionId}/reset`, { method: 'POST' });
        setMessages([]);
        setGenerationStatus(GENERATION.IDLE);
        setSessionState(prev => ({
            ...prev,
            questions: [],
            current_position: 0,
        }));
    };

    const handleRegenerate = async (guidanceText = '') => {
        if (!sessionState?.study_set_id) {
            toast.error('No study material to regenerate from.');
            return;
        }
        // The reset is part of regenerating, so the whole thing reads as GENERATING.
        setActivity(ACTIVITY.GENERATING);
        try {
            await resetSessionState();
            await handleGenerate(sessionId, sessionState?.label ?? 'Study set', guidanceText);
        } catch (err) {
            toast.error(err.status < 500
                ? err.message
                : 'Could not reset this session — please try again.');
        } finally {
            setActivity(ACTIVITY.NONE);
        }
    };

    const handleAddMaterial = async () => {
        setActivity(ACTIVITY.RESETTING);
        try {
            await resetSessionState();
            setMode(MODE.IDLE);
        } catch (err) {
            toast.error('Could not reset this session — please try again.');
        } finally {
            setActivity(ACTIVITY.NONE);
        }
    };

    // ── answer ────────────────────────────────────────────────


    const handleAnswer = async (choiceIndex = null) => {
        const currentInput = inputText;
        const currentQuestion = sessionState?.questions?.[sessionState?.current_position];
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
        setActivity(ACTIVITY.SUBMITTING_ANSWER);

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

            const nextIndex = (sessionState?.current_position ?? 0) + 1;
            const total = sessionState?.questions?.length ?? 0;

            if (nextIndex < total) {
                setSessionState(prev => ({
                    ...prev,
                    current_position: nextIndex,
                }));
            } else {
                // Last loaded question answered: wait if more are still
                // streaming in, otherwise we're done.
                setMode(modeAfterLastQuestion(generationStatus));
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
            setActivity(ACTIVITY.NONE);
            scrollToBottom();
        }
    };

    // ── chat ──────────────────────────────────────────────────
    const handleChat = async () => {
        const currentInput = inputText;

        setMessages(prev => [...prev, { role: 'user', content: currentInput }]);
        setInputText('');
        setActivity(ACTIVITY.SENDING_CHAT);

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
            setActivity(ACTIVITY.NONE);
            scrollToBottom();
        }
    };

    // ── send router ───────────────────────────────────────────
    const validateInput = (text, currentMode) => {
        if (currentMode === MODE.ANSWER && currentQuestion?.question_type !== 'MCQ') {
            if (!text.trim()) return 'Answer cannot be empty';
            if (text.trim().length < 3) return 'Answer is too short';
        }
        if (currentMode === MODE.CHAT) {
            if (!text.trim()) return 'Message cannot be empty';
        }
        return null;
    };

    const handleSend = async () => {
        if (!inputText.trim() && !file) return;

        if (mode === MODE.ANSWER || mode === MODE.CHAT) {
            const error = validateInput(inputText, mode);
            if (error) {
                setInputError(error);
                return;
            }
        }

        setInputError(null);

        if (file || mode === MODE.IDLE) {
            await handleUploadAndGenerate();
        } else if (mode === MODE.ANSWER) {
            await handleAnswer();
        } else {
            await handleChat();
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!isBusy) handleSend();
        }
    };

    // ── derived ───────────────────────────────────────────────
    // Single normalized source of truth — every render path below reads this
    // instead of sessionState.questions, which may be undefined mid-flight.
    const questions = Array.isArray(sessionState?.questions) ? sessionState.questions : [];
    const questionCount = questions.length;
    const answeredCount = Math.min(sessionState?.current_position ?? 0, questionCount);

    const hasActiveQuestions =
        questionCount > 0 && (sessionState?.current_position ?? 0) < questionCount;

    const currentQuestion = hasActiveQuestions
        ? questions[sessionState.current_position]
        : null;

    const isMcqAnswerMode =
        mode === MODE.ANSWER &&
        currentQuestion?.question_type === 'MCQ';

    const sessionTitle = sessionState?.label || 'New session';

    const placeholder =
        mode === MODE.ANSWER && currentQuestion
            ? currentQuestion.question_type === 'MCQ'
                ? ''
                : `Answer Q${sessionState.current_position + 1}...`
            : mode === MODE.CHAT
            ? 'Ask studykit anything...'
            : 'Paste notes or attach a file to get started...';

    // ── full page loading ─────────────────────────────────────
    if (sessionStatus === SESSION_STATUS.LOADING) {
        return (
            <div className="sp-wrap sp-loading-screen">
                <div className="sp-loading">
                    <span /><span /><span />
                </div>
            </div>
        );
    }

    // ── full page error (403, 500, unrecoverable) ─────────────
    if (sessionStatus === SESSION_STATUS.ERROR) {
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
                                                {msg.generation === GENERATION.FAILED_VALIDATION && qs.length > 0 && (
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
                                        <MarkdownMessage
                                            className="sp-feedback-text"
                                            isDark={theme === 'dark'}
                                        >
                                            {String(msg.content)}
                                        </MarkdownMessage>
                                        {msg.misconception && (
                                            <p className="sp-misconception">
                                                Common mistake: {msg.misconception}
                                            </p>
                                        )}
                                    </div>
                                ) : msg.role === 'assistant' ? (
                                    <MarkdownMessage isDark={theme === 'dark'}>{String(msg.content)}</MarkdownMessage>
                                ) : (
                                    <MarkdownMessage isDark={theme === 'dark'}>
                                        {String(msg.content)}
                                    </MarkdownMessage>
                                )}
                            </div>
                        </div>
                    ))}

                    {/* ── current question card ── */}
                    {currentQuestion && mode === MODE.ANSWER && (
                        <div className="sp-question-card">
                            <div className="sp-question-card-header">
                                <span className="sp-question-num">
                                    Q{sessionState.current_position + 1} of {questionCount}
                                </span>
                                <span className="sp-question-type-badge">{currentQuestion.question_type}</span>
                            </div>
                            <MarkdownMessage
                                className="sp-question-prompt"
                                isDark={theme === 'dark'}
                            >
                                {String(currentQuestion.prompt)}
                            </MarkdownMessage>
                            {currentQuestion.question_type === 'MCQ' && currentQuestion.choices && (
                                <div className="sp-choices">
                                    {currentQuestion.choices.map((choice, ci) => (
                                        <button
                                            key={ci}
                                            type="button"
                                            className="sp-choice"
                                            disabled={isBusy}
                                            onClick={() => handleAnswer(ci)}
                                        >
                                            <span className="sp-choice-letter">
                                                {String.fromCharCode(65 + ci)}
                                            </span>

                                            <MarkdownMessage
                                                className="sp-choice-text"
                                                isDark={theme === 'dark'}
                                            >
                                                {String(choice)}
                                            </MarkdownMessage>
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {isBusy && (
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
                                disabled={isBusy}
                            >
                                {isBusy ? 'Retrying...' : 'Retry'}
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
            {mode === MODE.COMPLETE ? (
                <div className="sp-completion-banner">
                    <div className="sp-completion-banner-inner">
                        {/* Show summary only when there are answered questions */}
                        {/* hide count when reset was just called (questions cleared) */}
                        {questionCount > 0 && (
                            <div className="sp-completion-text">
                                <p className="sp-completion-title">Session complete</p>
                                <p className="sp-completion-sub">
                                    {questionCount} question{questionCount === 1 ? '' : 's'} answered
                                </p>
                            </div>
                        )}

                        <div className="sp-completion-actions">
                            {/* Guidance input for regeneration */}
                            <textarea
                                className="sp-regenerate-input"
                                placeholder="Optional: guide the next set (e.g. 'focus on thermodynamics')"
                                rows={2}
                                id="regenerate-guidance"
                            />

                            <div className="sp-completion-btn-row">
                                {/*regenerate from existing study set */}
                                <button
                                    className="sp-completion-btn--primary"
                                    onClick={() => {
                                        const guidance = document.getElementById('regenerate-guidance')?.value ?? '';
                                        handleRegenerate(guidance);
                                    }}
                                    disabled={isBusy}
                                >
                                    {activity === ACTIVITY.GENERATING ? 'Generating...' : 'Regenerate questions'}
                                </button>

                                {/* upload new material — drops to idle for upload flow */}
                                <button
                                    className="sp-completion-btn--secondary"
                                    onClick={() => handleAddMaterial()}
                                    disabled={isBusy}
                                >
                                    Add new material
                                </button>

                                <Link to="/dashboard" className="sp-completion-btn--ghost">
                                    Back to dashboard
                                </Link>
                            </div>
                        </div>
                    </div>
                </div>
            ) : (
                <div className="sp-input-wrap">
                    {hasActiveQuestions && (
                        <div className="sp-toggle-row">
                            <Switch
                                checked={mode === MODE.CHAT}
                                checkedChildren="💬 Chat"
                                unCheckedChildren="📝 Answer"
                                onChange={(checked) => handleModeToggle(checked ? MODE.CHAT : MODE.ANSWER)}
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
                            {mode === MODE.IDLE && (
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
                                        disabled={isBusy}
                                    />

                                    <button
                                        className="sp-send-btn"
                                        type="button"
                                        onClick={handleSend}
                                        disabled={(!inputText.trim() && !file) || isBusy}
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
                        {mode === MODE.ANSWER
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