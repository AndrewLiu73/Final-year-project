import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from 'recharts';
import { COIN_COLOURS } from '../utils/constants';
import { TooltipBox } from '../utils/tooltips';

const coins = ['BTC', 'ETH', 'HYPE'];

function CustomTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null;
    return (
        <TooltipBox label={label}>
            {payload.map((e, i) => (
                <div key={i} style={{ color: e.color, marginBottom: '2px' }}>
                    {e.name}: {e.value.toFixed(1)}%
                </div>
            ))}
        </TooltipBox>
    );
}

export default function BiasHistoryChart({ biasSummaries, period, selectedCoin, type }) {
    if (!biasSummaries?.length) return (
        <div style={{ textAlign: 'center', padding: '60px', color: '#72767d', fontSize: 14 }}>
            No data available for this period.
        </div>
    );

    const coins2     = (!selectedCoin || selectedCoin === 'ALL') ? coins : [selectedCoin];
    const chartData = biasSummaries.slice(-period).map(item => {
        const agg = item.aggregate ?? item;
        const row = { label: item.timestamp ? new Date(item.timestamp).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' }) : '—' };
        coins2.forEach(coin => { row[coin] = agg[coin]?.[type === 'SHORT' ? 'short_pct' : 'long_pct'] ?? 0; });
        return row;
    });

    return (
        <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="label" tick={{ fill: '#72767d', fontSize: 11 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} tick={{ fill: '#72767d', fontSize: 11 }}
                    tickLine={false} axisLine={false} width={45}
                    label={{ value: '% Long or Short', angle: -90, position: 'insideLeft', fill: '#72767d', fontSize: 11, offset: 10 }} />
                <Tooltip content={<CustomTooltip />} />
                <Legend verticalAlign="top" wrapperStyle={{ color: '#b9bbbe', fontSize: '12px', paddingBottom: '8px' }}
                    formatter={value => <span style={{ color: '#b9bbbe' }}>{value} {type === 'SHORT' ? 'Short %' : 'Long %'}</span>} />
                {coins.map(coin => (
                    <Line key={coin} type="monotone" dataKey={coin} name={coin} stroke={COIN_COLOURS[coin]}
                        strokeWidth={2} dot={false} activeDot={{ r: 5, fill: COIN_COLOURS[coin] }} />
                ))}
            </LineChart>
        </ResponsiveContainer>
    );
}
