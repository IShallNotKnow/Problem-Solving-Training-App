import { useState, useRef } from 'react';
import { useTheme } from '../context/ThemeContext';
import { FiPaperclip, FiPlus, FiBook } from 'react-icons/fi';
import { IoSend } from 'react-icons/io5';
import './StudyPage.css';

function StudyPage() {
    const { theme, toggleTheme } = useTheme();

    const [chats, setChats] = useState([
        { id: 1, title: 'OS scheduling algorithms', messages: [] },
    ]);
    const [activeChatId, setActiveChatId] = useState(1);
    const [inputText, setInputText] = useState('');
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const inputRef = useRef(null);
    const messagesEndRef = useRef(null);

    const activeChat = chats.find(c => c.id === activeChatId);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    const handleNewChat = () => {
        const newId = Date.now();
        setChats(prev => [...prev, { id: newId, title: 'New study set', messages: [] }]);
        setActiveChatId(newId);
        setInputText('');
        setFile(null);
    };

    const handleSend = async () => {
        if (!inputText.trim() && !file) return;

        const userMessage = { role: 'user', content: inputText, file: file?.name || null };

        setChats(prev => prev.map(c =>
            c.id === activeChatId
                ? { ...c, messages: [...c.messages, userMessage] }
                : c
        ));
        setInputText('');
        setFile(null);
        if (inputRef.current) inputRef.current.value = '';
        setLoading(true);

        try {
            const formData = new FormData();
            formData.append('text', inputText);
            if (file) formData.append('file', file);

            const response = await fetch('http://localhost:8000/generate', {
                method: 'POST',
                body: formData,
            });
            const data = await response.json();

            const assistantMessage = { role: 'assistant', content: data.questions };

            setChats(prev => prev.map(c =>
                c.id === activeChatId
                    ? {
                        ...c,
                        title: inputText.slice(0, 30) || file?.name || 'Study set',
                        messages: [...c.messages, assistantMessage]
                    }
                    : c
            ));
        } catch (err) {
            console.error('Error:', err);
            setChats(prev => prev.map(c =>
                c.id === activeChatId
                    ? { ...c, messages: [...c.messages, { role: 'assistant', content: 'Something went wrong. Please try again.' }] }
                    : c
            ));
        } finally {
            setLoading(false);
            scrollToBottom();
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="sp-wrap">
            <aside className="sp-sidebar">
                <div className="sp-sidebar-header">
                    <span className="sp-brand">studykit</span>
                    <button className="sp-theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
                        {theme === 'dark' ? '☀' : '☾'}
                    </button>
                </div>

                <button className="sp-new-chat" onClick={handleNewChat}>
                    <FiPlus size={15} />
                    New study set
                </button>

                <div className="sp-chat-list">
                    <div className="sp-chat-list-label">Recent</div>
                    {chats.map(chat => (
                        <button
                            key={chat.id}
                            className={`sp-chat-item ${chat.id === activeChatId ? 'active' : ''}`}
                            onClick={() => setActiveChatId(chat.id)}
                        >
                            <FiBook size={14} className="sp-chat-icon" />
                            <span className="sp-chat-title">{chat.title}</span>
                        </button>
                    ))}
                </div>

                <div className="sp-sidebar-footer">
                    <a href="/" className="sp-footer-link">Home</a>
                    <a href="/login" className="sp-footer-link">Sign out</a>
                </div>
            </aside>

            <main className="sp-main">
                <div className="sp-messages" id="messages">
                    {activeChat?.messages.length === 0 && (
                        <div className="sp-empty">
                            <div className="sp-empty-icon">⌥</div>
                            <div className="sp-empty-title">Upload your slides or paste your notes</div>
                            <div className="sp-empty-sub">studykit will generate study questions based on what you share.</div>
                        </div>
                    )}

                    {activeChat?.messages.map((msg, i) => (
                        <div key={i} className={`sp-message sp-message--${msg.role}`}>
                            <div className="sp-message-bubble">
                                {msg.file && (
                                    <div className="sp-file-tag">
                                        <FiPaperclip size={12} />
                                        {msg.file}
                                    </div>
                                )}
                                <span>{msg.content}</span>
                            </div>
                        </div>
                    ))}

                    {loading && (
                        <div className="sp-message sp-message--assistant">
                            <div className="sp-message-bubble sp-loading">
                                <span />
                                <span />
                                <span />
                            </div>
                        </div>
                    )}

                    <div ref={messagesEndRef} />
                </div>

                <div className="sp-input-wrap">
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
                                <button onClick={() => { setFile(null); inputRef.current.value = ''; }}>✕</button>
                            </div>
                        )}

                        <div className="sp-input-row">
                            <button
                                className="sp-attach-btn"
                                type="button"
                                onClick={() => inputRef.current?.click()}
                                aria-label="Attach file"
                            >
                                <FiPaperclip size={18} />
                            </button>

                            <textarea
                                className="sp-textarea"
                                value={inputText}
                                onChange={(e) => setInputText(e.target.value)}
                                onKeyDown={handleKeyDown}
                                placeholder="Paste notes or describe what to study..."
                                rows={1}
                            />

                            <button
                                className="sp-send-btn"
                                type="button"
                                onClick={handleSend}
                                disabled={!inputText.trim() && !file}
                                aria-label="Send"
                            >
                                <IoSend size={18} />
                            </button>
                        </div>
                    </div>
                    <div className="sp-input-hint">Press Enter to send · Shift+Enter for new line</div>
                </div>
            </main>
        </div>
    );
}

export default StudyPage;