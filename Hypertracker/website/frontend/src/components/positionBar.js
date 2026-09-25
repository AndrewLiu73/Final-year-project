import React from 'react';
import styles from './positionBar.module.css';

export default function PositionBar({ aggregate }) {
  if (!aggregate) return null;

  return (
    <div>
      {Object.entries(aggregate).map(([coin, data]) => {
        const long_count = data.longs;
        const short_count = data.shorts;
        const total = long_count + short_count;
        const long_pct = total > 0 ? ((long_count / total) * 100).toFixed(1) : 0;
        const short_pct = total > 0 ? ((short_count / total) * 100).toFixed(1) : 0;

        return (
          <div key={coin} className={styles.card}>
            <div className={styles.coinTitle}>
              {coin}
            </div>
            <div className={styles.statsRow}>
              <div>
                <div className={styles.statLabel}>Total Millionaires</div>
                <div className={styles.totalValue}>{total}</div>
              </div>
              <div>
                <div className={styles.statLabel}>Long</div>
                <div className={styles.longValue}>
                  {long_count}{" "}
                  <span className={styles.pctText}>
                    ({long_pct}%)
                  </span>
                </div>
              </div>
              <div>
                <div className={styles.statLabel}>Short</div>
                <div className={styles.shortValue}>
                  {short_count}{" "}
                  <span className={styles.pctText}>
                    ({short_pct}%)
                  </span>
                </div>
              </div>
            </div>
            <div className={styles.barTrack}>
              <div className={styles.barLong} style={{ width: `${long_pct}%` }} />
              <div className={styles.barShort} style={{ width: `${short_pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
