import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatBalance } from '../utils/formatters';
import styles from './openPositions.module.css';
import useSort from '../hooks/useSort';
import SortIndicator from '../components/sortIndicator';
import API_BASE from '../config';

const REFRESH_INTERVAL = 30_000;

const SORT_COLS = [
  { key: 'size',           label: 'Size'        },
  { key: 'entry_price',    label: 'Entry Price' },
  { key: 'notional_usd',   label: 'Notional'    },
  { key: 'unrealized_pnl', label: 'uPnL'        },
];

export default function OpenPositionsPage() {
  const navigate = useNavigate();
  const [positions,     setPositions]     = useState([]);
  const [concentration, setConcentration] = useState([]);
  const [pagination,    setPagination]    = useState({ total_count: 0, unique_wallets: 0, page: 1, page_size: 50, has_more: false });
  const [loading,       setLoading]       = useState(true);
  const [lastUpdate,    setLastUpdate]    = useState(null);
  const [assetFilter,     setAssetFilter]     = useState('');
  const [directionFilter, setDirectionFilter] = useState('');
  const { sortBy, sortDirection, handleSort } = useSort('notional_usd', 'desc');
  const abortRef = useRef(null);

  const fetchPositions = useCallback(async (page = 1, append = false) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    try {
      const params = new URLSearchParams({ sort_by: sortBy, sort_direction: sortDirection, page: String(page), page_size: '50' });
      if (assetFilter)     params.append('asset',     assetFilter);
      if (directionFilter) params.append('direction', directionFilter);
      const json = await fetch(`${API_BASE}/api/large-positions?${params}`, { signal: abortRef.current.signal }).then(r => r.json());
      setPositions(prev => append ? [...prev, ...json.data] : json.data);
      setPagination(json.pagination);
      setLastUpdate(new Date());
    } catch (err) {
      if (err.name !== 'AbortError') console.error('fetch positions failed:', err);
    }
  }, [assetFilter, directionFilter, sortBy, sortDirection]);

  const fetchConcentration = useCallback(async () => {
    try {
      setConcentration(await fetch(`${API_BASE}/api/asset-concentration`).then(r => r.json()));
    } catch (err) { console.error('fetch concentration failed:', err); }
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchPositions(1), fetchConcentration()]).finally(() => setLoading(false));
  }, [fetchPositions, fetchConcentration]);

  useEffect(() => {
    const id = setInterval(() => { fetchPositions(1); fetchConcentration(); }, REFRESH_INTERVAL);
    return () => clearInterval(id);
  }, [fetchPositions, fetchConcentration]);

  const stats = useMemo(() => ({
    totalNotional: positions.reduce((s, p) => s + (p.notional_usd   || 0), 0),
    totalUpnl:     positions.reduce((s, p) => s + (p.unrealized_pnl || 0), 0),
    longs:         positions.filter(p => p.direction === 'LONG').length,
    shorts:        positions.filter(p => p.direction === 'SHORT').length,
    total:         pagination.total_count,
    uniqueWallets: pagination.unique_wallets,
  }), [positions, pagination.total_count, pagination.unique_wallets]);

  if (loading) return (
    <div className={styles.loadingState}>
      <div className={styles.spinner} />
      <span>Loading open positions...</span>
    </div>
  );

  const STAT_ROWS = [
    ['Positions',      stats.total.toLocaleString(),         null                          ],
    ['Unique Wallets', stats.uniqueWallets.toLocaleString(), null                          ],
    ['Longs',          stats.longs.toLocaleString(),         styles.statValueGreen         ],
    ['Shorts',         stats.shorts.toLocaleString(),        styles.statValueRed           ],
    ['Notional',       formatBalance(stats.totalNotional),   null                          ],
    ['Total uPnL',     formatBalance(stats.totalUpnl),       stats.totalUpnl >= 0 ? styles.statValueGreen : styles.statValueRed],
  ];

  return (
    <div className={styles.container}>

      {/* Sidebar */}
      <div className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <h2>Filters</h2>
          <span className={styles.badge}>{stats.total.toLocaleString()}</span>
        </div>

        <div className={styles.filterSection}>
          {[
            { label: 'Asset', value: assetFilter, set: setAssetFilter,
              options: [['', 'All assets'], ...concentration.slice(0, 30).map(c => [c.asset, c.asset])] },
            { label: 'Direction', value: directionFilter, set: setDirectionFilter,
              options: [['', 'All'], ['LONG', 'Long only'], ['SHORT', 'Short only']] },
          ].map(({ label, value, set, options }) => (
            <label key={label} className={styles.filterLabel}>
              <span className={styles.labelText}>{label}</span>
              <select value={value} onChange={e => set(e.target.value)} className={styles.discordSelect}>
                {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          ))}
        </div>

        <div className={styles.divider} />

        <div className={styles.statsPanel}>
          {STAT_ROWS.map(([label, value, cls]) => (
            <div key={label} className={styles.statItem}>
              <span className={styles.statLabel}>{label}</span>
              <span className={cls || styles.statValue}>{value}</span>
            </div>
          ))}
        </div>

        <div className={styles.divider} />

        <div className={styles.concentrationSection}>
          <div className={styles.concentrationTitle}>Asset Concentration</div>
          <div className={styles.concentrationList}>
            {concentration.slice(0, 12).map(c => {
              const longPct = (c.longs + c.shorts) > 0 ? (c.longs / (c.longs + c.shorts)) * 100 : 50;
              return (
                <div key={c.asset} className={styles.concRow}>
                  <span className={styles.concAsset}>{c.asset}</span>
                  <div className={styles.concBar}>
                    <div className={styles.concLong}  style={{ width: `${longPct}%` }} />
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

      {/* Main */}
      <div className={styles.mainContent}>
        <div className={styles.channelHeader}>
          <div className={styles.channelInfo}>
            <span className={styles.channelIcon}>#</span>
            <h1 className={styles.channelName}>open-positions</h1>
            <span className={styles.channelMeta}>
              {stats.total.toLocaleString()} positions from {stats.uniqueWallets.toLocaleString()} wallets - positions &gt; 10,000 USD
            </span>
          </div>
          <div className={styles.refreshInfo}>
            <div className={styles.liveDot} />
            <span>{lastUpdate ? `Updated ${lastUpdate.toLocaleTimeString()}` : 'Loading...'}</span>
          </div>
        </div>

        <div className={styles.tableContainer}>
          <div className={styles.tableHeader}>
            {['#', 'Asset', 'Side'].map(h => <div key={h}>{h}</div>)}
            {SORT_COLS.map(({ key, label }) => (
              <div key={key} className={styles.sortable} onClick={() => handleSort(key)}>
                {label} <SortIndicator sortBy={sortBy} column={key} sortDirection={sortDirection} className={styles.sortIndicator} arrowStyle="triangle" />
              </div>
            ))}
            <div>Wallet</div>
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
                      <div className={styles.valueText}>{formatBalance(p.notional_usd)}</div>
                      <div className={pnlClass}>{pnl > 0 ? '+' : ''}{formatBalance(pnl)}</div>
                      <div>
                        <span
                          className={styles.walletText}
                          onClick={e => { e.stopPropagation(); navigate(`/trader/${p.wallet_address}`); }}
                        >
                          {p.wallet_address.slice(0, 6)}...{p.wallet_address.slice(-4)}
                        </span>
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
                {!pagination.has_more && (
                  <div className={styles.endMessage}>
                    End of results &bull; {pagination.total_count.toLocaleString()} positions
                  </div>
                )}
              </>
            ) : (
              <div className={styles.emptyState}><p>No positions match your filters</p></div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}