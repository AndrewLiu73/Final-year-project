import React, { useEffect, useState } from "react";
import './App.css';
import BiasHistoryChart from './hooks/biasHistoryChart';
import PositionBar from './hooks/positionBar';

// Your table/component for showing multiple samples:
function BiasSummaryDisplay({ biasSummaries }) {
  if (!biasSummaries.length) return <p>Loading market bias...</p>;
  return (
    <div>
      <h2>Aggregate Market Bias (Recent Samples)</h2>
      {biasSummaries.map((summary, idx) => (
        <div key={idx}>
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

function App() {
  const [biasSummaries, setBiasSummaries] = useState([]);
  const [period, setPeriod] = useState(7);

  useEffect(() => {
    fetch("http://localhost:8000/api/bias-aggregate")
      .then(res => res.json())
      .then(setBiasSummaries);
  }, []);

  // Filter logic
  const now = new Date();
  const filtered = biasSummaries.filter(item => {
    if (!item.timestamp) return false;
    const sampleDate = new Date(item.timestamp);
    const daysAgo = (now - sampleDate) / (1000 * 60 * 60 * 24);
    return daysAgo <= period;
  });

  // Most recent sample
  const latestSample = filtered.length > 0
    ? filtered[filtered.length - 1]
    : null;

  return (
    <div>
      <h1>Millionaire Bias</h1>

      {/* Show only the latest sample at the top */}
      {latestSample && (
        <div>
          <h2>Latest Market Bias</h2>
          <div style={{color: "#cbd5e0", fontSize: 13, marginBottom: 8}}>
            Timestamp: {new Date(latestSample.timestamp).toLocaleString()}
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

      {/* Buttons for period selection */}
      <div style={{ margin: "16px 0" }}>
        <button onClick={() => setPeriod(7)}>Last 7 days</button>
        <button onClick={() => setPeriod(30)}>Last 30 days</button>
        <button onClick={() => setPeriod(90)}>Last 90 days</button>
      </div>

      {/* Chart and table---pass just aggregate objects */}
      <BiasHistoryChart biasSummaries={filtered.map(item => item.aggregate)} />
      <BiasSummaryDisplay biasSummaries={filtered.map(item => item.aggregate)} />
    </div>
  );
}

export default App;
