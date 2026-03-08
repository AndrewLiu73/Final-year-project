import {
    LineChart, Line, XAxis, YAxis,
    Tooltip, Legend, ResponsiveContainer,
    CartesianGrid
} from 'recharts';
import { COIN_COLOURS } from '../utils/constants';

const ALL_COINS = ['BTC', 'ETH', 'HYPE'];

function CustomTooltip({ active, payload, label }) {
    if (!active || !payload || payload.length === 0) return null;
    return (
        <div style={{
            background:   '#2f3136',
            border:       '1px solid #202225',
            borderRadius: '6px',
            padding:      '8px 12px',
            fontSize:     '12px',
        }}>
            <div style={{ color: '#ffffff', marginBottom: '6px', fontWeight: 600 }}>{label}</div>
            {payload.map((entry, i) => (
                <div key={i} style={{ color: entry.color, marginBottom: '2px' }}>
                    {entry.name}: {entry.value.toFixed(1)}%
                </div>
            ))}
        </div>
    );
}

export default function BiasHistoryChart({ biasSummaries, period, selectedCoin, type }) {
    if (!biasSummaries || biasSummaries.length === 0) {
        return (
            <div style={{ textAlign: 'center', padding: '60px', color: '#72767d', fontSize: 14 }}>
                No data available for this period.
            </div>
        );
    }

    const filtered    = biasSummaries.slice(-period);
    const pickedCoins = (selectedCoin === 'ALL' || !selectedCoin) ? ALL_COINS : [selectedCoin];

    const chartData = filtered.map(item => {
        const ts  = item.timestamp;
        const agg = item.aggregate ?? item;

        const label = ts
            ? new Date(ts).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' })
            : '—';

        const row = { label };
        pickedCoins.forEach(coin => {
            row[coin] = type === 'SHORT'
                ? (agg[coin]?.short_pct ?? 0)
                : (agg[coin]?.long_pct  ?? 0);
        });
        return row;
    });

    return (
        <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" />
                <XAxis
                    dataKey="label"
                    tick={{ fill: '#72767d', fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                />
                <YAxis
                    domain={[0, 100]}
                    tickFormatter={v => `${v}%`}
                    tick={{ fill: '#72767d', fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    width={45}
                    label={{
                        value: '% Long or Short',
                        angle: -90,
                        position: 'insideLeft',
                        fill: '#72767d',
                        fontSize: 11,
                        offset: 10,
                    }}
                />
                <Tooltip content={<CustomTooltip />} />
                <Legend
                    verticalAlign="top"
                    wrapperStyle={{ color: '#b9bbbe', fontSize: '12px', paddingBottom: '8px' }}
                    formatter={(value) => (
                        <span style={{ color: '#b9bbbe' }}>
                            {value} {type === 'SHORT' ? 'Short %' : 'Long %'}
                        </span>
                    )}
                />
                {pickedCoins.map(coin => (
                    <Line
                        key={coin}
                        type="monotone"
                        dataKey={coin}
                        name={coin}
                        stroke={COIN_COLOURS[coin]}
                        strokeWidth={2}
                        dot={false}
                        activeDot={{ r: 5, fill: COIN_COLOURS[coin] }}
                    />
                ))}
            </LineChart>
        </ResponsiveContainer>
    );
}
