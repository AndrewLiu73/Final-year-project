import React, { useState, useEffect } from 'react';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const GREEN  = '#3ba55d';
const RED    = '#ed4245';
const ACCENT = '#5865f2';

const COIN_COLOURS = {
  BTC:  '#f7931a',
  ETH:  '#627eea',
  HYPE: '#5865f2',
};

const EXCHANGE_COLOURS = {
  Binance:     '#f0b90b',
  OKX:         '#00b4d8',
  Bybit:       '#f7a600',
  Deribit:     '#0e8fff',
  Hyperliquid: '#5865f2',
};

const TREND_COLOURS = {
  'Building Long':     '#3ba55d',
  'Squeeze Risk':      '#ed4245',
  'Crowded / Fragile': '#f0a500',
  'Short Covering':    '#00b4d8',
  'Deleveraging':      '#72767d',
  'Neutral':           '#96989d',
};

const TARGET_COINS = ['BTC', 'ETH'];

// ── live fetchers ─────────────────────────────────────────────────────────────

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

    // open_interest already in USD — sum directly
    const total_oi = items.reduce((s, i) => s + parseFloat(i.open_interest || 0), 0);

    const perp   = items.find(i => i.instrument_name?.includes(`${coin}-PERPETUAL`)) || items[0];
    const mark_px = parseFloat(perp?.mark_price || 0);

    results[coin] = { oi_usd: total_oi, mark_px };
  }));
  return results;
}

async function fetchHyperliquidLive() {
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
    if (TARGET_COINS.includes(asset.name)) {
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

// ── shared components ─────────────────────────────────────────────────────────

function PieTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { name, value, payload: p } = payload[0];
  return (
    <div style={{
      background: '#2f3136', border: '1px solid #202225',
      borderRadius: 6, padding: '10px 14px', fontSize: 13,
    }}>
      <div style={{ color: '#fff', fontWeight: 700, marginBottom: 4 }}>{name}</div>
      <div style={{ color: '#b9bbbe' }}>${(value / 1e9).toFixed(3)}B</div>
      <div style={{ color: p.fill, fontWeight: 600 }}>{p.pct?.toFixed(1)}%</div>
    </div>
  );
}

function TrendBadge({ label }) {
  if (!label) return null;
  return (
    <span style={{
      display:      'inline-block',
      padding:      '3px 10px',
      borderRadius: 99,
      fontSize:     11,
      fontWeight:   700,
      background:   (TREND_COLOURS[label] || '#96989d') + '22',
      color:        TREND_COLOURS[label]  || '#96989d',
      border:       `1px solid ${TREND_COLOURS[label] || '#96989d'}55`,
    }}>
      {label}
    </span>
  );
}

// ── generic exchange tab ──────────────────────────────────────────────────────

function ExchangeTab({ exchange, backendData }) {
  const [liveData, setLiveData] = useState(null);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);

  useEffect(() => {
    const fetcher = EXCHANGE_FETCHERS[exchange];
    fetcher()
      .then(d  => { setLiveData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [exchange]);

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 40, color: '#96989d' }}>
      <div style={spinnerStyle}></div> Fetching live OI from {exchange}...
    </div>
  );
  if (error) return <div style={{ color: RED, padding: 20 }}>Error: {error}</div>;
  if (!liveData) return null;

  const colour  = EXCHANGE_COLOURS[exchange] || '#72767d';
  const entries = Object.entries(liveData);
  const totalOI = entries.reduce((s, [, v]) => s + v.oi_usd, 0);

  const pieData = entries.map(([coin, v]) => ({
    name:  coin,
    value: v.oi_usd,
    pct:   totalOI > 0 ? (v.oi_usd / totalOI * 100) : 0,
    fill:  COIN_COLOURS[coin] || '#72767d',
  }));

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <div style={cardStyle}>
        <div style={cardTitle}>Live OI — {exchange} (USD)</div>
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
        <div style={{ textAlign: 'center', fontSize: 12, color: '#96989d', marginTop: 4 }}>
          Total {exchange} OI: ${(totalOI / 1e9).toFixed(3)}B
        </div>
      </div>

      <div style={cardStyle}>
        <div style={cardTitle}>Asset Breakdown + 30min Signal</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 8 }}>
          {entries.map(([coin, v]) => {
            const backend = backendData?.[coin]?.find(d => d.exchange === exchange);
            const chg     = backend?.change_pct_30min ?? null;
            const label   = backend?.trend_label      ?? null;
            const px_chg  = backend?.px_change_30min  ?? null;

            return (
              <div key={coin} style={{
                background:   '#36393f',
                borderRadius: 8,
                padding:      '14px 18px',
                border:       `1px solid ${COIN_COLOURS[coin] || '#202225'}33`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <div style={{ color: COIN_COLOURS[coin], fontWeight: 800, fontSize: 16 }}>{coin}</div>
                  <TrendBadge label={label} />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <div>
                    <div style={statLabel}>Live OI (USD)</div>
                    <div style={statValue}>${(v.oi_usd / 1e9).toFixed(3)}B</div>
                  </div>
                  <div>
                    <div style={statLabel}>Mark Price</div>
                    <div style={statValue}>${v.mark_px.toLocaleString()}</div>
                  </div>
                  <div>
                    <div style={statLabel}>OI Change (30m)</div>
                    <div style={{
                      fontSize: 16, fontWeight: 700,
                      color: chg === null ? '#96989d' : chg >= 0 ? GREEN : RED,
                    }}>
                      {chg === null ? '—' : `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`}
                    </div>
                  </div>
                  <div>
                    <div style={statLabel}>Price Change (30m)</div>
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

// ── millionaire tab (unchanged) ───────────────────────────────────────────────

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

  const coinData = coins.map(([coin, v]) => ({
    name:  coin,
    value: (v.long || 0) + (v.short || 0),
    pct:   totalOI > 0 ? (((v.long || 0) + (v.short || 0)) / totalOI * 100) : 0,
    fill:  COIN_COLOURS[coin] || '#72767d',
  }));

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <div style={cardStyle}>
        <div style={cardTitle}>Long / Short Split</div>
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
        <div style={{ textAlign: 'center', marginTop: 4, fontSize: 12, color: '#96989d' }}>
          Total tracked exposure: ${(totalOI / 1e9).toFixed(3)}B
        </div>
      </div>

      <div style={cardStyle}>
        <div style={cardTitle}>Exposure by Asset</div>
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

// ── hyperliquid OI tab (unchanged) ────────────────────────────────────────────

function HyperliquidOITab() {
  const [oiData,  setOiData]  = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  const TARGETS = ['BTC', 'ETH', 'HYPE'];

  useEffect(() => {
    const fetchOI = async () => {
      try {
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
          if (TARGETS.includes(asset.name)) {
            const ctx = ctxs[i];
            const oi  = parseFloat(ctx.openInterest || 0);
            const px  = parseFloat(ctx.markPx       || 0);
            results[asset.name] = { openInterest: oi, markPx: px, oiUsd: oi * px };
          }
        });
        setOiData(results);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    fetchOI();
  }, []);

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 40, color: '#96989d' }}>
      <div style={spinnerStyle}></div> Fetching live OI from Hyperliquid...
    </div>
  );
  if (error) return <div style={{ color: RED, padding: 20 }}>Error: {error}</div>;

  const entries = Object.entries(oiData);
  const totalOI = entries.reduce((s, [, v]) => s + v.oiUsd, 0);

  const pieData = entries.map(([coin, v]) => ({
    name:  coin,
    value: v.oiUsd,
    pct:   totalOI > 0 ? (v.oiUsd / totalOI * 100) : 0,
    fill:  COIN_COLOURS[coin] || '#72767d',
  }));

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <div style={cardStyle}>
        <div style={cardTitle}>OI by Asset (USD)</div>
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
        <div style={{ textAlign: 'center', fontSize: 12, color: '#96989d', marginTop: 4 }}>
          Total OI (BTC+ETH+HYPE): ${(totalOI / 1e9).toFixed(3)}B
        </div>
      </div>

      <div style={cardStyle}>
        <div style={cardTitle}>Asset Breakdown</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 8 }}>
          {entries.map(([coin, v]) => (
            <div key={coin} style={{
              background: '#36393f', borderRadius: 8, padding: '14px 18px',
              border: `1px solid ${COIN_COLOURS[coin] || '#202225'}22`,
            }}>
              <div style={{ color: COIN_COLOURS[coin], fontWeight: 800, fontSize: 16, marginBottom: 8 }}>
                {coin}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <div>
                  <div style={statLabel}>Open Interest</div>
                  <div style={statValue}>${(v.oiUsd / 1e9).toFixed(3)}B</div>
                </div>
                <div>
                  <div style={statLabel}>Mark Price</div>
                  <div style={statValue}>${v.markPx.toLocaleString()}</div>
                </div>
                <div>
                  <div style={statLabel}>Coin Units OI</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#b9bbbe' }}>
                    {v.openInterest.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                </div>
                <div>
                  <div style={statLabel}>Share of Total</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: COIN_COLOURS[coin] }}>
                    {totalOI > 0 ? (v.oiUsd / totalOI * 100).toFixed(1) : 0}%
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── styles ────────────────────────────────────────────────────────────────────

const cardStyle = {
  background:   '#2f3136',
  borderRadius: 8,
  padding:      '20px 24px',
  border:       '1px solid #202225',
};

const cardTitle = {
  fontSize:      11,
  fontWeight:    700,
  textTransform: 'uppercase',
  letterSpacing: '0.8px',
  color:         '#96989d',
  marginBottom:  16,
  paddingBottom: 10,
  borderBottom:  '1px solid #202225',
};

const statLabel = {
  fontSize:      11,
  color:         '#96989d',
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
};

const statValue = {
  fontSize:  16,
  fontWeight: 700,
  color:     '#fff',
};

const spinnerStyle = {
  width:        18,
  height:       18,
  border:       '3px solid #202225',
  borderTop:    '3px solid #5865f2',
  borderRadius: '50%',
  animation:    'spin 1s linear infinite',
  flexShrink:   0,
};

const tabStyle = (active) => ({
  padding:      '8px 20px',
  background:   active ? ACCENT : '#2f3136',
  color:        active ? '#fff' : '#96989d',
  border:       `1px solid ${active ? ACCENT : '#202225'}`,
  borderRadius: '4px',
  cursor:       'pointer',
  fontWeight:   700,
  fontSize:     13,
  transition:   'all 0.15s ease',
});

// ── root component ────────────────────────────────────────────────────────────

const TABS = [
  { key: 'millionaire', label: 'Millionaire Cohort' },
  { key: 'hyperliquid', label: 'Hyperliquid OI (Live)' },
  { key: 'Binance',     label: 'Binance' },
  { key: 'Bybit',       label: 'Bybit' },
  { key: 'OKX',         label: 'OKX' },
  { key: 'Deribit',     label: 'Deribit' },
];

export default function OITabs({ aggregate }) {
  const [tab,         setTab]         = useState('millionaire');
  const [backendData, setBackendData] = useState(null);

  // fetch backend once for 30-min deltas and trend labels
  useEffect(() => {
    fetch('http://localhost:8000/api/exchange-oi')
      .then(res => res.json())
      .then(setBackendData)
      .catch(e  => console.error('Backend OI fetch failed:', e));
  }, []);

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {TABS.map(t => (
          <button key={t.key} style={tabStyle(tab === t.key)} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'millionaire' && <MillionaireTab aggregate={aggregate} />}
      {tab === 'hyperliquid' && <HyperliquidOITab />}
      {['Binance', 'Bybit', 'OKX', 'Deribit'].map(ex => (
        tab === ex && (
          <ExchangeTab key={ex} exchange={ex} backendData={backendData} />
        )
      ))}
    </div>
  );
}
