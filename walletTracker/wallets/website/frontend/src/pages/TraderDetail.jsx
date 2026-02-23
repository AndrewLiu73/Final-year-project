'use client';

import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import styles from './TraderDetail.module.css';

export default function TraderDetailPage() {
    const { wallet } = useParams();
    const navigate   = useNavigate();

    const [trader,     setTrader]     = useState(null);
    const [loading,    setLoading]    = useState(true);
    const [error,      setError]      = useState(null);
    const [dataSource, setDataSource] = useState('cached');

    useEffect(() => {
        if (!wallet) return;

        const fetchData = async () => {
            setLoading(true);
            setError(null);

            try {
                // fire both requests at the same time
                const [liveRes, dbRes] = await Promise.all([
                    fetch(`http://localhost:8000/api/users/trader/${wallet}/live`),
                    fetch(`http://localhost:8000/api/users/trader/${wallet}`)
                ]);

                const liveData = liveRes.ok ? await liveRes.json() : null;
                const dbData   = dbRes.ok   ? await dbRes.json()   : null;

                if (!dbData || dbData.error) {
                    setError('Trader not found');
                    setLoading(false);
                    return;
                }

                // DB is the base (accurate trade history, win rate, drawdown)
                // live overwrites only the real-time fields
                const merged = {
                    ...dbData,
                    ...(liveData && !liveData.error ? {
                        account_value:        liveData.account_value,
                        withdrawable_balance: liveData.withdrawable_balance,
                        total_pnl:            liveData.total_pnl,
                        realized_pnl:         liveData.realized_pnl,
                        unrealized_pnl:       liveData.unrealized_pnl,
                        profit_percentage:    liveData.profit_percentage,
                        open_positions:       liveData.open_positions,
                        open_positions_count: liveData.open_positions_count,
                        data_source:          'live',
                    } : { data_source: 'cached' })
                };

                setTrader(merged);
                setDataSource(merged.data_source);

            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, [wallet]);

    const formatBalance = (balance) => {
        if (balance === null || balance === undefined || balance === 0) return '$0';
        if (Math.abs(balance) < 1000) return `$${Math.floor(balance)}`;
        return `$${(balance / 1000).toFixed(2)}k`;
    };

    const formatLargeNumber = (num) => {
        if (!num) return '0';
        if (num >= 1000000) return `${(num / 1000000).toFixed(2)}M`;
        if (num >= 1000)    return `${(num / 1000).toFixed(2)}k`;
        return Math.floor(num).toString();
    };

    const copyToClipboard = () => {
        if (wallet) {
            navigator.clipboard.writeText(wallet);
            alert('Wallet address copied!');
        }
    };

    if (loading) {
        return (
            <div className={styles.container}>
                <div className={styles.loadingState}>
                    <div className={styles.spinner}></div>
                    <p>Loading trader data...</p>
                </div>
            </div>
        );
    }

    if (error || !trader) {
        return (
            <div className={styles.container}>
                <div className={styles.errorState}>
                    <h2>Error</h2>
                    <p>{error || 'Trader not found'}</p>
                    <button onClick={() => navigate('/traders')} className={styles.backButton}>
                        Back to Traders
                    </button>
                </div>
            </div>
        );
    }

    const totalPnl      = trader.total_pnl      ?? 0;
    const realizedPnl   = trader.realized_pnl   ?? 0;
    const unrealizedPnl = trader.unrealized_pnl ?? 0;

    const winLossRatio       = trader.losing_trades > 0
        ? (trader.winning_trades / trader.losing_trades)
        : trader.winning_trades ?? 0;

    const avgProfitPerTrade  = trader.trade_count > 0
        ? totalPnl / trader.trade_count
        : 0;

    const profitColor  = totalPnl > 0 ? '#3ba55d' : '#ed4245';
    const isProfitable = totalPnl > 0;

    return (
        <div className={styles.container}>
            <div className={styles.header}>
                <button onClick={() => navigate('/traders')} className={styles.backButton}>
                    Back to Traders
                </button>
                <div className={styles.walletInfo}>
                    <h1 className={styles.walletAddress}>
                        {wallet?.slice(0, 10)}...{wallet?.slice(-8)}
                    </h1>
                    <button onClick={copyToClipboard} className={styles.copyButton}>
                        Copy
                    </button>
                </div>
                <div className={styles.statusBadge} style={{ background: profitColor }}>
                    {isProfitable ? 'Profitable' : 'Losing'}
                </div>
                <div className={styles.dataSourceBadge} style={{
                    background:   dataSource === 'live' ? '#3ba55d' : '#f0b132',
                    padding:      '6px 12px',
                    borderRadius: '12px',
                    fontSize:     '12px',
                    fontWeight:   '600',
                    color:        'white',
                    marginLeft:   '12px'
                }}>
                    {dataSource === 'live' ? 'LIVE' : 'CACHED'}
                </div>
            </div>

            <div className={styles.gridContainer}>
                {/* Account Overview */}
                <div className={styles.card}>
                    <h2 className={styles.cardTitle}>Account Overview</h2>
                    <div className={styles.metricGrid}>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Account Value</span>
                            <span className={styles.metricValue}>{formatBalance(trader.account_value)}</span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Withdrawable</span>
                            <span className={styles.metricValue}>{formatBalance(trader.withdrawable_balance)}</span>
                        </div>
                    </div>
                </div>

                {/* PnL */}
                <div className={styles.card}>
                    <h2 className={styles.cardTitle}>Profit & Loss</h2>
                    <div className={styles.metricGrid}>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Total PnL</span>
                            <span className={styles.metricValue} style={{ color: profitColor }}>
                                {totalPnl > 0 ? '+' : ''}{formatBalance(totalPnl)}
                            </span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Profit %</span>
                            <span className={styles.metricValue} style={{ color: profitColor }}>
                                {trader.profit_percentage > 0 ? '+' : ''}{(trader.profit_percentage ?? 0).toFixed(2)}%
                            </span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Realized PnL</span>
                            <span className={styles.metricValue}>{formatBalance(realizedPnl)}</span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Unrealized PnL</span>
                            <span className={styles.metricValue} style={{
                                color: unrealizedPnl > 0 ? '#3ba55d' : '#ed4245'
                            }}>
                                {unrealizedPnl > 0 ? '+' : ''}{formatBalance(unrealizedPnl)}
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
                                {(trader.win_rate_percentage ?? 0).toFixed(1)}%
                            </span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Total Trades</span>
                            <span className={styles.metricValue}>
                                {(trader.trade_count ?? 0).toLocaleString()}
                            </span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Winning Trades</span>
                            <span className={styles.metricValueGreen}>
                                {(trader.winning_trades ?? 0).toLocaleString()}
                            </span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Losing Trades</span>
                            <span className={styles.metricValueRed}>
                                {(trader.losing_trades ?? 0).toLocaleString()}
                            </span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Win/Loss Ratio</span>
                            <span className={styles.metricValue}>
                                {winLossRatio.toFixed(2)}
                            </span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Avg Profit/Trade</span>
                            <span className={styles.metricValue}>
                                {formatBalance(avgProfitPerTrade)}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Risk */}
                <div className={styles.card}>
                    <h2 className={styles.cardTitle}>Risk Management</h2>
                    <div className={styles.metricGrid}>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Max Drawdown</span>
                            <span className={styles.metricValueRed}>
                                {(trader.max_drawdown_percentage ?? 0).toFixed(2)}%
                            </span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Open Positions</span>
                            <span className={styles.metricValue}>
                                {trader.open_positions_count ?? 0}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Volume */}
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
                {trader.open_positions && trader.open_positions.length > 0 ? (
                    <div className={styles.cardWide}>
                        <h2 className={styles.cardTitle}>
                            Open Positions ({trader.open_positions_count})
                        </h2>
                        <div className={styles.positionsTable}>
                            {trader.open_positions.map((position, index) => {
                                const posColor = (position.unrealized_pnl ?? 0) > 0 ? '#3ba55d' : '#ed4245';
                                return (
                                    <div key={index} className={styles.positionCard}>
                                        <div className={styles.positionHeader}>
                                            <span className={styles.positionCoin}>
                                                {position.asset || 'Unknown'}
                                            </span>
                                            <span className={styles.positionSide} style={{
                                                color: position.direction === 'LONG' ? '#3ba55d' : '#ed4245'
                                            }}>
                                                {position.direction || 'N/A'}
                                            </span>
                                        </div>
                                        <div className={styles.positionDetails}>
                                            <div className={styles.positionMetric}>
                                                <span>Size:</span>
                                                <span>{position.size ? position.size.toFixed(4) : '0'}</span>
                                            </div>
                                            <div className={styles.positionMetric}>
                                                <span>Entry:</span>
                                                <span>${position.entry_price ? position.entry_price.toFixed(2) : '0'}</span>
                                            </div>
                                            <div className={styles.positionMetric}>
                                                <span>Unrealized PnL:</span>
                                                <span style={{ color: posColor }}>
                                                    {(position.unrealized_pnl ?? 0) > 0 ? '+' : ''}
                                                    {formatBalance(position.unrealized_pnl ?? 0)}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                ) : (
                    <div className={styles.cardWide}>
                        <h2 className={styles.cardTitle}>Open Positions</h2>
                        <div style={{ padding: '40px', textAlign: 'center', color: '#96989d' }}>
                            <p>No open positions</p>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
