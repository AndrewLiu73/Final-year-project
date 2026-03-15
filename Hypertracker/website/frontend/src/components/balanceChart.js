import { useState, useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { formatBalance } from '../utils/formatters';
import { TooltipBox, tooltipDate } from '../utils/tooltips';

const timeframes = ['1D','1W','1M','All'];
const key = { '1D': 'day', '1W': 'week', '1M': 'month', 'All': 'allTime' };

const btn = (active, small) => ({
    padding: small ? '4px 8px' : '4px 10px', borderRadius: '4px', border: 'none',
    cursor: 'pointer', fontSize: small ? '11px' : '12px', fontWeight: 600,
    background: active ? (small ? '#40444b' : '#5865f2') : 'transparent',
    color: active ? 'white' : '#96989d', transition: 'background 0.15s',
});

function CustomTooltip({ active, payload, color, period }) {
    if (!active || !payload?.[0]) return null;
    const { time, value } = payload[0].payload;
    return (
        <TooltipBox label={tooltipDate(time, period)} dark>
            <div style={{ color, fontWeight: 700 }}>{formatBalance(value)}</div>
        </TooltipBox>
    );
}

export default function HistoryChart({ historicalPnl, historicalBalance }) {
    const [mode, setMode]     = useState('pnl');
    const [period, setPeriod] = useState('1W');

    const chartData = useMemo(() => {
        const source = (mode === 'pnl' ? historicalPnl : historicalBalance)?.[key[period]];
        if (!source) return [];
        return source.map(item => ({
            time:  typeof item.timestamp === 'object' ? parseInt(item.timestamp.$numberLong) : item.timestamp,
            value: mode === 'pnl' ? item.pnl : item.balance,
        }));
    }, [mode, period, historicalPnl, historicalBalance]);

    const tickFormatter = ts => {
        const d = new Date(ts);
        if (period === '1D')  return d.toLocaleTimeString('en-IE', { hour: '2-digit', minute: '2-digit' });
        if (period === 'All') return d.toLocaleDateString('en-IE', { month: 'short', year: '2-digit' });
        return d.toLocaleDateString('en-IE', { month: 'short', day: 'numeric' });
    };

    const isUp      = chartData.length > 1 ? chartData.at(-1).value >= chartData[0].value : true;
    const lineColor = mode === 'balance' ? '#5865f2' : (isUp ? '#3ba55d' : '#ed4245');

    if (!historicalPnl && !historicalBalance) return null;

    return (
        <div style={{ background: '#2f3136', borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <div style={{ display: 'flex', gap: '4px' }}>
                    {['pnl', 'balance'].map(m => (
                        <button key={m} onClick={() => setMode(m)} style={btn(mode === m, false)}>
                            {m === 'pnl' ? 'PnL' : 'Balance'}
                        </button>
                    ))}
                </div>
                <div style={{ display: 'flex', gap: '4px' }}>
                    {timeframes.map(p => (
                        <button key={p} onClick={() => setPeriod(p)} style={btn(period === p, true)}>{p}</button>
                    ))}
                </div>
            </div>
            {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                    <LineChart data={chartData} margin={{ top: 5, right: 10, left: 5, bottom: 0 }}>
                        <XAxis dataKey="time" type="number" scale="time" domain={['dataMin','dataMax']}
                            tickFormatter={tickFormatter} tick={{ fill: '#96989d', fontSize: 10 }} tickLine={false} axisLine={false} tickCount={6} />
                        <YAxis tickFormatter={formatBalance} tick={{ fill: '#96989d', fontSize: 10 }} tickLine={false} axisLine={false} width={60} />
                        <Tooltip content={<CustomTooltip color={lineColor} period={period} />} />
                        <ReferenceLine y={0} stroke="#40444b" strokeDasharray="3 3" />
                        <Line type="monotone" dataKey="value" stroke={lineColor} strokeWidth={2} dot={false} activeDot={{ r: 4, fill: lineColor }} />
                    </LineChart>
                </ResponsiveContainer>
            ) : (
                <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#96989d', fontSize: '13px' }}>
                    No data for this period
                </div>
            )}
        </div>
    );
}
