import React, { useEffect, useState } from "react";
import './App.css';

// Components
import BiasHistoryChart from './components/biasHistoryChart'; // Check casing!
import PositionBar from './components/positionBar';           // Check casing!
import ProfitableTradersPage from './pages/profitability';

// --- Your Existing Helper Component ---
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

// --- MAIN APP ---
function App() {
  const [view, setView] = useState("market"); // 'market' or 'traders'
  const [biasSummaries, setBiasSummaries] = useState([]);
  const [period, setPeriod] = useState(7);

  // Fetch Market Data (Only if viewing market)
  useEffect(() => {
    if (view === "market") {
      fetch("http://localhost:8000/api/bias-aggregate")
        .then(res => res.json())
        .then(setBiasSummaries)
        .catch(err => console.error("Error fetching bias:", err));
    }
  }, [view]);

  // Filter logic for Market Data
  const now = new Date();
  const filtered = biasSummaries.filter(item => {
    if (!item.timestamp) return false;
    const sampleDate = new Date(item.timestamp);
    const daysAgo = (now - sampleDate) / (1000 * 60 * 60 * 24);
    return daysAgo <= period;
  });

  const latestSample = filtered.length > 0 ? filtered[filtered.length - 1] : null;

  return (
    <div style={{ padding: "20px", background: "#0f172a", minHeight: "100vh", color: "white" }}>

      {/* --- HEADER & NAVIGATION --- */}
      <div style={{ marginBottom: "30px", borderBottom: "1px solid #334155", paddingBottom: "20px" }}>
        <h1 style={{ marginBottom: "20px", color: "#60a5fa" }}>Hyperliquid Analytics</h1>
        <div style={{ display: "flex", gap: "10px" }}>
          <button
            onClick={() => setView("market")}
            style={{
              padding: "10px 20px",
              background: view === "market" ? "#3b82f6" : "#1e293b",
              color: "white",
              border: "none",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: "bold"
            }}
          >
            📈 Market Overview
          </button>
          <button
            onClick={() => setView("traders")}
            style={{
              padding: "10px 20px",
              background: view === "traders" ? "#3b82f6" : "#1e293b",
              color: "white",
              border: "none",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: "bold"
            }}
          >
            💰 Profitable Traders
          </button>
        </div>
      </div>

      {/* --- VIEW 1: MARKET OVERVIEW (Your Old Code) --- */}
      {view === "market" && (
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
      )}

      {/* --- VIEW 2: TRADER FILTER (New Code) --- */}
      {view === "traders" && (
        <ProfitableTradersPage />
      )}

    </div>
  );
}

export default App;
