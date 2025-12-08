import React from 'react';

export default function PositionBar({ coin, position, long, long_pct, short, short_pct }) {
  const barStyle = {
    display: 'flex',
    height: '8px',
    width: '100%',
    background: '#20232A',
    borderRadius: '5px',
    overflow: 'hidden',
    marginTop: '6px',
    marginBottom: '6px'
  };
  return (
    <div style={{
      background: "#191B22",
      padding: "1rem",
      borderRadius: "10px",
      marginBottom: "1rem",
      boxShadow: "0 1px 6px rgba(0,0,0,0.14)"
    }}>
      <div style={{ fontWeight:700, fontSize:18, color:"#ecc94b", marginBottom:10 }}>{coin}</div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <div>
          <div style={{ color: "#b7b8b3", fontSize: 13 }}>Position</div>
          <div style={{ fontWeight: 700, fontSize: 20, color: "#f6ad55" }}>{position}</div>
        </div>
        <div>
          <div style={{ color: "#b7b8b3", fontSize: 13 }}>Long Position</div>
          <div style={{ fontWeight: 700, fontSize: 17, color: "#38a169" }}>{long} <span style={{ fontWeight:400, color:"#b7b8b3", fontSize:13 }}>({long_pct}%)</span></div>
        </div>
        <div>
          <div style={{ color: "#b7b8b3", fontSize: 13 }}>Short Position</div>
          <div style={{ fontWeight: 700, fontSize: 17, color: "#e53e3e" }}>{short} <span style={{ fontWeight:400, color:"#b7b8b3", fontSize:13 }}>({short_pct}%)</span></div>
        </div>
      </div>
      <div style={barStyle}>
        <div style={{ width: `${long_pct}%`, background: "#38a169" }} />
        <div style={{ width: `${short_pct}%`, background: "#e53e3e" }} />
      </div>
    </div>
  );
}
