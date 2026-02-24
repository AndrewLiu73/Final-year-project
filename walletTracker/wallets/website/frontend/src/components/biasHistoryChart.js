import React from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend
} from "chart.js";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

const COIN_COLOURS = {
  BTC:  '#f7931a',
  ETH:  '#627eea',
  HYPE: '#5865f2',
};

const ALL_COINS = ['BTC', 'ETH', 'HYPE'];

// biasSummaries = full items with { timestamp, aggregate: { BTC: {...}, ETH: {...} } }
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

  // Use real dates for X axis
  const labels = filtered.map(item => {
    const ts = item.timestamp;
    if (!ts) return '—';
    const d = new Date(ts);
    return d.toLocaleDateString('en-GB', { month: 'short', day: 'numeric' });
  });

  const datasets = pickedCoins.map(coin => ({
    label: `${coin} ${type === 'SHORT' ? 'Short %' : 'Long %'}`,
    data: filtered.map(item => {
      const agg = item.aggregate ?? item; // support both shapes
      return type === 'SHORT'
        ? (agg[coin]?.short_pct ?? 0)
        : (agg[coin]?.long_pct  ?? 0);
    }),
    borderColor:      COIN_COLOURS[coin],
    backgroundColor:  `${COIN_COLOURS[coin]}18`,
    fill:             false,
    tension:          0.3,
    pointRadius:      3,
    pointHoverRadius: 6,
    borderWidth:      2,
  }));

  return (
    <Line
      data={{ labels, datasets }}
      options={{
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            position: 'top',
            labels: {
              color:           '#b9bbbe',
              usePointStyle:   true,
              pointStyleWidth: 16,
              padding:         20,
            },
          },
          tooltip: {
            backgroundColor: '#2f3136',
            titleColor:      '#ffffff',
            bodyColor:       '#b9bbbe',
            borderColor:     '#202225',
            borderWidth:     1,
            callbacks: {
              label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%`,
            },
          },
        },
        scales: {
          x: {
            ticks: {
              color:    '#72767d',
              maxTicksLimit: 12,
              maxRotation:   45,
            },
            grid: { color: 'rgba(255,255,255,0.05)' },
          },
          y: {
            min:   0,
            max:   100,
            ticks: { color: '#72767d', callback: v => `${v}%` },
            grid:  { color: 'rgba(255,255,255,0.05)' },
            title: { display: true, text: '% Long or Short', color: '#72767d' },
          },
        },
      }}
    />
  );
}
