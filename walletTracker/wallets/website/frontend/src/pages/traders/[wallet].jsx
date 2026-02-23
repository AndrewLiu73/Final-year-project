'use client';

import { useRouter } from 'next/router';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import styles from './wallet.module.css';

export default function TraderDetailPage() {
  const router = useRouter();
  const { wallet } = router.query;

  const [trader, setTrader] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!wallet) return;

    const fetchTraderDetails = async () => {
      setLoading(true);
      try {
        const response = await fetch(`http://localhost:8000/api/users/trader/${wallet}`);

        if (!response.ok) {
          throw new Error('Failed to fetch trader details');
        }

        const data = await response.json();

        if (data.error) {
          throw new Error(data.error);
        }

        setTrader(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchTraderDetails();
  }, [wallet]);

  const formatBalance = (balance) => {
    if (!balance) return '$0';
    if (Math.abs(balance) < 1000) {
      return `$${Math.floor(balance)}`;
    }
    return `$${(balance / 1000).toFixed(2)}k`;
  };

  const formatLargeNumber = (num) => {
    if (!num) return '0';
    if (num >= 1000000) {
      return `${(num / 1000000).toFixed(2)}M`;
    }
    if (num >= 1000) {
      return `${(num / 1000).toFixed(2)}k`;
    }
    return Math.floor(num).toString();
  };

  const copyToClipboard = () => {
    if (wallet) {
      navigator.clipboard.writeText(wallet);
      alert('Wallet address copied to clipboard!');
    }
  };

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.loadingState}>
          <div className={styles.spinner}></div>
          <p>Loading trader details...</p>
        </div>
      </div>
    );
  }

  if (error || !trader) {
    return (
      <div className={styles.container}>
        <div className={styles.errorState}>
          <h2>❌ Error</h2>
          <p>{error || 'Trader not found'}</p>
          <Link href="/">
            <button className={styles.backButton}>Back to Traders</button>
          </Link>
        </div>
      </div>
    );
  }

  const profitColor = trader.total_pnl > 0 ? '#3ba55d' : '#ed4245';
  const isProfitable = trader.total_pnl > 0;

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <Link href="/">
          <button className={styles.backButton}>← Back to Traders</button>
        </Link>
        <div className={styles.walletInfo}>
          <h1 className={styles.walletAddress}>
            {wallet?.slice(0, 10)}...{wallet?.slice(-8)}
          </h1>
          <button onClick={copyToClipboard} className={styles.copyButton}>
            📋 Copy
          </button>
        </div>
        <div className={styles.statusBadge} style={{ background: profitColor }}>
          {isProfitable ? 'Profitable' : 'Losing'}
        </div>
      </div>

      {/* Main Grid */}
      <div className={styles.gridContainer}>
        {/* Account Overview */}
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>Account Overview</h2>
          <div className={styles.metricGrid}>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Account Value</span>
              <span className={styles.metricValue}>
                {formatBalance(trader.account_value)}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Withdrawable</span>
              <span className={styles.metricValue}>
                {formatBalance(trader.withdrawable_balance)}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Initial Balance</span>
              <span className={styles.metricValue}>
                {formatBalance(trader.initial_balance)}
              </span>
            </div>
          </div>
        </div>

        {/* PnL Metrics */}
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>Profit & Loss</h2>
          <div className={styles.metricGrid}>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Total PnL</span>
              <span className={styles.metricValue} style={{ color: profitColor }}>
                {trader.total_pnl > 0 ? '+' : ''}{formatBalance(trader.total_pnl)}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Profit %</span>
              <span className={styles.metricValue} style={{ color: profitColor }}>
                {trader.profit_percentage > 0 ? '+' : ''}{trader.profit_percentage.toFixed(2)}%
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Realized PnL</span>
              <span className={styles.metricValue}>
                {formatBalance(trader.realized_pnl)}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Unrealized PnL</span>
              <span className={styles.metricValue}>
                {formatBalance(trader.unrealized_pnl)}
              </span>
            </div>
          </div>
        </div>

        {/* Trading Performance */}
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>Trading Performance</h2>
          <div className={styles.metricGrid}>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Win Rate</span>
              <span className={styles.metricValue}>
                {trader.win_rate_percentage.toFixed(1)}%
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Total Trades</span>
              <span className={styles.metricValue}>
                {trader.trade_count.toLocaleString()}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Winning Trades</span>
              <span className={styles.metricValueGreen}>
                {trader.winning_trades.toLocaleString()}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Losing Trades</span>
              <span className={styles.metricValueRed}>
                {trader.losing_trades.toLocaleString()}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Win/Loss Ratio</span>
              <span className={styles.metricValue}>
                {trader.win_loss_ratio.toFixed(2)}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Avg Profit/Trade</span>
              <span className={styles.metricValue}>
                {formatBalance(trader.avg_profit_per_trade)}
              </span>
            </div>
          </div>
        </div>

        {/* Risk Metrics */}
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>Risk Management</h2>
          <div className={styles.metricGrid}>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Max Drawdown</span>
              <span className={styles.metricValueRed}>
                {trader.max_drawdown_percentage.toFixed(2)}%
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Open Positions</span>
              <span className={styles.metricValue}>
                {trader.open_positions_count}
              </span>
            </div>
          </div>
        </div>

        {/* Volume & Trading Activity */}
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>Volume & Activity</h2>
          <div className={styles.metricGrid}>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Total Volume</span>
              <span className={styles.metricValue}>
                ${formatLargeNumber(trader.total_volume_usdc)}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Avg Trade Size</span>
              <span className={styles.metricValue}>
                {formatBalance(trader.avg_trade_size_usdc)}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricLabel}>Last Updated</span>
              <span className={styles.metricValue}>
                {trader.last_updated
                  ? new Date(trader.last_updated).toLocaleString()
                  : 'N/A'}
              </span>
            </div>
          </div>
        </div>

        {/* Open Positions */}
        {trader.open_positions && trader.open_positions.length > 0 && (
          <div className={styles.cardWide}>
            <h2 className={styles.cardTitle}>Open Positions</h2>
            <div className={styles.positionsTable}>
              {trader.open_positions.map((position, index) => (
                <div key={index} className={styles.positionCard}>
                  <div className={styles.positionHeader}>
                    <span className={styles.positionCoin}>{position.coin || 'Unknown'}</span>
                    <span className={styles.positionSide} style={{
                      color: position.side === 'long' ? '#3ba55d' : '#ed4245'
                    }}>
                      {position.side?.toUpperCase() || 'N/A'}
                    </span>
                  </div>
                  <div className={styles.positionDetails}>
                    <div className={styles.positionMetric}>
                      <span>Size:</span>
                      <span>{position.szi || 'N/A'}</span>
                    </div>
                    <div className={styles.positionMetric}>
                      <span>Entry:</span>
                      <span>{position.entryPx || 'N/A'}</span>
                    </div>
                    <div className={styles.positionMetric}>
                      <span>Leverage:</span>
                      <span>{position.leverage ? `${position.leverage}x` : 'N/A'}</span>
                    </div>
                    <div className={styles.positionMetric}>
                      <span>Unrealized PnL:</span>
                      <span style={{
                        color: (position.unrealizedPnl || 0) > 0 ? '#3ba55d' : '#ed4245'
                      }}>
                        {formatBalance(position.unrealizedPnl || 0)}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
