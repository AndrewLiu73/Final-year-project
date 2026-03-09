import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatBalance } from '../utils/formatters';
import styles from './openPositions.module.css';
import API_BASE from '../config';

const REFRESH_INTERVAL = 30_000; // 30s — backend cache is 30s anyway

export default function OpenPositionsPage() {
  const navigate = useNavigate();

  // data
  const [positions, setPositions] = useState([]);
  const [concentration, setConcentration] = useState([]);
  const [pagination, setPagination] = useState({ total_count: 0, unique_wallets: 0, page: 1, page_size: 50, has_more: false });
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);

  // filters
  const [minNotional, setMinNotional] = useState('10000');
  const [assetFilter, setAssetFilter] = useState('');
  const [directionFilter, setDirectionFilter] = useState('');
  const [sortBy, setSortBy] = useState('notional_usd');
  const [sortDirection, setSortDirection] = useState('desc');

  const abortRef = useRef(null);

  // ── fetch positions ──
  const fetchPositions = useCallback(async (page = 1, append = false) => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();

    try {
      const params = new URLSearchParams({
        min_notional_usd: minNotional || '0',
        sort_by: sortBy,
        sort_direction: sortDirection,
        page: String(page),
        page_size: '50',
      });
      if (assetFilter) params.append('asset', assetFilter);
      if (directionFilter) params.append('direction', directionFilter);

      const res = await fetch(`${API_BASE}/api/large-positions?${params}`, { signal: abortRef.current.signal });
      const json = await res.json();

      setPositions(prev => append ? [...prev, ...json.data] : json.data);
      setPagination(json.pagination);
      setLastUpdate(new Date());
    } catch (err) {
      if (err.name !== 'AbortError') console.error('fetch positions failed:', err);
    }
  }, [minNotional, assetFilter, directionFilter, sortBy, sortDirection]);

  // ── fetch concentration ──
  const fetchConcentration = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/asset-concentration`);
      const json = await res.json();
      setConcentration(json);
    } catch (err) {
      console.error('fetch concentration failed:', err);
    }
  }, []);

  // initial load + whenever filters change
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchPositions(1), fetchConcentration()]).finally(() => setLoading(false));
  }, [fetchPositions, fetchConcentration]);

  // auto-refresh
  useEffect(() => {
    const id = setInterval(() => {
      fetchPositions(1);
      fetchConcentration();
    }, REFRESH_INTERVAL);
    return () => clearInterval(id);
  }, [fetchPositions, fetchConcentration]);

  // ── sorting ──
  const handleSort = (col) => {
    if (sortBy === col) {
      setSortDirection(d => d === 'desc' ? 'asc' : 'desc');
    } else {
      setSortBy(col);
      setSortDirection('desc');
    }
  };

  const SortIndicator = ({ column }) => {
    if (sortBy !== column) return null;
    return <span className={styles.sortIndicator}>{sortDirection === 'desc' ? '▼' : '▲'}</span>;
  };

  // ── summary stats ──
  const stats = useMemo(() => {
    const totalNotional = positions.reduce((s, p) => s + (p.notional_usd || 0), 0);
    const totalUpnl = positions.reduce((s, p) => s + (p.unrealized_pnl || 0), 0);
    const longs = positions.filter(p => p.direction === 'LONG').length;
    const shorts = positions.filter(p => p.direction === 'SHORT').length;
    return {
      totalNotional, totalUpnl, longs, shorts,
      total: pagination.total_count,
      uniqueWallets: pagination.unique_wallets,
    };
  }, [positions, pagination.total_count, pagination.unique_wallets]);

  // ── loading state ──
  if (loading) {
    return (
      <div className={styles.loadingState}>
        <div className={styles.spinner} />
        <span>Loading open positions...</span>
      </div>
    );
  }

  // ── top concentration assets for the dropdown ──
  const topAssets = concentration.slice(0, 30).map(c => c.asset);

  return (
    <div className={styles.container}>

      {/* ── Sidebar ── */}
      <div className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <h2>Filters</h2>
          <span className={styles.badge}>{stats.total.toLocaleString()}</span>
        </div>

        <div className={styles.filterSection}>
          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Min Notional $</span>
            <input
              type="number"
              placeholder="e.g. 10000"
              value={minNotional}
              onChange={e => setMinNotional(e.target.value)}
              className={styles.discordInput}
            />
            <span className={styles.helperText}>Size x Entry Price</span>
          </label>

          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Asset</span>
            <select
              value={assetFilter}
              onChange={e => setAssetFilter(e.target.value)}
              className={styles.discordSelect}
            >
              <option value="">All assets</option>
              {topAssets.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>

          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Direction</span>
            <select
              value={directionFilter}
              onChange={e => setDirectionFilter(e.target.value)}
              className={styles.discordSelect}
            >
              <option value="">All</option>
              <option value="LONG">Long only</option>
              <option value="SHORT">Short only</option>
            </select>
          </label>
        </div>

        <div className={styles.divider} />

        {/* summary stats */}
        <div className={styles.statsPanel}>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Positions</span>
            <span className={styles.statValue}>{stats.total.toLocaleString()}</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Unique Wallets</span>
            <span className={styles.statValue}>{stats.uniqueWallets.toLocaleString()}</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Longs</span>
            <span className={styles.statValueGreen}>{stats.longs.toLocaleString()}</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Shorts</span>
            <span className={styles.statValueRed}>{stats.shorts.toLocaleString()}</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Notional</span>
            <span className={styles.statValue}>{formatBalance(stats.totalNotional)}</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Total uPnL</span>
            <span className={stats.totalUpnl >= 0 ? styles.statValueGreen : styles.statValueRed}>
              {formatBalance(stats.totalUpnl)}
            </span>
          </div>
        </div>

        <div className={styles.divider} />

        {/* concentration mini-bars */}
        <div className={styles.concentrationSection}>
          <div className={styles.concentrationTitle}>Asset Concentration</div>
          <div className={styles.concentrationList}>
            {concentration.slice(0, 12).map(c => {
              const total = c.longs + c.shorts;
              const longPct = total > 0 ? (c.longs / total) * 100 : 50;
              return (
                <div key={c.asset} className={styles.concRow}>
                  <span className={styles.concAsset}>{c.asset}</span>
                  <div className={styles.concBar}>
                    <div className={styles.concLong} style={{ width: `${longPct}%` }} />
                    <div className={styles.concShort} style={{ width: `${100 - longPct}%` }} />
                  </div>
                  <span className={styles.concRatio}>
                    {c.longs}/{c.shorts}
                    {c.unique_wallets != null && <span className={styles.concWallets}> ({c.unique_wallets})</span>}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── Main ── */}
      <div className={styles.mainContent}>
        <div className={styles.channelHeader}>
          <div className={styles.channelInfo}>
            <span className={styles.channelIcon}>#</span>
            <h1 className={styles.channelName}>open-positions</h1>
            <span className={styles.channelMeta}>
              {stats.total.toLocaleString()} positions from {stats.uniqueWallets.toLocaleString()} wallets
            </span>
          </div>
          <div className={styles.refreshInfo}>
            <div className={styles.liveDot} />
            <span>
              {lastUpdate ? `Updated ${lastUpdate.toLocaleTimeString()}` : 'Loading...'}
            </span>
          </div>
        </div>

        <div className={styles.tableContainer}>
          <div className={styles.tableHeader}>
            <div>#</div>
            <div>Asset</div>
            <div>Side</div>
            <div className={styles.sortable} onClick={() => handleSort('size')}>
              Size <SortIndicator column="size" />
            </div>
            <div>Entry</div>
            <div className={styles.sortable} onClick={() => handleSort('notional_usd')}>
              Notional <SortIndicator column="notional_usd" />
            </div>
            <div className={styles.sortable} onClick={() => handleSort('unrealized_pnl')}>
              uPnL <SortIndicator column="unrealized_pnl" />
            </div>
            <div>Wallet</div>
            <div className={styles.sortable} onClick={() => handleSort('account_value')}>
              Acct Value <SortIndicator column="account_value" />
            </div>
          </div>

          <div className={styles.tableBody}>
            {positions.length > 0 ? (
              <>
                {positions.map((p, idx) => {
                  const pnl = p.unrealized_pnl || 0;
                  const pnlClass = pnl > 0 ? styles.pnlPositive : pnl < 0 ? styles.pnlNegative : styles.pnlZero;

                  return (
                    <div
                      key={`${p.wallet_address}-${p.asset}-${p.direction}`}
                      className={styles.tableRow}
                      onClick={() => navigate(`/trader/${p.wallet_address}`)}
                    >
                      <div className={styles.rankCell}>{idx + 1}</div>
                      <div className={styles.assetCell}>{p.asset}</div>
                      <div>
                        <span className={p.direction === 'LONG' ? styles.directionLong : styles.directionShort}>
                          {p.direction}
                        </span>
                      </div>
                      <div className={styles.valueText}>
                        {p.size?.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                      </div>
                      <div className={styles.valueText}>
                        ${p.entry_price?.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </div>
                      <div className={styles.valueText}>
                        {formatBalance(p.notional_usd)}
                      </div>
                      <div className={pnlClass}>
                        {pnl > 0 ? '+' : ''}{formatBalance(pnl)}
                      </div>
                      <div>
                        <span
                          className={styles.walletText}
                          onClick={e => { e.stopPropagation(); navigate(`/trader/${p.wallet_address}`); }}
                        >
                          {p.wallet_address.slice(0, 6)}...{p.wallet_address.slice(-4)}
                        </span>
                      </div>
                      <div className={styles.valueText}>
                        {formatBalance(p.account_value)}
                      </div>
                    </div>
                  );
                })}

                {pagination.has_more && (
                  <div className={styles.loadMoreRow}>
                    <button
                      onClick={() => fetchPositions(pagination.page + 1, true)}
                      className={styles.loadMoreBtn}
                    >
                      Load More ({(pagination.total_count - positions.length).toLocaleString()} remaining)
                    </button>
                  </div>
                )}

                {!pagination.has_more && positions.length > 0 && (
                  <div className={styles.endMessage}>
                    End of results &bull; {pagination.total_count.toLocaleString()} positions
                  </div>
                )}
              </>
            ) : (
              <div className={styles.emptyState}>
                <p>No positions match your filters</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

