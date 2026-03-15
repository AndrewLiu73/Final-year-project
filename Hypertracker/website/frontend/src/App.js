import React, { useEffect, useState } from "react";
import { BrowserRouter as Router, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import './App.css';


import BiasHistoryChart from './components/biasHistoryChart';
import PositionBar from './components/positionBar';
import ProfitableTradersPage from './pages/profitability';
import TraderDetailPage from './pages/TraderDetail';
import OpenPositionsPage from './pages/openPositions';
import OITabs from './components/OITabs';
import WatchlistPage from './pages/watchlist';
import ErrorBoundary from './components/errorBoundary';

// --- Navigation Header ---
function NavigationHeader() {
  const navigate = useNavigate();
  const location = useLocation();

  const isMarket  = location.pathname === '/';
  const isTraders = location.pathname.startsWith('/traders') || location.pathname.startsWith('/trader/');

  return (
    <div className="header-container">
      <h1 className="main-title">Hyperliquid Analytics</h1>
      <div className="nav-buttons">
        <button
          onClick={() => navigate('/')}
          className={`nav-button ${isMarket ? 'active' : ''}`}
        >
          Market Overview
        </button>

        <button
          onClick={() => navigate('/traders')}
          className={`nav-button ${isTraders ? 'active' : ''}`}
        >
          Traders
        </button>

        <button
          onClick={() => navigate('/open-positions')}
          className={`nav-button ${location.pathname === '/open-positions' ? 'active' : ''}`}
        >
          Open Positions
        </button>

        <button
          onClick={() => navigate('/watchlist')}
          className={`nav-button ${location.pathname === '/watchlist' ? 'active' : ''}`}
        >
          Watchlist
        </button>
      </div>
    </div>
  );
}

// --- Market View ---
function MarketView() {
  const [biasSummaries, setBiasSummaries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState(30);
  const [selectedCoin, setSelectedCoin] = useState('ALL');
  const [chartType, setChartType] = useState('LONG');
  const [millionairesCount, setMillionairesCount] = useState(0);

  useEffect(() => {
    setLoading(true);
    fetch(`http://localhost:8000/api/bias-summaries`)
      .then(res => res.json())
      .then(data => { setBiasSummaries(data); setLoading(false); })
      .catch(err  => { console.error(err);    setLoading(false); });
  }, []);

    useEffect(() => {
    fetch(`http://localhost:8000/api/millionaires`)
      .then(res => res.json())
      .then(data => setMillionairesCount(data.length))
      .catch(err => console.error(err));
  }, []);

  const now      = new Date();
  const filtered = biasSummaries.filter(item => {
    if (!item.timestamp) return false;
    return (now - new Date(item.timestamp)) / 86400000 <= period;
  });

  const latest    = filtered.length > 0 ? filtered[filtered.length - 1] : null;
  const aggregate = latest?.aggregate ?? {};
  const coins     = Object.entries(aggregate);

  const totalLong  = coins.reduce((s, [, v]) => s + (v.long  || 0), 0);
  const totalShort = coins.reduce((s, [, v]) => s + (v.short || 0), 0);
  const totalOI    = totalLong + totalShort;
  const netBias = totalOI > 0 ? (totalLong >= totalShort ? 'Long' : 'Short') : '—';
  const biasColor  = parseFloat(netBias) > 0 ? 'var(--green-d)' : 'var(--red)';

  const periodBtns = [
    { label: '7D',  value: 7  },
    { label: '30D', value: 30 },
    { label: '90D', value: 90 },
  ];

  const coinBtns = [
    { label: 'All', value: 'ALL'  },
    { label: 'BTC', value: 'BTC'  },
    { label: 'ETH', value: 'ETH'  },
    { label: 'HYPE',value: 'HYPE' },
  ];

  const typeBtns = [
    { label: 'Long %',  value: 'LONG'  },
    { label: 'Short %', value: 'SHORT' },
  ];

  if (loading) {
    return (
      <div className="market-loading">
        <div className="spinner-sm"></div>
        Loading market data...
      </div>
    );
  }

  return (
    <div>

      {latest && (
        <div className="market-hero">
          <div className="market-stat-card">
            <span className="market-stat-label">Total Exposure</span>
            <span className="market-stat-value">${(totalOI / 1e9).toFixed(2)}B</span>
          </div>
          <div className="market-stat-card">
            <span className="market-stat-label">Total Long</span>
            <span className="market-stat-value" style={{ color: 'var(--green-d)' }}>
              ${(totalLong / 1e9).toFixed(2)}B
            </span>
          </div>
          <div className="market-stat-card">
            <span className="market-stat-label">Total Short</span>
            <span className="market-stat-value" style={{ color: 'var(--red)' }}>
              ${(totalShort / 1e9).toFixed(2)}B
            </span>
          </div>
          <div className="market-stat-card">
            <span className="market-stat-label">Net Bias</span>
            <span className="market-stat-value" style={{ color: biasColor }}>
              {netBias}
            </span>
          </div>
          <div className="market-stat-card">
            <span className="market-stat-label">Assets Tracked</span>
            <span className="market-stat-value">{coins.length}</span>
          </div>
        </div>
      )}

      {/* OI Tabs */}
      <div className="section-card">
        <div className="section-title">
          Open Interest
          {latest && (
            <span className="section-timestamp">
              Cohort data: {new Date(latest.timestamp).toLocaleString()}
            </span>
          )}
        </div>
        <OITabs aggregate={aggregate} />
      </div>

      {/* Bias History */}
      <div className="section-card">
        <div className="section-title">Bias History</div>

        {/* All controls in one row */}
        <div style={{
          display:      'flex',
          flexWrap:     'wrap',
          alignItems:   'center',
          gap:          '6px',
          marginBottom: '20px',
        }}>

          {/* Period */}
          <div style={{ display: 'flex', gap: '4px' }}>
            {periodBtns.map(b => (
              <button
                key={b.value}
                className={`period-btn ${period === b.value ? 'active' : ''}`}
                onClick={() => setPeriod(b.value)}
              >
                {b.label}
              </button>
            ))}
          </div>

          {/* Divider */}
          <div style={{ width: '1px', height: '24px', background: '#202225', margin: '0 4px' }} />

          {/* Coin */}
          <div style={{ display: 'flex', gap: '4px' }}>
            {coinBtns.map(b => (
              <button
                key={b.value}
                className={`period-btn ${selectedCoin === b.value ? 'active' : ''}`}
                onClick={() => setSelectedCoin(b.value)}
              >
                {b.label}
              </button>
            ))}
          </div>

          {/* Divider */}
          <div style={{ width: '1px', height: '24px', background: '#202225', margin: '0 4px' }} />

          {/* Long / Short */}
          <div style={{ display: 'flex', gap: '4px' }}>
            {typeBtns.map(b => (
              <button
                key={b.value}
                className={`period-btn ${chartType === b.value ? 'active' : ''}`}
                onClick={() => setChartType(b.value)}
              >
                {b.label}
              </button>
            ))}
          </div>

        </div>

        <BiasHistoryChart
          biasSummaries={filtered}
          period={period}
          selectedCoin={selectedCoin}
          type={chartType}
        />
      </div>

      {/* Asset breakdown */}
      {latest && (
    <div className="section-card">
        <div className="section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Asset Breakdown</span>
            <span style={{
                fontSize:     '12px',
                fontWeight:   '600',
                color:        '#b9bbbe',
                background:   '#202225',
                padding:      '4px 10px',
                borderRadius: '12px',
            }}>
                {millionairesCount.toLocaleString()} millionaires tracked
            </span>
        </div>
        {coins.map(([coin, stats]) => (
            <PositionBar
                key={coin}
                coin={coin}
                position={`$${((stats.long + stats.short) / 1e9).toFixed(2)}B`}
                long={`$${(stats.long / 1e9).toFixed(2)}B`}
                long_pct={stats.long_pct?.toFixed(2)}
                short={`$${(stats.short / 1e9).toFixed(2)}B`}
                short_pct={stats.short_pct?.toFixed(2)}
            />
        ))}
    </div>
)}


    </div>
  );
}

// --- App Shell ---
function AppContent() {
  return (
    <div className="app-container">
      <NavigationHeader />
      <div className="content-container">
        <ErrorBoundary>
          <Routes>
            <Route path="/"               element={<MarketView />} />
            <Route path="/traders"        element={<ProfitableTradersPage />} />
            <Route path="/trader/:wallet" element={<TraderDetailPage />} />
            <Route path="/open-positions" element={<OpenPositionsPage />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
          </Routes>
        </ErrorBoundary>
      </div>
    </div>
  );
}

function App() {
  return (
    <Router>
      <AppContent />
    </Router>
  );
}

export default App;
