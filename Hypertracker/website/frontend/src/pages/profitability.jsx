import { useState, useMemo, useEffect } from 'react';
import { useProfitableTraders } from '../hooks/useProfitability';
import { useNavigate } from 'react-router-dom';
import styles from './profitability.module.css';
import useUserId from "../hooks/useUsers";
import useSort from '../hooks/useSort';
import TraderTable from '../components/traderTable';

export default function ProfitableTradersPage() {
  const navigate = useNavigate();
  const userId = useUserId();

  const [minWinrateInput, setMinWinrateInput]           = useState('');
  const [maxDrawdownInput, setMaxDrawdownInput]         = useState('');
  const [minBalanceInput, setMinBalanceInput]           = useState('');
  const [maxBalanceInput, setMaxBalanceInput]           = useState('');
  const [pageSizeInput, setPageSizeInput]               = useState('100');
  const [botFilterInput, setBotFilterInput]             = useState('default');
  const [activityFilterInput, setActivityFilterInput]   = useState('all');
  const [positionsFilterInput, setPositionsFilterInput] = useState('all');
  const { sortBy, setSortBy, sortDirection, setSortDirection, handleSort } = useSort('pnl', 'desc');
  const [searchQuery, setSearchQuery] = useState('');
  const [appliedFilters, setAppliedFilters] = useState({
    minWinrate:      undefined,
    maxDrawdown:     undefined,
    minBalance:      undefined,
    maxBalance:      undefined,
    botFilter:       'default',
    positionsFilter: 'all',
    activityFilter:  'all',
    search:          '',
  });

  const [pageSize, setPageSize] = useState(100);

  // Restore filters from sessionStorage when navigating back from a trader page
  useEffect(() => {
    const saved = sessionStorage.getItem('traderFilters');
    if (!saved) return;

    const f = JSON.parse(saved);
    setMinWinrateInput(f.minWinrateInput           ?? '');
    setMaxDrawdownInput(f.maxDrawdownInput         ?? '');
    setMinBalanceInput(f.minBalanceInput           ?? '');
    setMaxBalanceInput(f.maxBalanceInput           ?? '');
    setPageSizeInput(f.pageSizeInput               ?? '100');
    setBotFilterInput(f.botFilterInput             ?? 'default');
    setActivityFilterInput(f.activityFilterInput   ?? 'all');
    setPositionsFilterInput(f.positionsFilterInput ?? 'all');
    setSortBy(f.sortBy                             ?? 'pnl');
    setSortDirection(f.sortDirection               ?? 'desc');
    setSearchQuery(f.searchQuery                   ?? '');

    setAppliedFilters({
      minWinrate:      f.minWinrateInput  ? parseFloat(f.minWinrateInput)  : undefined,
      maxDrawdown:     f.maxDrawdownInput ? parseFloat(f.maxDrawdownInput) : undefined,
      minBalance:      f.minBalanceInput  ? parseFloat(f.minBalanceInput)  : undefined,
      maxBalance:      f.maxBalanceInput  ? parseFloat(f.maxBalanceInput)  : undefined,
      botFilter:       f.botFilterInput       ?? 'default',
      positionsFilter: f.positionsFilterInput ?? 'all',
      activityFilter:  f.activityFilterInput  ?? 'all',
      search:          f.searchQuery          ?? '',
    });
    setPageSize(parseInt(f.pageSizeInput) || 100);
  }, [setSortBy, setSortDirection]);

  // Debounce search — fires a real backend request after 400ms of no typing
  useEffect(() => {
    const timer = setTimeout(() => {
      setAppliedFilters(prev => ({ ...prev, search: searchQuery }));
    }, 400);
    return () => clearTimeout(timer);
  }, [searchQuery]);

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
    fetch(`http://localhost:8000/api/watchlist`, {
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
      minWinrate:      minWinrateInput  ? parseFloat(minWinrateInput)  : undefined,
      maxDrawdown:     maxDrawdownInput ? parseFloat(maxDrawdownInput) : undefined,
      minBalance:      minBalanceInput  ? parseFloat(minBalanceInput)  : undefined,
      maxBalance:      maxBalanceInput  ? parseFloat(maxBalanceInput)  : undefined,
      botFilter:       botFilterInput,
      positionsFilter: positionsFilterInput,
      activityFilter:  activityFilterInput,
      search:          searchQuery,
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
    setActivityFilterInput('all');
    setPositionsFilterInput('all');
    setSearchQuery('');
    setAppliedFilters({
      minWinrate:      undefined,
      maxDrawdown:     undefined,
      minBalance:      undefined,
      maxBalance:      undefined,
      botFilter:       'default',
      positionsFilter: 'all',
      activityFilter:  'all',
      search:          '',
    });
    setPageSize(100);
  };

  const hasUnappliedChanges = useMemo(() => {
    const currentInputs = {
      minWinrate:      minWinrateInput  ? parseFloat(minWinrateInput)  : undefined,
      maxDrawdown:     maxDrawdownInput ? parseFloat(maxDrawdownInput) : undefined,
      minBalance:      minBalanceInput  ? parseFloat(minBalanceInput)  : undefined,
      maxBalance:      maxBalanceInput  ? parseFloat(maxBalanceInput)  : undefined,
      botFilter:       botFilterInput,
      positionsFilter: positionsFilterInput,
      activityFilter:  activityFilterInput,
      search:          searchQuery,
    };
    const inputPageSize   = parseInt(pageSizeInput) || 100;
    const pageSizeChanged = inputPageSize !== pageSize;
    return JSON.stringify(currentInputs) !== JSON.stringify(appliedFilters) || pageSizeChanged;
  }, [
    minWinrateInput, maxDrawdownInput, minBalanceInput, maxBalanceInput,
    pageSizeInput, botFilterInput, activityFilterInput, positionsFilterInput,
    appliedFilters, pageSize, searchQuery
  ]);

  const handleWalletClick = (wallet) => {
    sessionStorage.setItem('traderFilters', JSON.stringify({
      minWinrateInput,
      maxDrawdownInput,
      minBalanceInput,
      maxBalanceInput,
      pageSizeInput,
      botFilterInput,
      activityFilterInput,
      positionsFilterInput,
      sortBy,
      sortDirection,
      searchQuery,
    }));
    navigate(`/trader/${wallet}`);
  };

  const stats = useMemo(() => {
    const profitableCount = traders.filter(t => t.isProfitable).length;
    const totalGain       = traders.reduce((sum, t) => sum + t.gainDollar, 0);
    const avgGain         = traders.length > 0 ? totalGain / traders.length : 0;
    const avgWinrate      = traders.length > 0
      ? traders.reduce((sum, t) => sum + (t.winrate || 0), 0) / traders.length
      : 0;
    return {
      loaded:     traders.length,
      total:      pagination.total_count,
      displayed:  traders.length,
      profitable: profitableCount,
      totalGain,
      avgGain,
      avgWinrate,
    };
  }, [traders, pagination]);

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
            <span className={styles.labelText}>Open Positions</span>
            <select
              value={positionsFilterInput}
              onChange={(e) => setPositionsFilterInput(e.target.value)}
              className={styles.discordSelect}
            >
              <option value="all">All traders</option>
              <option value="yes">In positions</option>
              <option value="no">No positions</option>
            </select>
          </label>

          <label className={styles.filterLabel}>
            <span className={styles.labelText}>Activity</span>
            <select
              value={activityFilterInput}
              onChange={(e) => setActivityFilterInput(e.target.value)}
              className={styles.discordSelect}
            >
              <option value="all">All traders</option>
              <option value="active">Active only</option>
              <option value="inactive">Inactive only</option>
            </select>
            <span className={styles.helperText}>Trading volume &gt; 0</span>
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

        <TraderTable
          traders={traders}
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
