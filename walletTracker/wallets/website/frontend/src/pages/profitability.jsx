import { useState, useMemo, useEffect } from 'react';
import { useProfitableTraders } from '../hooks/useProfitability';
import { useNavigate } from 'react-router-dom';
import styles from './profitability.module.css';
import useUserId from "../hooks/useUsers";
import API_BASE from '../config';
// pulled sort logic into a shared hook — was getting annoying maintaining it in 3 places
import useSort from '../hooks/useSort';
import TraderTable from '../components/TraderTable';

export default function ProfitableTradersPage() {
  const navigate = useNavigate();
  const userId = useUserId();

  const [minWinrateInput, setMinWinrateInput]   = useState('');
  const [maxDrawdownInput, setMaxDrawdownInput] = useState('');
  const [minBalanceInput, setMinBalanceInput]   = useState('');
  const [maxBalanceInput, setMaxBalanceInput]   = useState('');
  const [pageSizeInput, setPageSizeInput]       = useState('100');
  const [botFilterInput, setBotFilterInput]     = useState('default');
  const [activityFilterInput, setActivityFilterInput] = useState('active');

  const [appliedFilters, setAppliedFilters] = useState({
    minWinrate:  undefined,
    maxDrawdown: undefined,
    minBalance:  undefined,
    maxBalance:  undefined,
    botFilter:   'default',
    activeOnly:  true,
  });
  // restore filters on mount — add this useEffect near the top

useEffect(() => {
    const saved = sessionStorage.getItem('traderFilters');
    if (!saved) return;

    const f = JSON.parse(saved);
    setMinWinrateInput(f.minWinrateInput   ?? '');
    setMaxDrawdownInput(f.maxDrawdownInput ?? '');
    setMinBalanceInput(f.minBalanceInput   ?? '');
    setMaxBalanceInput(f.maxBalanceInput   ?? '');
    setPageSizeInput(f.pageSizeInput       ?? '100');
    setBotFilterInput(f.botFilterInput     ?? 'default');
    setActivityFilterInput(f.activityFilterInput ?? 'active');
    setSortBy(f.sortBy                     ?? 'pnl');
    setSortDirection(f.sortDirection       ?? 'desc');
    setSearchQuery(f.searchQuery           ?? '');

    // also apply them immediately
    setAppliedFilters({
        minWinrate:  f.minWinrateInput  ? parseFloat(f.minWinrateInput)  : undefined,
        maxDrawdown: f.maxDrawdownInput ? parseFloat(f.maxDrawdownInput) : undefined,
        minBalance:  f.minBalanceInput  ? parseFloat(f.minBalanceInput)  : undefined,
        maxBalance:  f.maxBalanceInput  ? parseFloat(f.maxBalanceInput)  : undefined,
        botFilter:   f.botFilterInput   ?? 'default',
        activeOnly:  (f.activityFilterInput ?? 'active') === 'active',
    });
    setPageSize(parseInt(f.pageSizeInput) || 100);
}, []); // empty deps = runs once on mount


  const [pageSize, setPageSize]           = useState(100);
  const [searchQuery, setSearchQuery]     = useState('');
  // useSort hook replaces the old manual handleSort + state that was duplicated everywhere
  const { sortBy, setSortBy, sortDirection, setSortDirection, handleSort } = useSort('pnl', 'desc');

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
    fetch(`${API_BASE}/api/watchlist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: userId, walletAddress: wallet, label: wallet })
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
      activeOnly:  activityFilterInput === 'active',
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
    setActivityFilterInput('active');
    setAppliedFilters({
      minWinrate:  undefined,
      maxDrawdown: undefined,
      minBalance:  undefined,
      maxBalance:  undefined,
      botFilter:   'default',
      activeOnly:  true,
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
      activeOnly:  activityFilterInput === 'active',
    };
    const inputPageSize   = parseInt(pageSizeInput) || 100;
    const pageSizeChanged = inputPageSize !== pageSize;
    return JSON.stringify(currentInputs) !== JSON.stringify(appliedFilters) || pageSizeChanged;
  }, [minWinrateInput, maxDrawdownInput, minBalanceInput, maxBalanceInput, pageSizeInput, botFilterInput, activityFilterInput, appliedFilters, pageSize]);

  // handleSort comes from useSort hook now
  // SortIndicator comes from TraderTable component

const handleWalletClick = (wallet) => {
    sessionStorage.setItem('traderFilters', JSON.stringify({
        minWinrateInput,
        maxDrawdownInput,
        minBalanceInput,
        maxBalanceInput,
        pageSizeInput,
        botFilterInput,
        activityFilterInput,
        sortBy,
        sortDirection,
        searchQuery,
    }));
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
              onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
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
              onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
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
              onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
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
              onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
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
            <span className={styles.labelText}>Activity Filter</span>
            <select
              value={activityFilterInput}
              onChange={(e) => setActivityFilterInput(e.target.value)}
              className={styles.discordSelect}
            >
              <option value="active">Active only</option>
              <option value="all">All traders</option>
            </select>
            <span className={styles.helperText}>Show traders with open positions</span>
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

        {/* Using TraderTable component instead of duplicating table markup here and in watchlist */}
        <TraderTable
          traders={filteredTraders}
          sortBy={sortBy}
          sortDirection={sortDirection}
          handleSort={handleSort}
          onWalletClick={handleWalletClick}
          actionLabel="Watch"
          onAction={addToWatchlist}
          actionIcon="★"
          actionColor="#5865f2"
          styles={styles}
          footer={
            <>
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
          }
        />
      </div>
    </div>
  );
}
