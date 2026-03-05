import { useState, useMemo } from 'react';
import {
    LineChart, Line, XAxis, YAxis,
    Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';

const PERIODS     = ['1D', '1W', '1M', 'All'];
const PERIOD_KEYS = { '1D': 'day', '1W': 'week', '1M': 'month', 'All': 'allTime' };

function formatY(val) {
    const abs = Math.abs(val);
    const sign = val < 0 ? '-' : '';
    if (abs >= 1_000_000_000_000) return `${sign}$${(abs / 1_000_000_000_000).toFixed(2)}T`;
    if (abs >= 1_000_000_000)     return `${sign}$${(abs / 1_000_000_000).toFixed(2)}B`;
    if (abs >= 1_000_000)         return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000)             return `${sign}$${(abs / 1_000).toFixed(1)}K`;
    return `${sign}$${abs.toFixed(0)}`;
}

function CustomTooltip({ active, payload, color, period }) {
    if (!active || !payload || !payload[0]) return null;
    const d = payload[0].payload;

    const date  = new Date(d.time);
    const label = period === '1D'
        ? date.toLocaleTimeString('en-IE', { hour: '2-digit', minute: '2-digit' })
        : date.toLocaleDateString('en-IE', { month: 'short', day: 'numeric', year: period === 'All' ? 'numeric' : undefined });

    return (
        <div style={{
            background: '#18191c', border: '1px solid #40444b',
            padding: '8px 12px', borderRadius: '6px', fontSize: '12px'
        }}>
            <div style={{ color: '#96989d', marginBottom: '4px' }}>{label}</div>
            <div style={{ color: color, fontWeight: 700 }}>{formatY(d.value)}</div>
        </div>
    );
}

export default function HistoryChart({ historicalPnl, historicalBalance }) {
    const [mode, setMode]     = useState('pnl');
    const [period, setPeriod] = useState('1W');

    const periodKey = PERIOD_KEYS[period];

    const chartData = useMemo(() => {
        const source = mode === 'pnl' ? historicalPnl : historicalBalance;
        if (!source || !source[periodKey]) return [];

        return source[periodKey].map(item => {
            const ts = typeof item.timestamp === 'object'
                ? parseInt(item.timestamp.$numberLong)
                : item.timestamp;

            return {
                time:  ts,
                value: mode === 'pnl' ? item.pnl : item.balance,
            };
        });
    }, [mode, period, historicalPnl, historicalBalance, periodKey]);

    const tickFormatter = (ts) => {
        const date = new Date(ts);
        if (period === '1D')  return date.toLocaleTimeString('en-IE', { hour: '2-digit', minute: '2-digit' });
        if (period === 'All') return date.toLocaleDateString('en-IE', { month: 'short', year: '2-digit' });
        return date.toLocaleDateString('en-IE', { month: 'short', day: 'numeric' });
    };

    const isUp = chartData.length > 1
        ? chartData[chartData.length - 1].value >= chartData[0].value
        : true;

    const lineColor = mode === 'balance'
        ? '#5865f2'
        : (isUp ? '#3ba55d' : '#ed4245');

    if (!historicalPnl && !historicalBalance) return null;

    return (
        <div style={{
            background: '#2f3136', borderRadius: '8px',
            padding: '16px', marginBottom: '20px'
        }}>
            <div style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginBottom: '12px'
            }}>
                <div style={{ display: 'flex', gap: '4px' }}>
                    {['pnl', 'balance'].map(m => (
                        <button
                            key={m}
                            onClick={() => setMode(m)}
                            style={{
                                padding: '4px 10px', borderRadius: '4px',
                                border: 'none', cursor: 'pointer',
                                fontSize: '12px', fontWeight: 600,
                                background: mode === m ? '#5865f2' : '#40444b',
                                color: mode === m ? 'white' : '#96989d',
                                transition: 'background 0.15s',
                            }}
                        >
                            {m === 'pnl' ? 'PnL' : 'Balance'}
                        </button>
                    ))}
                </div>

                <div style={{ display: 'flex', gap: '4px' }}>
                    {PERIODS.map(p => (
                        <button
                            key={p}
                            onClick={() => setPeriod(p)}
                            style={{
                                padding: '4px 8px', borderRadius: '4px',
                                border: 'none', cursor: 'pointer',
                                fontSize: '11px', fontWeight: 600,
                                background: period === p ? '#40444b' : 'transparent',
                                color: period === p ? 'white' : '#96989d',
                                transition: 'background 0.15s',
                            }}
                        >
                            {p}
                        </button>
                    ))}
                </div>
            </div>

            {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                    <LineChart data={chartData} margin={{ top: 5, right: 10, left: 5, bottom: 0 }}>
                        <XAxis
                            dataKey="time"
                            type="number"
                            scale="time"
                            domain={['dataMin', 'dataMax']}
                            tickFormatter={tickFormatter}
                            tick={{ fill: '#96989d', fontSize: 10 }}
                            tickLine={false}
                            axisLine={false}
                            tickCount={6}
                        />
                        <YAxis
                            tickFormatter={formatY}
                            tick={{ fill: '#96989d', fontSize: 10 }}
                            tickLine={false}
                            axisLine={false}
                            width={60}
                        />
                        <Tooltip content={<CustomTooltip color={lineColor} period={period} />} />
                        <ReferenceLine y={0} stroke="#40444b" strokeDasharray="3 3" />
                        <Line
                            type="monotone"
                            dataKey="value"
                            stroke={lineColor}
                            strokeWidth={2}
                            dot={false}
                            activeDot={{ r: 4, fill: lineColor }}
                        />
                    </LineChart>
                </ResponsiveContainer>
            ) : (
                <div style={{
                    height: 200, display: 'flex',
                    alignItems: 'center', justifyContent: 'center',
                    color: '#96989d', fontSize: '13px'
                }}>
                    No data for this period
                </div>
            )}
        </div>
    );
}
