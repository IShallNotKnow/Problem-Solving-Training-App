import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

/**
 * Renders assistant output as Markdown + LaTeX + Mermaid.
 *
 * Requires:
 *   npm i react-markdown remark-gfm remark-math rehype-katex katex mermaid
 *
 * Security note: no `rehype-raw` here on purpose. Model output is untrusted, and
 * enabling raw HTML would open an XSS hole. Markdown-only keeps it safe.
 */

let mermaidPromise = null;
function loadMermaid(isDark) {
    // Loaded lazily so the ~500 kB mermaid bundle never blocks first paint.
    if (!mermaidPromise) {
        mermaidPromise = import('mermaid').then(({ default: mermaid }) => {
            mermaid.initialize({
                startOnLoad: false,
                securityLevel: 'strict',
                theme: isDark ? 'dark' : 'default',
                fontFamily: 'DM Sans, system-ui, sans-serif',
            });
            return mermaid;
        });
    }
    return mermaidPromise;
}

function Mermaid({ chart, isDark }) {
    const ref = useRef(null);
    const [failed, setFailed] = useState(false);
    const id = useMemo(() => `mmd-${Math.random().toString(36).slice(2)}`, []);

    useEffect(() => {
        let cancelled = false;
        loadMermaid(isDark)
            .then(m => m.render(id, chart))
            .then(({ svg }) => {
                if (!cancelled && ref.current) ref.current.innerHTML = svg;
            })
            .catch(() => {
                // A malformed diagram must never take the message down.
                if (!cancelled) setFailed(true);
            });
        return () => { cancelled = true; };
    }, [chart, id, isDark]);

    if (failed) {
        return <pre className="md-pre"><code>{chart}</code></pre>;
    }
    return <div className="md-mermaid" ref={ref} />;
}

export default function MarkdownMessage({ children, isDark = false }) {
    const text = typeof children === 'string' ? children : String(children ?? '');

    return (
        <div className="md-body">
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
                components={{
                    code({ inline, className, children, ...props }) {
                        const lang = /language-(\w+)/.exec(className || '')?.[1];
                        const value = String(children).replace(/\n$/, '');

                        if (!inline && lang === 'mermaid') {
                            return <Mermaid chart={value} isDark={isDark} />;
                        }
                        if (inline) {
                            return <code className="md-code-inline" {...props}>{children}</code>;
                        }
                        return (
                            <pre className="md-pre">
                                <code className={className} {...props}>{children}</code>
                            </pre>
                        );
                    },
                    a({ children, ...props }) {
                        return <a target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
                    },
                    table({ children, ...props }) {
                        return (
                            <div className="md-table-wrap">
                                <table {...props}>{children}</table>
                            </div>
                        );
                    },
                }}
            >
                {text}
            </ReactMarkdown>
        </div>
    );
}