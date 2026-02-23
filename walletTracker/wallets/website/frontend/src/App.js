import React, { useEffect, useState } from "react";
import { BrowserRouter as Router, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import './App.css';

// Components
import BiasHistoryChart from './components/biasHistoryChart';
import PositionBar from './components/positionBar';
import ProfitableTradersPage from './pages/profitability';
import TraderDetailPage from './pages/TraderDetail';

// --- Helper Component ---
function BiasSummaryDisplay({ biasSummaries }) {
  if (!biasSummaries.length) return <p>Loading market bias...</p>;
  return (
    <div>
      <h2>Aggregate Market Bias (Recent Samples)</h2>
      {biasSummaries.map((summary, idx) => (
        <div key={idx} style={{marginBottom: '2rem'}}>
          <h3 style={{color:'#ecc94b', marginBottom: '6px'}}>Sample {idx + 1}</h3>
          {Object.entries(summary).map(([coin, stats]) => (
            <PositionBar
              key={coin}
              coin={coin}
              position={`$${((stats.long + stats.short)/1e9).toFixed(2)}B`}
              long={`$${(stats.long/1e9).toFixed(2)}B`}
              long_pct={stats.long_pct?.toFixed(2)}
              short={`$${(stats.short/1e9).toFixed(2)}B`}
              short_pct={stats.short_pct?.toFixed(2)}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

// --- NAVIGATION HEADER COMPONENT ---
function NavigationHeader() {
  const navigate = useNavigate();
  const location = useLocation();

  const isMarketView = location.pathname === '/';
  const isTradersView = location.pathname.startsWith('/traders') || location.pathname.startsWith('/trader/');

  return (
    <div className="header-container">
      <h1 className="main-title">Hyperliquid Analytics</h1>
      <div className="nav-buttons">
        <button
          onClick={() => navigate('/')}
          className={`nav-button ${isMarketView ? 'active' : ''}`}
        >
          📈 Market Overview
        </button>
        <button
          onClick={() => navigate('/traders')}
          className={`nav-button ${isTradersView ? 'active' : ''}`}
        >
          💰 Profitable Traders
        </button>
      </div>
    </div>
  );
}

// --- MARKET VIEW COMPONENT ---
function MarketView() {
  const [biasSummaries, setBiasSummaries] = useState([]);
  const [period, setPeriod] = useState(90);

  useEffect(() => {
    fetch("http://localhost:8000/api/bias-aggregate")
      .then(res => res.json())
      .then(setBiasSummaries)
      .catch(err => console.error("Error fetching bias:", err));
  }, []);

  console.log("Current biasSummaries state:", biasSummaries);
  console.log("biasSummaries.length:", biasSummaries?.length);


  const now = new Date();
  const filtered = biasSummaries.filter(item => {
    if (!item.timestamp) return false;
    const sampleDate = new Date(item.timestamp);
    const daysAgo = (now - sampleDate) / (1000 * 60 * 60 * 24);
    return daysAgo <= period;
  });

  const latestSample = filtered.length > 0 ? filtered[filtered.length - 1] : null;

  return (
    <div>
      {latestSample && (
        <div style={{ marginBottom: "30px" }}>
          <h2>Latest Market Bias</h2>
          <div style={{color: "#cbd5e0", fontSize: 13, marginBottom: 8}}>
            {new Date(latestSample.timestamp).toLocaleString()}
          </div>
          {Object.entries(latestSample.aggregate).map(([coin, stats]) => (
            <PositionBar
              key={coin}
              coin={coin}
              position={`$${((stats.long + stats.short)/1e9).toFixed(2)}B`}
              long={`$${(stats.long/1e9).toFixed(2)}B`}
              long_pct={stats.long_pct?.toFixed(2)}
              short={`$${(stats.short/1e9).toFixed(2)}B`}
              short_pct={stats.short_pct?.toFixed(2)}
            />
          ))}
        </div>
      )}

      <div style={{ margin: "20px 0" }}>
        <span style={{ marginRight: 10, color: "#94a3b8" }}>History:</span>
        <button onClick={() => setPeriod(7)} style={{marginRight:5}}>7 Days</button>
        <button onClick={() => setPeriod(30)} style={{marginRight:5}}>30 Days</button>
        <button onClick={() => setPeriod(90)}>90 Days</button>
      </div>

      <BiasHistoryChart biasSummaries={filtered.map(item => item.aggregate)} />
      <BiasSummaryDisplay biasSummaries={filtered.map(item => item.aggregate)} />
    </div>
  );
}

// --- MAIN APP WITH ROUTING ---
function AppContent() {
  return (
    <div className="app-container">
      <NavigationHeader />

      <div className="content-container">
        <Routes>
          <Route path="/" element={<MarketView />} />
          <Route path="/traders" element={<ProfitableTradersPage />} />
          <Route path="/trader/:wallet" element={<TraderDetailPage />} />
        </Routes>
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
