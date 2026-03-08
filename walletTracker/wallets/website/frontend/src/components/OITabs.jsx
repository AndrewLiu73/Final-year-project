import React, { useState, useEffect, useRef } from 'react';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import styles from './OITabs.module.css';
import { COIN_COLOURS } from '../utils/constants';
import API_BASE from '../config';

const GREEN = '#3ba55d';
const RED = '#ed4245';

const TREND_COLOURS = {
  'Building Long': '#3ba55d',
  'Squeeze Risk': '#ed4245',
  'Crowded / Fragile': '#f0a500',
  'Short Covering': '#00b4d8',
  'Deleveraging': '#72767d',
  'Neutral': '#96989d',
};

const TARGET_COINS = ['BTC', 'ETH'];

async function fetchBinanceLive() {
  const results = {};
  await Promise.all(TARGET_COINS.map(async coin => {
    const symbol = `${coin}USDT`;
    const [oiRes, pxRes] = await Promise.all([
      fetch(`https://fapi.binance.com/fapi/v1/openInterest?symbol=${symbol}`),
      fetch(`https://fapi.binance.com/fapi/v1/premiumIndex?symbol=${symbol}`),
    ]);
    const oiData = await oiRes.json();
    const pxData = await pxRes.json();
    const oi     = parseFloat(oiData.openInterest || 0);
    const px     = parseFloat(pxData.markPrice    || 0);
    results[coin] = { oi_usd: oi * px, mark_px: px };
  }));
  return results;
}

async function fetchBybitLive() {
  const results = {};
  await Promise.all(TARGET_COINS.map(async coin => {
    const symbol = `${coin}USDT`;
    const [oiRes, pxRes] = await Promise.all([
      fetch(`https://api.bybit.com/v5/market/open-interest?category=linear&symbol=${symbol}&intervalTime=5min&limit=1`),
      fetch(`https://api.bybit.com/v5/market/tickers?category=linear&symbol=${symbol}`),
    ]);
    const oiData = await oiRes.json();
    const pxData = await pxRes.json();
    const oi     = parseFloat(oiData.result?.list?.[0]?.openInterest || 0);
    const px     = parseFloat(pxData.result?.list?.[0]?.markPrice    || 0);
    results[coin] = { oi_usd: oi * px, mark_px: px };
  }));
  return results;
}

async function fetchOKXLive() {
  const results = {};
  await Promise.all(TARGET_COINS.map(async coin => {
    const instId = `${coin}-USDT-SWAP`;
    const [oiRes, pxRes] = await Promise.all([
      fetch(`https://www.okx.com/api/v5/public/open-interest?instId=${instId}`),
      fetch(`https://www.okx.com/api/v5/public/mark-price?instId=${instId}`),
    ]);
    const oiData = await oiRes.json();
    const pxData = await pxRes.json();
    const oi_usd = parseFloat(oiData.data?.[0]?.oiUsd  || 0);
    const px     = parseFloat(pxData.data?.[0]?.markPx || 0);
    results[coin] = { oi_usd, mark_px: px };
  }));
  return results;
}

async function fetchDeribitLive() {
  const results = {};
  await Promise.all(TARGET_COINS.map(async coin => {
    const res   = await fetch(
      `https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=${coin}&kind=future`
    );
    const data  = await res.json();
    const items = data.result || [];
    const total_oi = items.reduce((s, i) => s + parseFloat(i.open_interest || 0), 0);
    const perp     = items.find(i => i.instrument_name?.includes(`${coin}-PERPETUAL`)) || items[0];
    const mark_px  = parseFloat(perp?.mark_price || 0);
    results[coin] = { oi_usd: total_oi, mark_px };
  }));
  return results;
}

async function fetchHyperliquidLive() {
  const HL_TARGETS = ['BTC', 'ETH', 'HYPE'];
  const res  = await fetch('https://api.hyperliquid.xyz/info', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ type: 'metaAndAssetCtxs' }),
  });
  const data = await res.json();
  const meta = data[0].universe;
  const ctxs = data[1];
  const results = {};
  meta.forEach((asset, i) => {
    if (HL_TARGETS.includes(asset.name)) {
      const ctx = ctxs[i];
      const oi  = parseFloat(ctx.openInterest || 0);
      const px  = parseFloat(ctx.markPx       || 0);
      results[asset.name] = { oi_usd: oi * px, mark_px: px };
    }
  });
  return results;
}

const EXCHANGE_FETCHERS = {
  Binance:     fetchBinanceLive,
  Bybit:       fetchBybitLive,
  OKX:         fetchOKXLive,
  Deribit:     fetchDeribitLive,
  Hyperliquid: fetchHyperliquidLive,
};

function PieTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { name, value, payload: p } = payload[0];
  return (
    <div className={styles.tooltip}>
      <div style={{ color: '#fff', fontWeight: 700, marginBottom: 4 }}>{name}</div>
      <div style={{ color: '#b9bbbe' }}>${(value / 1e9).toFixed(3)}B</div>
      <div style={{ color: p.fill, fontWeight: 600 }}>{p.pct?.toFixed(1)}%</div>
    </div>
  );
}

function TrendBadge({ label }) {
  if (!label) return null;
  const colour = TREND_COLOURS[label] || '#96989d';

  const SIGNAL_TABLE = [
    { oi: '> +3%', px: '> +1%', label: 'Building Long'     },
    { oi: '> +3%', px: '< -1%', label: 'Squeeze Risk'      },
    { oi: '> +3%', px: 'flat',  label: 'Crowded / Fragile' },
    { oi: '< -3%', px: '> +1%', label: 'Short Covering'    },
    { oi: '< -3%', px: '< -1%', label: 'Deleveraging'      },
    { oi: 'flat',  px: 'flat',  label: 'Neutral'            },
  ];

  return (
    <span className={styles.trendBadgeWrapper}>
      <span
        className={styles.trendBadge}
        style={{
          background: colour + '22',
          color:      colour,
          border:     `1px solid ${colour}55`,
          cursor:     'pointer',
        }}
      >
        {label}
      </span>

      <div className={styles.trendTable}>
        <div className={styles.trendTableTitle}>Signal Reference</div>
        <div className={styles.trendTableGrid}>
          <div className={styles.trendTableHeader}>OI Change</div>
          <div className={styles.trendTableHeader}>Price Change</div>
          <div className={styles.trendTableHeader}>Signal</div>
          {SIGNAL_TABLE.map((row, i) => {
            const rowColour = TREND_COLOURS[row.label] || '#96989d';
            const isActive  = row.label === label;
            return (
              <React.Fragment key={i}>
                <div className={`${styles.trendTableCell} ${isActive ? styles.trendTableCellActive : ''}`}>
                  {row.oi}
                </div>
                <div className={`${styles.trendTableCell} ${isActive ? styles.trendTableCellActive : ''}`}>
                  {row.px}
                </div>
                <div
                  className={`${styles.trendTableCell} ${isActive ? styles.trendTableCellActive : ''}`}
                  style={{ color: rowColour, fontWeight: 700 }}
                >
                  {row.label}
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </span>
  );
}


function ExchangeTab({ exchange, backendData, cachedData, onDataFetched }) {
  const [liveData, setLiveData] = useState(cachedData || null);
  const [loading, setLoading] = useState(!cachedData);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (cachedData) {
      setLiveData(cachedData);
      setLoading(false);
      return;
    }
    const fetcher = EXCHANGE_FETCHERS[exchange];
    fetcher()
      .then(d  => { setLiveData(d); onDataFetched(exchange, d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [exchange, cachedData, onDataFetched]);

  if (loading) return (
    <div className={styles.loadingWrapper}>
      <div className={styles.spinner}></div>
      Fetching live OI from {exchange}...
    </div>
  );
  if (error)     return <div style={{ color: RED, padding: 20 }}>Error: {error}</div>;
  if (!liveData) return null;

  const entries = Object.entries(liveData).sort((a, b) => b[1].oi_usd - a[1].oi_usd);
  const totalOI = entries.reduce((s, [, v]) => s + v.oi_usd, 0);

  const pieData = entries.map(([coin, v]) => ({
    name:  coin,
    value: v.oi_usd,
    pct:   totalOI > 0 ? (v.oi_usd / totalOI * 100) : 0,
    fill:  COIN_COLOURS[coin] || '#72767d',
  }));

  return (
    <div className={styles.grid2}>
      <div className={styles.card}>
        <div className={styles.cardTitle}>Live OI — {exchange} (USD)</div>
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={pieData} cx="50%" cy="50%" innerRadius={70} outerRadius={110}
              dataKey="value" paddingAngle={3}>
              {pieData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
            </Pie>
            <Tooltip content={<PieTooltip />} />
            <Legend formatter={(v, e) => (
              <span style={{ color: e.payload.fill, fontWeight: 700 }}>
                {v} — {e.payload.pct?.toFixed(1)}%
              </span>
            )} />
          </PieChart>
        </ResponsiveContainer>
        <div className={styles.totalLabel}>
          Total {exchange} OI: ${(totalOI / 1e9).toFixed(3)}B
        </div>
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Asset Breakdown + OI Change</div>
        <div className={styles.assetList}>
          {entries.map(([coin, v]) => {
            const backend = backendData?.[coin]?.find(
              d => d.exchange?.toLowerCase() === exchange.toLowerCase()
            );
            const chg    = backend?.change_pct_30min ?? null;
            const label  = backend?.trend_label      ?? null;
            const px_chg = backend?.px_change_30min  ?? null;

            return (
              <div
                key={coin}
                className={styles.assetCard}
                style={{ border: `1px solid ${COIN_COLOURS[coin] || '#202225'}33` }}
              >
                <div className={styles.assetCardHeader}>
                  <div style={{ color: COIN_COLOURS[coin], fontWeight: 800, fontSize: 16 }}>{coin}</div>
                  <TrendBadge label={label} />
                </div>
                <div className={styles.assetCardGrid}>
                  <div>
                    <div className={styles.statLabel}>Live OI (USD)</div>
                    <div className={styles.statValue}>${(v.oi_usd / 1e9).toFixed(3)}B</div>
                  </div>
                  <div>
                    <div className={styles.statLabel}>Mark Price</div>
                    <div className={styles.statValue}>${v.mark_px.toLocaleString()}</div>
                  </div>
                  <div>
                    <div className={styles.statLabel}>OI Change (30m)</div>
                    <div style={{
                      fontSize: 16, fontWeight: 700,
                      color: chg === null ? '#96989d' : chg >= 0 ? GREEN : RED,
                    }}>
                      {chg === null ? '—' : `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`}
                    </div>
                  </div>
                  <div>
                    <div className={styles.statLabel}>Price Change (30m)</div>
                    <div style={{
                      fontSize: 16, fontWeight: 700,
                      color: px_chg === null ? '#96989d' : px_chg >= 0 ? GREEN : RED,
                    }}>
                      {px_chg === null ? '—' : `${px_chg >= 0 ? '+' : ''}${px_chg.toFixed(2)}%`}
                    </div>
                  </div>
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
  const coins = Object.entries(aggregate);
  if (!coins.length) return <p style={{ color: '#96989d', padding: 20 }}>No data</p>;

  const totalLong  = coins.reduce((s, [, v]) => s + (v.long  || 0), 0);
  const totalShort = coins.reduce((s, [, v]) => s + (v.short || 0), 0);
  const totalOI    = totalLong + totalShort;
  const lsPct      = totalOI > 0 ? (totalLong / totalOI * 100) : 50;

  const lsData = [
    { name: 'Long',  value: totalLong,  pct: lsPct,       fill: GREEN },
    { name: 'Short', value: totalShort, pct: 100 - lsPct, fill: RED   },
  ];

  const coinData = coins
    .map(([coin, v]) => ({
      name:  coin,
      value: (v.long || 0) + (v.short || 0),
      pct:   totalOI > 0 ? (((v.long || 0) + (v.short || 0)) / totalOI * 100) : 0,
      fill:  COIN_COLOURS[coin] || '#72767d',
    }))
    .sort((a, b) => b.value - a.value);

  return (
    <div className={styles.grid2}>
      <div className={styles.card}>
        <div className={styles.cardTitle}>Long / Short Split</div>
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={lsData} cx="50%" cy="50%" innerRadius={70} outerRadius={110}
              dataKey="value" paddingAngle={3}>
              {lsData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
            </Pie>
            <Tooltip content={<PieTooltip />} />
            <Legend formatter={(v, e) => (
              <span style={{ color: e.payload.fill, fontWeight: 700 }}>
                {v} — {e.payload.pct?.toFixed(1)}%
              </span>
            )} />
          </PieChart>
        </ResponsiveContainer>
        <div className={styles.totalLabel}>
          Total tracked exposure: ${(totalOI / 1e9).toFixed(3)}B
        </div>
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Exposure by Asset</div>
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={coinData} cx="50%" cy="50%" innerRadius={70} outerRadius={110}
              dataKey="value" paddingAngle={3}>
              {coinData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
            </Pie>
            <Tooltip content={<PieTooltip />} />
            <Legend formatter={(v, e) => (
              <span style={{ color: e.payload.fill, fontWeight: 700 }}>
                {v} — {e.payload.pct?.toFixed(1)}%
              </span>
            )} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

const TABS = [
  { key: 'millionaire', label: 'Millionaire Bias' },
  { key: 'Hyperliquid', label: 'Hyperliquid OI' },
  { key: 'Binance', label: 'Binance OI' },
  { key: 'Bybit', label: 'Bybit OI' },
  { key: 'OKX', label: 'OKX OI' },
  { key: 'Deribit', label: 'Deribit OI' },
];

export default function OITabs({ aggregate }) {
  const [tab, setTab] = useState('millionaire');
  const [backendData, setBackendData] = useState(null);
  const exchangeCache = useRef({});

  const handleDataFetched = React.useCallback((exchange, data) => {
    exchangeCache.current[exchange] = { data, ts: Date.now() };
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/exchange-oi`)
      .then(res => res.json())
      .then(setBackendData)
      .catch(e  => console.error('Backend OI fetch failed:', e));
  }, []);

  return (
    <div>
      <div className={styles.tabBar}>
        {TABS.map(t => (
          <button
            key={t.key}
            className={`${styles.tab} ${tab === t.key ? styles.active : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'millionaire' && <MillionaireTab aggregate={aggregate} />}
      {['Hyperliquid', 'Binance', 'Bybit', 'OKX', 'Deribit'].map(ex => {
        const cached = exchangeCache.current[ex];
        const isStale = cached && (Date.now() - cached.ts) > 60000;
        return tab === ex && (
          <ExchangeTab
            key={ex}
            exchange={ex}
            backendData={backendData}
            cachedData={isStale ? null : cached?.data || null}
            onDataFetched={handleDataFetched}
          />
        );
      })}
    </div>
  );
}
