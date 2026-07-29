import { Component } from 'react';
import { FiAlertTriangle } from 'react-icons/fi';

/**
 * Catches render-time exceptions anywhere below it. Without this, a single
 * bad field (e.g. an undefined questions array) unmounts the whole React
 * tree and the user sees a blank white page with no way to recover.
 */
export default class ErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { error: null };
    }

    static getDerivedStateFromError(error) {
        return { error };
    }

    componentDidCatch(error, info) {
        console.error('Unhandled render error:', error, info?.componentStack);
    }

    handleReload = () => {
        this.setState({ error: null });
        window.location.reload();
    };

    render() {
        if (!this.state.error) return this.props.children;

        return (
            <div className="eb-wrap" role="alert">
                <div className="eb-card">
                    <div className="eb-icon">
                        <FiAlertTriangle size={26} />
                    </div>
                    <h1 className="eb-title">Something went wrong</h1>
                    <p className="eb-sub">
                        This page hit an unexpected error. Reloading usually fixes it.
                    </p>
                    <div className="eb-actions">
                        <button className="eb-btn eb-btn--primary" onClick={this.handleReload}>
                            Reload page
                        </button>
                        <a className="eb-btn eb-btn--ghost" href="/dashboard">
                            Back to dashboard
                        </a>
                    </div>
                </div>
            </div>
        );
    }
}