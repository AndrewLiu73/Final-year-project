'use client';

import { useParams, useNavigate } from 'react-router-dom';
import styles from './TraderDetail.module.css';
import { useTraderData }            from '../hooks/useWalletData';
import { calculateDirectionalBias } from '../utils/biasUtils';
import HistoryChart                 from '../components/balanceChart';
import { formatBalance }            from '../utils/formatters';

export default function TraderDetailPage() {
    const { wallet }                     = useParams();
    const navigate                       = useNavigate();
    const { data: trader, loading, error,
            dataSource }                 = useTraderData(wallet);

    const copyToClipboard = () => {
        if (wallet) {
            navigator.clipboard.writeText(wallet);
            alert('Wallet address copied!');
        }
    };

    if (loading || (!trader && !error)) {
        return (
            <div className={styles.container}>
                <div className={styles.loadingState}>
                    <div className={styles.spinner}></div>
                    <p>Loading trader data...</p>
                </div>
            </div>
        );
    }

    if (!loading && (error || !trader)) {
        return (
            <div className={styles.container}>
                <div className={styles.errorState}>
                    <h2>Trader Not Found</h2>
                    <p>{error || 'No data available for this wallet.'}</p>
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

    const profitColor  = totalPnl > 0 ? '#3ba55d' : '#ed4245';
    const isProfitable = totalPnl > 0;
    const bias         = calculateDirectionalBias(trader.open_positions);

    return (
        <div className={styles.container}>

            {/* Header */}
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

            {/* History Chart — sits between header and cards */}
            {(trader.historical_pnl || trader.historical_balance) && (
                <HistoryChart
                    historicalPnl={trader.historical_pnl}
                    historicalBalance={trader.historical_balance}
                />
            )}

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

                {/* Profit & Loss */}
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
                            <span className={styles.metricLabel}>Max Drawdown</span>
                            <span className={styles.metricValueRed}>
                                {(trader.max_drawdown_percentage ?? 0).toFixed(2)}%
                            </span>
                        </div>
                    </div>
                </div>

                {/* Directional Bias */}
                <div className={styles.card}>
                    <h2 className={styles.cardTitle}>Directional Bias</h2>
                    <div className={styles.metricGrid}>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Current Bias</span>
                            <span className={styles.metricValue} style={{ color: bias.color, fontWeight: '700' }}>
                                {bias.label}
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

                {/* Volume & Activity */}
                <div className={styles.card}>
                    <h2 className={styles.cardTitle}>Volume & Activity</h2>
                    <div className={styles.metricGrid}>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Total Volume</span>
                            <span className={styles.metricValue}>
                                {formatBalance(trader.total_volume_usdc)}
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

                {/* Account Role */}
                {trader.user_role && trader.user_role !== 'unknown' && (
                    <div className={styles.card}>
                        <h2 className={styles.cardTitle}>Account Role</h2>
                        <div className={styles.metricGrid}>
                            <div className={styles.metric}>
                                <span className={styles.metricLabel}>Role</span>
                                <span className={styles.metricValue}>
                                    {trader.user_role === 'subAccount' ? 'Sub Account' : 'Master'}
                                </span>
                            </div>

                            {trader.user_role === 'subAccount' && (
                                <div className={styles.metric}>
                                    <span className={styles.metricLabel}>Master</span>
                                    {trader.master_wallet ? (
                                        <span
                                            className={styles.metricValue}
                                            style={{ cursor: 'pointer', color: '#5865f2', fontSize: '13px', fontFamily: 'monospace' }}
                                            onClick={() => navigate(`/traders/${trader.master_wallet}`)}
                                            title={trader.master_wallet}
                                        >
                                            {trader.master_wallet.slice(0, 10)}...{trader.master_wallet.slice(-8)}
                                        </span>
                                    ) : (
                                        <span className={styles.metricValue} style={{ color: '#96989d' }}>
                                            Unknown Trader
                                        </span>
                                    )}
                                </div>
                            )}

                            {trader.user_role === 'master' && (
                                <div className={styles.metric}>
                                    <span className={styles.metricLabel}>Sub Accounts</span>
                                    <span className={styles.metricValue}>{trader.sub_account_count ?? 0}</span>
                                </div>
                            )}
                        </div>

                        {trader.user_role === 'master' && trader.sub_accounts && trader.sub_accounts.length > 0 && (
                            <div style={{ marginTop: '12px' }}>
                                {trader.sub_accounts.map((addr, i) => (
                                    <div
                                        key={i}
                                        style={{
                                            padding: '8px 12px', marginBottom: '6px',
                                            background: '#2b2d31', borderRadius: '8px',
                                            cursor: 'pointer', color: '#5865f2',
                                            fontSize: '13px', fontFamily: 'monospace'
                                        }}
                                        onClick={() => navigate(`/traders/${addr}`)}
                                        title={addr}
                                    >
                                        {addr.slice(0, 10)}...{addr.slice(-8)}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Account Flags */}
                <div className={styles.card}>
                    <h2 className={styles.cardTitle}>Account Flags</h2>
                    <div className={styles.metricGrid}>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Bot</span>
                            <span className={styles.metricValue} style={{
                                color: trader.is_likely_bot ? '#ed4245' : '#3ba55d'
                            }}>
                                {trader.is_likely_bot ? 'Yes' : 'No'}
                            </span>
                        </div>
                        <div className={styles.metric}>
                            <span className={styles.metricLabel}>Vault Depositor</span>
                            <span className={styles.metricValue} style={{
                                color: trader.is_vault_depositor ? '#f0b132' : '#96989d'
                            }}>
                                {trader.is_vault_depositor ? 'Yes' : 'No'}
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
