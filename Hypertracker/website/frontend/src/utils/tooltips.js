export function tooltipDate(ts, period) {
    const d = new Date(ts);
    if (period === '1D') return d.toLocaleTimeString('en-IE', { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString('en-IE', { month: 'short', day: 'numeric', year: period === 'All' ? 'numeric' : undefined });
}

export function TooltipBox({ label, dark = false, children }) {
    return (
        <div style={{
            background: dark ? '#18191c' : '#2f3136',
            border: `1px solid ${dark ? '#40444b' : '#202225'}`,
            borderRadius: '6px', padding: '8px 12px', fontSize: '12px',
        }}>
            {label && <div style={{ color: '#96989d', marginBottom: '4px', fontWeight: 600 }}>{label}</div>}
            {children}
        </div>
    );
}
