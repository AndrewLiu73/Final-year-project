import React from 'react';

// class component because react doesn't have a hook for error boundaries yet.
// wraps the routes so if any page component throws, we get a fallback UI
// instead of a blank white screen
class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, info) {
        console.error('ErrorBoundary caught:', error, info);
    }

    render() {
        if (this.state.hasError) {
            return (
                <div style={{
                    display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center',
                    minHeight: '60vh', color: '#b9bbbe', gap: '16px',
                }}>
                    <h2 style={{ color: '#ed4245', margin: 0 }}>Something went wrong</h2>
                    <p style={{ color: '#96989d', fontSize: '14px', maxWidth: '400px', textAlign: 'center' }}>
                        {this.state.error?.message || 'An unexpected error occurred.'}
                    </p>
                    <button
                        onClick={() => window.location.reload()}
                        style={{
                            background: '#5865f2', color: 'white', border: 'none',
                            borderRadius: '4px', padding: '8px 20px',
                            cursor: 'pointer', fontWeight: 600, fontSize: '14px',
                        }}
                    >
                        Reload Page
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}

export default ErrorBoundary;
