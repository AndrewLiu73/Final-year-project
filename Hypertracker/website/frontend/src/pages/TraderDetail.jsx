'use client';
import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import styles from './TraderDetail.module.css';
import { calculateDirectionalBias } from '../utils/biasUtils';
import { formatBalance } from '../utils/formatters';
import HistoryChart from '../components/balanceChart';
import API_BASE from '../config';

const G = '#3ba55d', R = '#ed4245';
const pnlColor = v => v > 0 ? G : R;
const fmtPnl   = v => `${v > 0 ? '+' : ''}${formatBalance(v)}`;
const fmtAddr  = a => `${a.slice(0, 10)}...${a.slice(-8)}`;

const Metric = ({ label, value, style }) => (
  <div className={styles.metric}>
    <span className={styles.metricLabel}>{label}</span>
    <span className={styles.metricValue} style={style}>{value}</span>
  </div>
);

const Card = ({ title, children, wide }) => (
  <div className={wide ? styles.cardWide : styles.card}>
    <h2 className={styles.cardTitle}>{title}</h2>
    {children}
  </div>
);

export default function TraderDetailPage() {
  const { wallet } = useParams();
  const navigate   = useNavigate();
  const [trader,     setTrader]     = useState(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState(null);
  const [dataSource, setDataSource] = useState('cached');

  const fetchData = useCallback(async (signal) => {
    if (!wallet) return;
    setLoading(true); setError(null);
    try {
      const [liveRes, dbRes] = await Promise.all([
        fetch(`${API_BASE}/api/users/trader/${wallet}/live`, { signal }),
        fetch(`${API_BASE}/api/users/trader/${wallet}`,      { signal }),
      ]);
      const [liveData, dbData] = await Promise.all([
        liveRes.ok ? liveRes.json() : null,
        dbRes.ok   ? dbRes.json()   : null,
      ]);
      if (!dbData || dbData.error) { setError('Trader not found'); return; }
      const live = liveData && !liveData.error;
      const merged = {
        ...dbData,
        ...(live ? {
          account_value: liveData.account_value, withdrawable_balance: liveData.withdrawable_balance,
          total_pnl: liveData.total_pnl, realized_pnl: liveData.realized_pnl, unrealized_pnl: liveData.unrealized_pnl,
          profit_percentage: liveData.profit_percentage, open_positions: liveData.open_positions,
          open_positions_count: liveData.open_positions_count, spot_account_value: liveData.spot_account_value,
          perp_account_value: liveData.perp_account_value, spot_balances: liveData.spot_balances ?? [],
          data_source: 'live',
        } : { data_source: 'cached' })
      };
      setTrader(merged); setDataSource(merged.data_source);
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
    } finally { setLoading(false); }
  }, [wallet]);

  useEffect(() => {
    const c = new AbortController();
    fetchData(c.signal);
    return () => c.abort();
  }, [fetchData]);

  if (loading || (!trader && !error)) return (
    <div className={styles.container}>
      <div className={styles.loadingState}><div className={styles.spinner} /><p>Loading trader data...</p></div>
    </div>
  );

  if (error || !trader) return (
    <div className={styles.container}>
      <div className={styles.errorState}>
        <h2>Trader Not Found</h2>
        <p>{error || 'No data available for this wallet.'}</p>
        <button onClick={() => navigate('/traders')} className={styles.backButton}>Back to Traders</button>
      </div>
    </div>
  );

  const totalPnl      = trader.total_pnl      ?? 0;
  const realizedPnl   = trader.realized_pnl   ?? 0;
  const unrealizedPnl = trader.unrealized_pnl ?? 0;
  const bias          = calculateDirectionalBias(trader.open_positions);
  const isLive        = dataSource === 'live';

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <button onClick={() => navigate('/traders')} className={styles.backButton}>Back to Traders</button>
        <div className={styles.walletInfo}>
          <h1 className={styles.walletAddress}>{fmtAddr(wallet)}</h1>
          <button onClick={() => { navigator.clipboard.writeText(wallet); alert('Wallet address copied!'); }} className={styles.copyButton}>Copy</button>
        </div>
        <div className={styles.statusBadge} style={{ background: pnlColor(totalPnl) }}>{totalPnl > 0 ? 'Profitable' : 'Losing'}</div>
        <div className={styles.dataSourceBadge} style={{ background: isLive ? G : '#f0b132', padding: '6px 12px', borderRadius: '12px', fontSize: '12px', fontWeight: '600', color: 'white', marginLeft: '12px' }}>
          {isLive ? 'LIVE' : 'CACHED'}
        </div>
      </div>

      {(trader.historical_pnl || trader.historical_balance) && (
        <HistoryChart historicalPnl={trader.historical_pnl} historicalBalance={trader.historical_balance} />
      )}

      <div className={styles.gridContainer}>
        <Card title="Account Overview">
          <div className={styles.metricGrid}>
            <Metric label="Account Value" value={formatBalance(trader.account_value)} />
            <Metric label="Withdrawable"  value={formatBalance(trader.withdrawable_balance)} />
            {isLive && <>
              <Metric label="Perp Value" value={formatBalance(trader.perp_account_value ?? 0)} />
              <Metric label="Spot Value" value={formatBalance(trader.spot_account_value ?? 0)} />
            </>}
          </div>
        </Card>

        <Card title="Profit & Loss">
          <div className={styles.metricGrid}>
            <Metric label="Total PnL"      value={fmtPnl(totalPnl)}      style={{ color: pnlColor(totalPnl) }} />
            <Metric label="Realized PnL"   value={formatBalance(realizedPnl)} />
            <Metric label="Unrealized PnL" value={fmtPnl(unrealizedPnl)} style={{ color: pnlColor(unrealizedPnl) }} />
          </div>
        </Card>

        <Card title="Trading Performance">
          <div className={styles.metricGrid}>
            <Metric label="Win Rate"     value={`${(trader.win_rate_percentage ?? 0).toFixed(1)}%`} />
            <Metric label="Max Drawdown" value={`${(trader.max_drawdown_percentage ?? 0).toFixed(2)}%`} style={{ color: R }} />
          </div>
        </Card>

        <Card title="Directional Bias">
          <div className={styles.metricGrid}>
            <Metric label="Current Bias"    value={bias.label}                    style={{ color: bias.color, fontWeight: '700' }} />
            <Metric label="Open Positions"  value={trader.open_positions_count ?? 0} />
          </div>
        </Card>

        <Card title="Volume & Activity">
          <div className={styles.metricGrid}>
            <Metric label="Total Volume"   value={`$${formatBalance(trader.total_volume_usdc)}`} />
            <Metric label="Avg Trade Size" value={formatBalance(trader.avg_trade_size_usdc)} />
            <Metric label="Last Updated"   value={trader.last_updated ? new Date(trader.last_updated).toLocaleString() : 'N/A'} />
          </div>
        </Card>

        {trader.user_role && trader.user_role !== 'unknown' && (
          <Card title="Account Role">
            <div className={styles.metricGrid}>
              <Metric label="Role" value={trader.user_role === 'subAccount' ? 'Sub Account' : 'Master'} />
              {trader.user_role === 'subAccount' && (
                <Metric label="Master" value={
                  trader.master_wallet
                    ? <span style={{ cursor: 'pointer', color: '#5865f2', fontSize: '13px', fontFamily: 'monospace' }} onClick={() => navigate(`/traders/${trader.master_wallet}`)} title={trader.master_wallet}>{fmtAddr(trader.master_wallet)}</span>
                    : <span style={{ color: '#96989d' }}>Unknown Trader</span>
                } />
              )}
              {trader.user_role === 'master' && <Metric label="Sub Accounts" value={trader.sub_account_count ?? 0} />}
            </div>
            {trader.user_role === 'master' && trader.sub_accounts?.length > 0 && (
              <div style={{ marginTop: '12px' }}>
                {trader.sub_accounts.map((addr, i) => (
                  <div key={i} style={{ padding: '8px 12px', marginBottom: '6px', background: '#2b2d31', borderRadius: '8px', cursor: 'pointer', color: '#5865f2', fontSize: '13px', fontFamily: 'monospace' }}
                    onClick={() => navigate(`/traders/${addr}`)} title={addr}>
                    {fmtAddr(addr)}
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        <Card title="Account Flags">
          <div className={styles.metricGrid}>
            <Metric label="Bot"             value={trader.is_likely_bot      ? 'Yes' : 'No'} style={{ color: trader.is_likely_bot      ? R : G }} />
            <Metric label="Vault Depositor" value={trader.is_vault_depositor ? 'Yes' : 'No'} style={{ color: trader.is_vault_depositor ? '#f0b132' : '#96989d' }} />
          </div>
        </Card>

        <Card title={`Open Positions${trader.open_positions?.length ? ` (${trader.open_positions_count})` : ''}`} wide>
          {trader.open_positions?.length > 0 ? (
            <div className={styles.positionsTable}>
              {trader.open_positions.map((pos, i) => (
                <div key={i} className={styles.positionCard}>
                  <div className={styles.positionHeader}>
                    <span className={styles.positionCoin}>{pos.asset || 'Unknown'}</span>
                    <span className={styles.positionSide} style={{ color: pos.direction === 'LONG' ? G : R }}>{pos.direction || 'N/A'}</span>
                  </div>
                  <div className={styles.positionDetails}>
                    {[
                      ['Size',          pos.size?.toFixed(4) ?? '0'],
                      ['Entry',         `$${pos.entry_price?.toFixed(2) ?? '0'}`],
                      ['Unrealized PnL', fmtPnl(pos.unrealized_pnl ?? 0), { color: pnlColor(pos.unrealized_pnl ?? 0) }],
                    ].map(([label, value, style]) => (
                      <div key={label} className={styles.positionMetric}>
                        <span>{label}:</span><span style={style}>{value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ padding: '40px', textAlign: 'center', color: '#96989d' }}><p>No open positions</p></div>
          )}
        </Card>
      </div>
    </div>
  );
}
