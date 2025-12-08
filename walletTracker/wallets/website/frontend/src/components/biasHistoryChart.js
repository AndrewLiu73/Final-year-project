import React, { useState } from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend
} from "chart.js";
ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

export default function BiasHistoryChart({ biasSummaries }) {
  const coins = ["BTC", "ETH", "HYPE"];
  const [period, setPeriod] = useState(7);
  const [selectedCoin, setSelectedCoin] = useState("ALL");
  const [type, setType] = useState("ALL");

  const filtered = biasSummaries.slice(-period);
  const pickedCoins = selectedCoin === "ALL" ? coins : [selectedCoin];
  const labels = filtered.map((_, idx) => `T${idx + 1}`);

  const datasets = pickedCoins.map(coin => ({
    label: `${coin} ${type === "LONG" ? "Long %" : type === "SHORT" ? "Short %" : "Long %"}`,
    data: filtered.map(s =>
      type === "LONG" ? s[coin]?.long_pct ?? 0
      : type === "SHORT" ? s[coin]?.short_pct ?? 0
      : s[coin]?.long_pct ?? 0),
    borderColor: coin === "BTC" ? "#f6ad55" : coin === "ETH" ? "#4299e1" : "#e53e3e",
    backgroundColor: "transparent"
  }));

  return (
    <div style={{background: "#232b38", padding:"1rem", borderRadius:"12px", marginBottom:"2rem"}}>
      <h2 style={{color:"#ecc94b"}}>Bias History Chart</h2>
      <div style={{marginBottom:10}}>
        <button onClick={() => setPeriod(7)}>Last 7</button>
        <button onClick={() => setPeriod(30)}>Last 30</button>
        <button onClick={() => setPeriod(biasSummaries.length)}>All</button>
        {coins.map(coin => <button key={coin} onClick={() => setSelectedCoin(coin)}>{coin}</button>)}
        <button onClick={() => setSelectedCoin("ALL")}>All Coins</button>
        <button onClick={() => setType("LONG")}>Long Only</button>
        <button onClick={() => setType("SHORT")}>Short Only</button>
        <button onClick={() => setType("ALL")}>All (default)</button>
      </div>
      <Line data={{ labels, datasets }} options={{
        responsive: true,
        plugins: {
          legend: {position: "top"},
          title: {display: true, text: "Bias Trend Over Time"}
        },
        scales: {
          y: {title: {display:true, text:"% Long or Short"}, min:0, max:100}
        }
      }} />
    </div>
  );
}
