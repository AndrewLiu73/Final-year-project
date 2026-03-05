import { useState, useMemo } from 'react';
import { useProfitableTraders } from '../hooks/useProfitability';
import { useNavigate } from 'react-router-dom';
import styles from './profitability.module.css';
import useUserId from "../hooks/useUsers";

export default function ProfitableTradersPage() {
  const navigate = useNavigate();
  const userId = useUserId();

  const [minWinrateInput, setMinWinrateInput]   = useState('');
  const [maxDrawdownInput, setMaxDrawdownInput] = useState('');
  const [minBalanceInput, setMinBalanceInput]   = useState('');
  const [maxBalanceInput, setMaxBalanceInput]   = useState('');
  const [pageSizeInput, setPageSizeInput]       = useState('100');
  const [botFilterInput, setBotFilterInput]     = useState('default');

  const [appliedFilters, setAppliedFilters] = useState({
    minWinrate:  undefined,
    maxDrawdown: undefined,
    minBalance:  undefined,
    maxBalance:  undefined,
    botFilter:   'default',
  });

  const [pageSize, setPageSize]           = useState(100);
  const [searchQuery, setSearchQuery]     = useState('');
  const [sortBy, setSortBy]               = useState('pnl');
  const [sortDirection, setSortDirection] = useState('desc');

  const {
    traders,
    loading,
    initialLoading,
    error,
    pagination,
    loadMore,
    hasMore
  } = useProfitableTraders(appliedFilters, pageSize, sortBy, sortDirection);

  function addToWatchlist(wallet) {
    if (!userId) return;
    fetch("http://localhost:8000/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, wallet_address: wallet, label: wallet })
    }).then(res => {
      if (res.status === 409) alert("Already in watchlist");
      else alert("Added to watchlist!");
    });
  }

  const handleApplyFilters = () => {
    setAppliedFilters({
      minWinrate:  minWinrateInput  ? parseFloat(minWinrateInput)  : undefined,
      maxDrawdown: maxDrawdownInput ? parseFloat(maxDrawdownInput) : undefined,
      minBalance:  minBalanceInput  ? parseFloat(minBalanceInput)  : undefined,
      maxBalance:  maxBalanceInput  ? parseFloat(maxBalanceInput)  : undefined,
      botFilter:   botFilterInput,
    });
    const newPageSize = parseInt(pageSizeInput) || 100;
    setPageSize(Math.min(Math.max(newPageSize, 10), 200));
  };

  const handleClearFilters = () => {
    setMinWinrateInput('');
    setMaxDrawdownInput('');
    setMinBalanceInput('');
    setMaxBalanceInput('');
    setPageSizeInput('100');
    setBotFilterInput('default');
    setAppliedFilters({
      minWinrate:  undefined,
      maxDrawdown: undefined,
      minBalance:  undefined,
      maxBalance:  undefined,
      botFilter:   'default',
    });
    setPageSize(100);
  };

  const hasUnappliedChanges = useMemo(() => {
    const currentInputs = {
      minWinrate:  minWinrateInput  ? parseFloat(minWinrateInput)  : undefined,
      maxDrawdown: maxDrawdownInput ? parseFloat(maxDrawdownInput) : undefined,
      minBalance:  minBalanceInput  ? parseFloat(minBalanceInput)  : undefined,
      maxBalance:  maxBalanceInput  ? parseFloat(maxBalanceInput)  : undefined,
      botFilter:   botFilterInput,
    };
    const inputPageSize   = parseInt(pageSizeInput) || 100;
    const pageSizeChanged = inputPageSize !== pageSize;
    return JSON.stringify(currentInputs) !== JSON.stringify(appliedFilters) || pageSizeChanged;
  }, [minWinrateInput, maxDrawdownInput, minBalanceInput, maxBalanceInput, pageSizeInput, botFilterInput, appliedFilters, pageSize]);

  const handleSort = (column) => {
    if (sortBy === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(column);
      setSortDirection('desc');
    }
  };

const formatBalance = (val) => {
    if (val === null || val === undefined) return '$0';
    const abs  = Math.abs(val);
    const sign = val < 0 ? '-' : '';
    if (abs >= 1_000_000_000_000) return `${sign}$${(abs / 1_000_000_000_000).toFixed(2)}T`;
    if (abs >= 1_000_000_000)     return `${sign}$${(abs / 1_000_000_000).toFixed(2)}B`;
    if (abs >= 1_000_000)         return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000)             return `${sign}$${(abs / 1_000).toFixed(1)}K`;
    return `${sign}$${abs.toFixed(0)}`;
};


  const handleWalletClick = (wallet) => {
    navigate(`/trader/${wallet}`);
  };

  const filteredTraders = useMemo(() => {
    if (!searchQuery) return traders;
    return traders.filter(trader =>
      trader.wallet.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [traders, searchQuery]);

  const stats = useMemo(() => {
    const profitableCount = filteredTraders.filter(t => t.isProfitable).length;
    const totalGain       = filteredTraders.reduce((sum, t) => sum + t.gainDollar, 0);
    const avgGain         = filteredTraders.length > 0 ? totalGain / filteredTraders.length : 0;
    const avgWinrate      = filteredTraders.length > 0
      ? filteredTraders.reduce((sum, t) => sum + (t.winrate || 0), 0) / filteredTraders.length
      : 0;
    return {
      loaded:     traders.length,
      total:      pagination.total_count,
      displayed:  filteredTraders.length,
      profitable: profitableCount,
      totalGain,
      avgGain,
      avgWinrate,
    };
  }, [filteredTraders, traders.length, pagination]);

  const SortIndicator = ({ column }) => {
    if (sortBy !== column) return null;
    return (
      <span className={styles.sortIndicator}>
        {sortDirection === 'asc' ? '↑' : '↓'}
      </span>
    );
  };

  if (initialLoading) {
    return (
      <div className={styles.discordContainer}>
        <div className={styles.loadingState}>
          <div className={styles.spinner}></div>
          <p>Loading traders...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.discordContainer}>
        <div className={styles.errorState}>
          <p>Error: {error}</p>
          <button onClick={() => window.location.reload()}>Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.discordContainer}>

      {/* Sidebar */}
      <div className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <h2>Filters</h2>
          <span className={styles.badge}>{stats.total}</span>
        </div>

        <div className={styles.filterSection}>
          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Min Winrate %</span>
            <input
              type="number"
              placeholder="e.g. 60"
              value={minWinrateInput}
              onChange={(e) => setMinWinrateInput(e.target.value)}
              className={styles.discordInput}
              min="0"
              max="100"
              onKeyPress={(e) => e.key === 'Enter' && handleApplyFilters()}
            />
          </label>

          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Max Drawdown %</span>
            <input
              type="number"
              placeholder="e.g. 20"
              value={maxDrawdownInput}
              onChange={(e) => setMaxDrawdownInput(e.target.value)}
              className={styles.discordInput}
              onKeyPress={(e) => e.key === 'Enter' && handleApplyFilters()}
            />
            <span className={styles.helperText}>Lower is better</span>
          </label>

          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Min Balance $</span>
            <input
              type="number"
              placeholder="e.g. 1000"
              value={minBalanceInput}
              onChange={(e) => setMinBalanceInput(e.target.value)}
              className={styles.discordInput}
              onKeyPress={(e) => e.key === 'Enter' && handleApplyFilters()}
            />
          </label>

          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Max Balance $</span>
            <input
              type="number"
              placeholder="e.g. 50000"
              value={maxBalanceInput}
              onChange={(e) => setMaxBalanceInput(e.target.value)}
              className={styles.discordInput}
              onKeyPress={(e) => e.key === 'Enter' && handleApplyFilters()}
            />
          </label>

          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Bot Filter</span>
            <select
              value={botFilterInput}
              onChange={(e) => setBotFilterInput(e.target.value)}
              className={styles.discordSelect}
            >
              <option value="default">All traders</option>
              <option value="no">Humans only</option>
              <option value="yes">Bots only</option>
            </select>
            <span className={styles.helperText}>Filter by bot detection</span>
          </label>

          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Traders Per Page</span>
            <select
              value={pageSizeInput}
              onChange={(e) => setPageSizeInput(e.target.value)}
              className={styles.discordSelect}
            >
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
              <option value="150">150</option>
              <option value="200">200</option>
            </select>
            <span className={styles.helperText}>How many to load at once</span>
          </label>

          <div className={styles.filterActions}>
            <button
              onClick={handleApplyFilters}
              className={`${styles.applyButton} ${hasUnappliedChanges ? styles.applyButtonActive : ''}`}
              disabled={!hasUnappliedChanges}
            >
              {hasUnappliedChanges ? 'Apply Filters' : 'Filters Applied'}
            </button>
            <button onClick={handleClearFilters} className={styles.clearButton}>
              Clear All
            </button>
          </div>
        </div>

        <div className={styles.statsPanel}>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Loaded</span>
            <span className={styles.statValue}>{stats.loaded.toLocaleString()}</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Profitable</span>
            <span className={styles.statValueGreen}>{stats.profitable.toLocaleString()}</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Avg Gain</span>
            <span className={styles.statValue}>
              ${stats.avgGain.toLocaleString('en-US', { maximumFractionDigits: 0 })}
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Avg WR</span>
            <span className={styles.statValue}>{stats.avgWinrate.toFixed(1)}%</span>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className={styles.mainContent}>
        <div className={styles.channelHeader}>
          <div className={styles.channelInfo}>
            <span className={styles.channelIcon}>#</span>
            <h1 className={styles.channelName}>profitable-traders</h1>
            <span className={styles.channelCount}>{stats.displayed} traders</span>
          </div>
          <div className={styles.searchBar}>
            <input
              type="text"
              placeholder="Search wallets..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={styles.searchInput}
            />
          </div>
        </div>

        <div className={styles.tableContainer}>
          <div className={styles.tableHeader}>
            <div className={styles.colWallet}>Wallet</div>
            <div className={`${styles.colBalance} ${styles.sortable}`} onClick={() => handleSort('balance')}>
              Balance <SortIndicator column="balance" />
            </div>
            <div className={`${styles.colPnl} ${styles.sortable}`} onClick={() => handleSort('pnl')}>
              All-Time PnL <SortIndicator column="pnl" />
            </div>
            <div className={`${styles.colOpenTrades} ${styles.sortable}`} onClick={() => handleSort('openTrades')}>
              Open Trades <SortIndicator column="openTrades" />
            </div>
            <div className={`${styles.colWinrate} ${styles.sortable}`} onClick={() => handleSort('winrate')}>
              Winrate <SortIndicator column="winrate" />
            </div>
            <div className={`${styles.colDrawdown} ${styles.sortable}`} onClick={() => handleSort('drawdown')}>
              Max DD <SortIndicator column="drawdown" />
            </div>
            <div className={styles.colWatch}>Watch</div>
          </div>

          <div className={styles.tableBody}>
            {filteredTraders.length > 0 ? (
              <>
                {filteredTraders.map((trader, index) => {
                  const profitColor = trader.isProfitable ? '#3ba55d' : '#ed4245';
                  return (
                    <div key={`${trader.wallet}-${index}`} className={styles.tableRow}>
                      <div className={styles.colWallet}>
                        <div className={styles.walletCell}>
                          <div className={styles.statusDot} style={{ background: profitColor }} />
                          <span
                            className={styles.walletText}
                            title={trader.wallet}
                            onClick={() => handleWalletClick(trader.wallet)}
                          >
                            {trader.wallet.slice(0, 6)}...{trader.wallet.slice(-4)}
                          </span>
                        </div>
                      </div>

                      <div className={styles.colBalance}>
                        <span className={styles.valueText}>{formatBalance(trader.currentBalance)}</span>
                      </div>

                     <div className={styles.colPnl}>
                          <div className={styles.pnlCell}>
                              <span className={styles.pnlValue} style={{ color: profitColor }}>
                                  {trader.gainDollar > 0 ? '+' : ''}{formatBalance(trader.gainDollar)}
                              </span>
                              <span className={styles.pnlPercent} style={{ color: profitColor }}>
                                  ({trader.gainPercent > 0 ? '+' : ''}{trader.gainPercent.toFixed(1)}%)
                              </span>
                          </div>
                      </div>


                      <div className={styles.colOpenTrades}>
                        <span className={styles.valueText}>{trader.openPositionsCount || 0}</span>
                      </div>

                      <div className={styles.colWinrate}>
                        <span className={styles.valueText}>
                          {trader.winrate ? `${trader.winrate.toFixed(1)}%` : '-'}
                        </span>
                      </div>

                      <div className={styles.colDrawdown}>
                        <span className={styles.valueText}>
                          {trader.maxDrawdown ? `${trader.maxDrawdown.toFixed(1)}%` : '-'}
                        </span>
                      </div>

                       <div className={styles.colWatch}>
                        <span
                          className={styles.watchStar}
                          onClick={() => addToWatchlist(trader.wallet)}
                          title="Add to watchlist"
                        >
                          ★
                        </span>
                      </div>
                    </div>
                  );
                })}

                {hasMore && (
                  <div className={styles.loadMoreRow}>
                    <button onClick={loadMore} disabled={loading} className={styles.loadMoreBtn}>
                      {loading ? (
                        <>
                          <div className={styles.smallSpinner}></div>
                          Loading...
                        </>
                      ) : (
                        `Load More (${(pagination.total_count - stats.loaded).toLocaleString()} remaining)`
                      )}
                    </button>
                  </div>
                )}

                {!hasMore && stats.loaded > 0 && (
                  <div className={styles.endMessage}>
                    End of results • {stats.total.toLocaleString()} traders
                  </div>
                )}
              </>
            ) : (
              <div className={styles.emptyState}>
                <p>No traders match your filters</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
