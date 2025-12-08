'use client';

import { useState, useMemo } from 'react';
import { List } from 'react-window';
import { useProfitableTraders } from '../hooks/useProfitability';
import styles from './profitability.module.css';

export default function ProfitableTradersPage() {
  const [minGain, setMinGain] = useState(0);
  const [maxGain, setMaxGain] = useState(1000);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('gainPercent'); // 'gainPercent' or 'gainDollar'

  const { traders, loading, error } = useProfitableTraders(minGain, maxGain);

  // Filter by search query
  const filteredTraders = useMemo(() => {
    return traders.filter(trader =>
      trader.wallet.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [traders, searchQuery]);

  // Sort traders
  const sortedTraders = useMemo(() => {
    const sorted = [...filteredTraders];
    if (sortBy === 'gainPercent') {
      sorted.sort((a, b) => b.gainPercent - a.gainPercent);
    } else if (sortBy === 'gainDollar') {
      sorted.sort((a, b) => b.gainDollar - a.gainDollar);
    }
    return sorted;
  }, [filteredTraders, sortBy]);

  // Row component for virtualization
  const TraderRow = ({ index, style }) => {
    const trader = sortedTraders[index];
    const profitColor = trader.isProfitable ? '#22c55e' : '#ef4444';

    return (
      <div style={style} className={styles.traderItem}>
        <div className={styles.walletAddress}>
          {trader.wallet.slice(0, 6)}...{trader.wallet.slice(-4)}
          <span className={styles.fullWallet} title={trader.wallet}>
            {trader.wallet}
          </span>
        </div>

        <div className={styles.balances}>
          <div className={styles.stat}>
            <span className={styles.label}>Initial</span>
            <span className={styles.value}>${trader.initialBalance.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.label}>Current</span>
            <span className={styles.value}>${trader.currentBalance.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
          </div>
        </div>

        <div className={styles.gainMetrics}>
          <div className={styles.stat}>
            <span className={styles.label}>Gain $</span>
            <span className={styles.value} style={{ color: profitColor }}>
              ${trader.gainDollar.toLocaleString('en-US', { maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className={styles.stat}>
            <span className={styles.label}>Gain %</span>
            <span className={styles.value} style={{ color: profitColor }}>
              {trader.gainPercent.toFixed(2)}%
            </span>
          </div>
        </div>

        <div className={styles.progressBar}>
          <div className={styles.barContainer}>
            <div
              className={styles.barFill}
              style={{
                width: `${Math.min(Math.abs(trader.gainPercent), 100)}%`,
                background: profitColor,
              }}
            />
          </div>
        </div>
      </div>
    );
  };

  // Stats
  const stats = useMemo(() => {
    const profitableCount = sortedTraders.filter(t => t.isProfitable).length;
    const totalGain = sortedTraders.reduce((sum, t) => sum + t.gainDollar, 0);
    const avgGain = sortedTraders.length > 0 ? totalGain / sortedTraders.length : 0;

    return {
      total: sortedTraders.length,
      profitable: profitableCount,
      totalGain,
      avgGain,
    };
  }, [sortedTraders]);

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.loadingState}>Loading traders...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.container}>
        <div className={styles.errorState}>Error: {error}</div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>Profitable Traders Filter</h1>
        <p>Filter traders by gain percentage — calculated dynamically without precalculation</p>
      </div>

      <div className={styles.controlsSection}>
        {/* Gain Range Sliders */}
        <div className={styles.filterBlock}>
          <h3>Gain Range Filter</h3>
          <div className={styles.sliderGroup}>
            <div className={styles.controlGroup}>
              <label>Minimum Gain (%)</label>
              <div className={styles.sliderContainer}>
                <input
                  type="range"
                  min="-100"
                  max="1000"
                  value={minGain}
                  onChange={(e) => setMinGain(Math.min(Number(e.target.value), maxGain))}
                  step="5"
                  className={styles.slider}
                />
                <span className={styles.valueLabel}>{minGain}%</span>
              </div>
            </div>

            <div className={styles.controlGroup}>
              <label>Maximum Gain (%)</label>
              <div className={styles.sliderContainer}>
                <input
                  type="range"
                  min="-100"
                  max="1000"
                  value={maxGain}
                  onChange={(e) => setMaxGain(Math.max(Number(e.target.value), minGain))}
                  step="5"
                  className={styles.slider}
                />
                <span className={styles.valueLabel}>{maxGain}%</span>
              </div>
            </div>
          </div>
        </div>

        {/* Search & Sort */}
        <div className={styles.filterBlock}>
          <h3>Search & Sort</h3>
          <div className={styles.searchGroup}>
            <input
              type="text"
              placeholder="Search by wallet address..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={styles.searchInput}
            />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className={styles.sortSelect}
            >
              <option value="gainPercent">Sort by Gain %</option>
              <option value="gainDollar">Sort by Gain $</option>
            </select>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className={styles.statsSection}>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Total Traders</span>
          <span className={styles.statValue}>{stats.total.toLocaleString()}</span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Profitable</span>
          <span className={styles.statValue} style={{ color: '#22c55e' }}>
            {stats.profitable.toLocaleString()}
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Total Gain</span>
          <span className={styles.statValue} style={{ color: '#22c55e' }}>
            ${stats.totalGain.toLocaleString('en-US', { maximumFractionDigits: 0 })}
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Avg Gain</span>
          <span className={styles.statValue}>
            ${stats.avgGain.toLocaleString('en-US', { maximumFractionDigits: 2 })}
          </span>
        </div>
      </div>

      {/* Traders List */}
      <div className={styles.listSection}>
        {sortedTraders.length > 0 ? (
          <List
            height={600}
            itemCount={sortedTraders.length}
            itemSize={85}
            width="100%"
          >
            {TraderRow}
          </List>
        ) : (
          <div className={styles.emptyState}>
            <p>No traders match your criteria</p>
          </div>
        )}
      </div>
    </div>
  );
}