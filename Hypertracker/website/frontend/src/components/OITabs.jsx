import React, { useState, useEffect, useRef, useCallback } from 'react';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import styles from './OITabs.module.css';
import { COIN_COLOURS } from '../utils/constants';

const GREEN = '#3ba55d';
const RED   = '#ed4245';

const TREND_COLOURS = {
  'Building Long': '#3ba55d', 'Squeeze Risk': '#ed4245',
  'Crowded / Fragile': '#f0a500', 'Short Covering': '#00b4d8',
  'Deleveraging': '#72767d', 'Neutral': '#96989d',
};

const SIGNAL_TABLE = [
  { oi: '> +3%', px: '> +1%', label: 'Building Long'     },
  { oi: '> +3%', px: '< -1%', label: 'Squeeze Risk'      },
  { oi: '> +3%', px: 'flat',  label: 'Crowded / Fragile' },
  { oi: '< -3%', px: '> +1%', label: 'Short Covering'    },
  { oi: '< -3%', px: '< -1%', label: 'Deleveraging'      },
  { oi: 'flat',  px: 'flat',  label: 'Neutral'            },
];

const TABS = [
  { key: 'millionaire', label: 'Millionaire Bias' },
  { key: 'Hyperliquid', label: 'Hyperliquid OI'  },
  { key: 'Binance',     label: 'Binance OI'      },
  { key: 'Bybit',       label: 'Bybit OI'        },
  { key: 'OKX',         label: 'OKX OI'          },
  { key: 'Deribit',     label: 'Deribit OI'      },
];

// ── Fetchers ──────────────────────────────────────────────────────────────────
const TARGET_COINS = ['BTC', 'ETH'];

const fetchBinanceLive = () =>
  Promise.all(TARGET_COINS.map(async coin => {
    const s = `${coin}USDT`;
    const [oi, px] = await Promise.all([
      fetch(`https://fapi.binance.com/fapi/v1/openInterest?symbol=${s}`).then(r => r.json()),
      fetch(`https://fapi.binance.com/fapi/v1/premiumIndex?symbol=${s}`).then(r => r.json()),
    ]);
    return [coin, { oi_usd: parseFloat(oi.openInterest || 0) * parseFloat(px.markPrice || 0), mark_px: parseFloat(px.markPrice || 0) }];
  })).then(Object.fromEntries);

const fetchBybitLive = () =>
  Promise.all(TARGET_COINS.map(async coin => {
    const s = `${coin}USDT`;
    const [oi, px] = await Promise.all([
      fetch(`https://api.bybit.com/v5/market/open-interest?category=linear&symbol=${s}&intervalTime=5min&limit=1`).then(r => r.json()),
      fetch(`https://api.bybit.com/v5/market/tickers?category=linear&symbol=${s}`).then(r => r.json()),
    ]);
    const price = parseFloat(px.result?.list?.[0]?.markPrice || 0);
    return [coin, { oi_usd: parseFloat(oi.result?.list?.[0]?.openInterest || 0) * price, mark_px: price }];
  })).then(Object.fromEntries);

const fetchOKXLive = () =>
  Promise.all(TARGET_COINS.map(async coin => {
    const id = `${coin}-USDT-SWAP`;
    const [oi, px] = await Promise.all([
      fetch(`https://www.okx.com/api/v5/public/open-interest?instId=${id}`).then(r => r.json()),
      fetch(`https://www.okx.com/api/v5/public/mark-price?instId=${id}`).then(r => r.json()),
    ]);
    return [coin, { oi_usd: parseFloat(oi.data?.[0]?.oiUsd || 0), mark_px: parseFloat(px.data?.[0]?.markPx || 0) }];
  })).then(Object.fromEntries);

const fetchDeribitLive = () =>
  Promise.all(TARGET_COINS.map(async coin => {
    const { result = [] } = await fetch(
      `https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=${coin}&kind=future`
    ).then(r => r.json());
    const perp = result.find(i => i.instrument_name?.includes(`${coin}-PERPETUAL`)) || result[0];
    return [coin, { oi_usd: result.reduce((s, i) => s + parseFloat(i.open_interest || 0), 0), mark_px: parseFloat(perp?.mark_price || 0) }];
  })).then(Object.fromEntries);

const fetchHyperliquidLive = async () => {
  const data = await fetch('https://api.hyperliquid.xyz/info', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type: 'metaAndAssetCtxs' }),
  }).then(r => r.json());
  const HL_TARGETS = ['BTC', 'ETH', 'HYPE'];
  return Object.fromEntries(
    data[0].universe
      .map((asset, i) => [asset.name, data[1][i]])
      .filter(([name]) => HL_TARGETS.includes(name))
      .map(([name, ctx]) => {
        const px = parseFloat(ctx.markPx || 0);
        return [name, { oi_usd: parseFloat(ctx.openInterest || 0) * px, mark_px: px }];
      })
  );
};

const EXCHANGE_FETCHERS = { Binance: fetchBinanceLive, Bybit: fetchBybitLive, OKX: fetchOKXLive, Deribit: fetchDeribitLive, Hyperliquid: fetchHyperliquidLive };

// ── Shared Components ─────────────────────────────────────────────────────────
const PieTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const { name, value, payload: p } = payload[0];
  return (
    <div className={styles.tooltip}>
      <div style={{ color: '#fff', fontWeight: 700, marginBottom: 4 }}>{name}</div>
      <div style={{ color: '#b9bbbe' }}>${(value / 1e9).toFixed(3)}B</div>
      <div style={{ color: p.fill, fontWeight: 600 }}>{p.pct?.toFixed(1)}%</div>
    </div>
  );
};

const DonutChart = ({ data }) => (
  <ResponsiveContainer width="100%" height={260}>
    <PieChart>
      <Pie data={data} cx="50%" cy="50%" innerRadius={70} outerRadius={110} dataKey="value" paddingAngle={3}>
        {data.map((e, i) => <Cell key={i} fill={e.fill} />)}
      </Pie>
      <Tooltip content={<PieTooltip />} />
      <Legend formatter={(v, e) => (
        <span style={{ color: e.payload.fill, fontWeight: 700 }}>{v} — {e.payload.pct?.toFixed(1)}%</span>
      )} />
    </PieChart>
  </ResponsiveContainer>
);

const TrendBadge = ({ label }) => {
  if (!label) return null;
  const colour = TREND_COLOURS[label] || '#96989d';
  return (
    <span className={styles.trendBadgeWrapper}>
      <span className={styles.trendBadge} style={{ background: colour + '22', color: colour, border: `1px solid ${colour}55`, cursor: 'pointer' }}>
        {label}
      </span>
      <div className={styles.trendTable}>
        <div className={styles.trendTableTitle}>Signal Reference</div>
        <div className={styles.trendTableGrid}>
          <div className={styles.trendTableHeader}>OI Change</div>
          <div className={styles.trendTableHeader}>Price Change</div>
          <div className={styles.trendTableHeader}>Signal</div>
          {SIGNAL_TABLE.map((row, i) => {
            const active = row.label === label;
            const rc = TREND_COLOURS[row.label] || '#96989d';
            return (
              <React.Fragment key={i}>
                <div className={`${styles.trendTableCell} ${active ? styles.trendTableCellActive : ''}`}>{row.oi}</div>
                <div className={`${styles.trendTableCell} ${active ? styles.trendTableCellActive : ''}`}>{row.px}</div>
                <div className={`${styles.trendTableCell} ${active ? styles.trendTableCellActive : ''}`} style={{ color: rc, fontWeight: 700 }}>{row.label}</div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </span>
  );
};

// ── Tabs ──────────────────────────────────────────────────────────────────────
function ExchangeTab({ exchange, backendData, cachedData, onDataFetched }) {
  const [liveData, setLiveData] = useState(cachedData || null);
  const [loading,  setLoading]  = useState(!cachedData);
  const [error,    setError]    = useState(null);

  useEffect(() => {
    if (cachedData) { setLiveData(cachedData); setLoading(false); return; }
    EXCHANGE_FETCHERS[exchange]()
      .then(d  => { setLiveData(d); onDataFetched(exchange, d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [exchange, cachedData, onDataFetched]);

  if (loading) return <div className={styles.loadingWrapper}><div className={styles.spinner} /> Fetching live OI from {exchange}...</div>;
  if (error)   return <div style={{ color: RED, padding: 20 }}>Error: {error}</div>;
  if (!liveData) return null;

  const entries = Object.entries(liveData).sort((a, b) => b[1].oi_usd - a[1].oi_usd);
  const totalOI = entries.reduce((s, [, v]) => s + v.oi_usd, 0);
  const pieData = entries.map(([coin, v]) => ({
    name: coin, value: v.oi_usd,
    pct:  totalOI > 0 ? v.oi_usd / totalOI * 100 : 0,
    fill: COIN_COLOURS[coin] || '#72767d',
  }));

  return (
    <div className={styles.grid2}>
      <div className={styles.card}>
        <div className={styles.cardTitle}>Live OI — {exchange} (USD)</div>
        <DonutChart data={pieData} />
        <div className={styles.totalLabel}>Total {exchange} OI: ${(totalOI / 1e9).toFixed(3)}B</div>
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Asset Breakdown + OI Change</div>
        <div className={styles.assetList}>
          {entries.map(([coin, v]) => {
            const b      = backendData?.[coin]?.find(d => d.exchange?.toLowerCase() === exchange.toLowerCase());
            const chg    = b?.change_pct_30min ?? null;
            const px_chg = b?.px_change_30min  ?? null;
            const fmt    = (val) => val === null ? '—' : `${val >= 0 ? '+' : ''}${val.toFixed(2)}%`;
            const clr    = (val) => val === null ? '#96989d' : val >= 0 ? GREEN : RED;
            return (
              <div key={coin} className={styles.assetCard} style={{ border: `1px solid ${COIN_COLOURS[coin] || '#202225'}33` }}>
                <div className={styles.assetCardHeader}>
                  <div style={{ color: COIN_COLOURS[coin], fontWeight: 800, fontSize: 16 }}>{coin}</div>
                  <TrendBadge label={b?.trend_label ?? null} />
                </div>
                <div className={styles.assetCardGrid}>
                  {[
                    ['Live OI (USD)',       `$${(v.oi_usd / 1e9).toFixed(3)}B`,         null    ],
                    ['Mark Price',          `$${v.mark_px.toLocaleString()}`,             null    ],
                    ['OI Change (30m)',     fmt(chg),                                     clr(chg)],
                    ['Price Change (30m)', fmt(px_chg),                                  clr(px_chg)],
                  ].map(([label, val, color]) => (
                    <div key={label}>
                      <div className={styles.statLabel}>{label}</div>
                      <div className={styles.statValue} style={color ? { color, fontWeight: 700, fontSize: 16 } : {}}>{val}</div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function MillionaireTab({ aggregate }) {
  const coins    = Object.entries(aggregate);
  if (!coins.length) return <p style={{ color: '#96989d', padding: 20 }}>No data</p>;

  const totalLong  = coins.reduce((s, [, v]) => s + (v.long  || 0), 0);
  const totalShort = coins.reduce((s, [, v]) => s + (v.short || 0), 0);
  const totalOI    = totalLong + totalShort;
  const lsPct      = totalOI > 0 ? totalLong / totalOI * 100 : 50;

  const lsData   = [
    { name: 'Long',  value: totalLong,  pct: lsPct,         fill: GREEN },
    { name: 'Short', value: totalShort, pct: 100 - lsPct,   fill: RED   },
  ];
  const coinData = coins
    .map(([coin, v]) => ({ name: coin, value: (v.long || 0) + (v.short || 0), pct: totalOI > 0 ? ((v.long || 0) + (v.short || 0)) / totalOI * 100 : 0, fill: COIN_COLOURS[coin] || '#72767d' }))
    .sort((a, b) => b.value - a.value);

  return (
    <div className={styles.grid2}>
      <div className={styles.card}>
        <div className={styles.cardTitle}>Long / Short Split</div>
        <DonutChart data={lsData} />
        <div className={styles.totalLabel}>Total tracked exposure: ${(totalOI / 1e9).toFixed(3)}B</div>
      </div>
      <div className={styles.card}>
        <div className={styles.cardTitle}>Exposure by Asset</div>
        <DonutChart data={coinData} />
      </div>
    </div>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────
export default function OITabs({ aggregate }) {
  const [tab,         setTab]         = useState('millionaire');
  const [backendData, setBackendData] = useState(null);
  const exchangeCache                 = useRef({});

  const handleDataFetched = useCallback((exchange, data) => {
    exchangeCache.current[exchange] = { data, ts: Date.now() };
  }, []);

  useEffect(() => {
    fetch('http://localhost:8000/api/exchange-oi')
      .then(r  => r.json())
      .then(setBackendData)
      .catch(e => console.error('Backend OI fetch failed:', e));
  }, []);

  return (
    <div>
      <div className={styles.tabBar}>
        {TABS.map(t => (
          <button key={t.key} className={`${styles.tab} ${tab === t.key ? styles.active : ''}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'millionaire' && <MillionaireTab aggregate={aggregate} />}
      {['Hyperliquid', 'Binance', 'Bybit', 'OKX', 'Deribit'].map(ex => {
        const cached = exchangeCache.current[ex];
        return tab === ex && (
          <ExchangeTab key={ex} exchange={ex} backendData={backendData}
            cachedData={(cached && Date.now() - cached.ts < 60000) ? cached.data : null}
            onDataFetched={handleDataFetched}
          />
        );
      })}
    </div>
  );
}
