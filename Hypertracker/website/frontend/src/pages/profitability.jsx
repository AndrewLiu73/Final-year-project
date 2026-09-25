import { useState, useMemo, useEffect } from 'react';
import { useProfitableTraders } from '../hooks/useProfitability';
import { useNavigate } from 'react-router-dom';
import styles from './profitability.module.css';
import useUserId from '../hooks/useUsers';
import useSort from '../hooks/useSort';
import TraderTable from '../components/traderTable';
import API_BASE from '../config';

// default filter values to run when user first visits the page or clicks clear filters
const DEFAULT_INPUTS = {
  minWinrate: '',
  maxDrawdown: '',
  minBalance: '',
  maxBalance: '',
  pageSize: '100',
  botFilter: 'default',
  activityFilter: 'all',
  positionsFilter: 'all',
};

// converts the raw string inputs into actual numbers for the api call
function toApplied(f) {
  return {
    minWinrate: f.minWinrate ? parseFloat(f.minWinrate) : undefined,
    maxDrawdown: f.maxDrawdown ? parseFloat(f.maxDrawdown) : undefined,
    minBalance: f.minBalance ? parseFloat(f.minBalance) : undefined,
    maxBalance: f.maxBalance ? parseFloat(f.maxBalance) : undefined,
    botFilter: f.botFilter,
    positionsFilter: f.positionsFilter,
    activityFilter: f.activityFilter,
    search: f.search ?? '',
  }
}

const FILTER_FIELDS = [
  { key: 'minWinrate', label: 'Min Winrate %', type: 'number', placeholder: 'e.g. 60', min: 0, max: 100 },
  { key: 'maxDrawdown', label: 'Max Drawdown %', type: 'number', placeholder: 'e.g. 20', helper: 'Lower is better' },
  { key: 'minBalance', label: 'Min Balance $', type: 'number', placeholder: 'e.g. 1000' },
  { key: 'maxBalance', label: 'Max Balance $', type: 'number', placeholder: 'e.g. 50000' },
];

const SELECT_FIELDS = [
  {
    key: 'botFilter',
    label: 'Bot Filter',
    helper: 'Filter by bot detection',
    options: [['default', 'All traders'], ['no', 'Humans only'], ['yes', 'Bots only']],
  },
  {
    key: 'positionsFilter',
    label: 'Open Positions',
    options: [['all', 'All traders'], ['yes', 'In positions'], ['no', 'No positions']],
  },
  {
    key: 'activityFilter',
    label: 'Activity',
    helper: 'Trading volume > 0',
    options: [['all', 'All traders'], ['active', 'Active only'], ['inactive', 'Inactive only']],
  },
  {
    key: 'pageSize',
    label: 'Traders Per Page',
    helper: 'How many to load at once',
    options: [['25', '25'], ['50', '50'], ['100', '100'], ['150', '150'], ['200', '200']],
  },
];

export default function ProfitableTradersPage() {
  const navigate = useNavigate();
  const userId = useUserId();

  const [inputs, setInputs] = useState(DEFAULT_INPUTS);
  const [searchQuery, setSearchQuery] = useState('');
  const [appliedFilters, setAppliedFilters] = useState(toApplied(DEFAULT_INPUTS));
  const [pageSize, setPageSize] = useState(100);

  const { sortBy, setSortBy, sortDirection, setSortDirection, handleSort } = useSort('pnl', 'desc');

  // generic change handler for filter inputs
  const set = (key) => (e) => {
    setInputs(prev => ({ ...prev, [key]: e.target.value }));
  }

  // restore filters from session so user doesnt lose their filters when going back
  useEffect(() => {
    const saved = sessionStorage.getItem('traderFilters');
    if (!saved) return;

    const f = JSON.parse(saved);

    setInputs({
      minWinrate: f.minWinrate ?? '',
      maxDrawdown: f.maxDrawdown ?? '',
      minBalance: f.minBalance ?? '',
      maxBalance: f.maxBalance ?? '',
      pageSize: f.pageSize ?? '100',
      botFilter: f.botFilter ?? 'default',
      activityFilter: f.activityFilter ?? 'all',
      positionsFilter: f.positionsFilter ?? 'all',
    });

    setSortBy(f.sortBy ?? 'pnl');
    setSortDirection(f.sortDirection ?? 'desc');
    setSearchQuery(f.searchQuery ?? '');
    setAppliedFilters(toApplied({ ...f, search: f.searchQuery ?? '' }));
    setPageSize(parseInt(f.pageSize) || 100);
  }, [setSortBy, setSortDirection]);

  // debounce the search so it doesnt spam the api on every keystroke
  useEffect(() => {
    const t = setTimeout(() => {
      setAppliedFilters(prev => ({ ...prev, search: searchQuery }));
    }, 400);
    return () => clearTimeout(t);
  }, [searchQuery]);

  const { traders, loading, initialLoading, error, pagination, loadMore, hasMore } =
    useProfitableTraders(appliedFilters, pageSize, sortBy, sortDirection);

  function handleApplyFilters() {
    const applied = toApplied({ ...inputs, search: searchQuery });
    setAppliedFilters(applied);

    let size = parseInt(inputs.pageSize) || 100;
    if (size < 10) size = 10;
    if (size > 200) size = 200;
    setPageSize(size);
  }

  function handleClearFilters() {
    setInputs(DEFAULT_INPUTS);
    setSearchQuery('');
    setAppliedFilters(toApplied(DEFAULT_INPUTS));
    setPageSize(100);
  }

  // check if user changed filters but hasnt clicked apply yet
  const hasUnappliedChanges = useMemo(() => {
    const current = toApplied({ ...inputs, search: searchQuery });
    const filtersChanged = JSON.stringify(current) !== JSON.stringify(appliedFilters);
    const sizeChanged = (parseInt(inputs.pageSize) || 100) !== pageSize;
    return filtersChanged || sizeChanged;
  }, [inputs, searchQuery, appliedFilters, pageSize]);

  function handleWalletClick(wallet) {
    // save current filters so we can restore them when user comes back
    sessionStorage.setItem('traderFilters', JSON.stringify({
      ...inputs,
      sortBy,
      sortDirection,
      searchQuery,
    }));
    navigate(`/trader/${wallet}`);
  }

  function addToWatchlist(wallet) {
    if (!userId) return;

    fetch(`${API_BASE}/api/watchlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, wallet_address: wallet }),
    }).then(res => {
      if (res.status === 409) {
        alert('Already in watchlist');
      } else {
        alert('Added to watchlist!');
      }
    });
  }

  const stats = useMemo(() => {
    const profitable = traders.filter(t => t.isProfitable).length;

    let totalGain = 0;
    for (let i = 0; i < traders.length; i++) {
      totalGain += traders[i].gainDollar;
    }

    const avgGain = traders.length > 0 ? totalGain / traders.length : 0;

    let totalWinrate = 0;
    traders.forEach(t => { totalWinrate += t.winrate || 0 });
    const avgWinrate = traders.length > 0 ? totalWinrate / traders.length : 0;

    return {
      loaded: traders.length,
      total: pagination.total_count,
      displayed: traders.length,
      profitable,
      avgGain,
      avgWinrate,
    };
  }, [traders, pagination]);

  if (initialLoading) {
    return (
      <div className={styles.discordContainer}>
        <div className={styles.loadingState}>
          <div className={styles.spinner} />
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

          {FILTER_FIELDS.map(({ key, label, placeholder, helper, ...rest }) => (
            <label key={key} className={styles.filterLabel}>
              <span className={styles.labelText}>{label}</span>
              <input
                type="number"
                placeholder={placeholder}
                value={inputs[key]}
                onChange={set(key)}
                className={styles.discordInput}
                onKeyDown={(e) => e.key === 'Enter' && handleApplyFilters()}
                {...rest}
              />
              {helper && <span className={styles.helperText}>{helper}</span>}
            </label>
          ))}

          {SELECT_FIELDS.map(({ key, label, helper, options }) => (
            <label key={key} className={styles.filterLabel}>
              <span className={styles.labelText}>{label}</span>
              <select
                value={inputs[key]}
                onChange={set(key)}
                className={styles.discordSelect}
              >
                {options.map(([val, text]) => (
                  <option key={val} value={val}>{text}</option>
                ))}
              </select>
              {helper && <span className={styles.helperText}>{helper}</span>}
            </label>
          ))}

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
          {[
            ['Loaded', stats.loaded.toLocaleString(), styles.statValue],
            ['Profitable', stats.profitable.toLocaleString(), styles.statValueGreen],
            ['Avg Gain', `$${stats.avgGain.toLocaleString('en-US', { maximumFractionDigits: 0 })}`, styles.statValue],
            ['Avg WR', `${stats.avgWinrate.toFixed(1)}%`, styles.statValue],
          ].map(([label, value, cls]) => (
            <div key={label} className={styles.statItem}>
              <span className={styles.statLabel}>{label}</span>
              <span className={cls}>{value}</span>
            </div>
          ))}
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
                  <button
                    onClick={loadMore}
                    disabled={loading}
                    className={styles.loadMoreBtn}
                  >
                    {loading
                      ? <><div className={styles.smallSpinner} />Loading...</>
                      : `Load More (${(pagination.total_count - stats.loaded).toLocaleString()} remaining)`
                    }
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