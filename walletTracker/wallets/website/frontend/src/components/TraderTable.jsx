import SortIndicator from './SortIndicator';
import { formatBalance } from '../utils/formatters';

/**
 * Shared trader table used by both the profitability scanner page
 * and the watchlist page. Before this component existed, both pages
 * had ~80 lines of almost identical JSX for the header + row mapping.
 *
 * Each page still owns its own data fetching, filtering, and layout —
 * this only handles the actual table rendering so we don't maintain
 * the same markup in two places.
 *
 * Props:
 *   traders        – array of trader objects (already sorted/filtered by the parent)
 *   sortBy         – current sort column key
 *   sortDirection  – 'asc' or 'desc'
 *   handleSort     – callback from useSort hook
 *   onWalletClick  – what happens when you click a wallet address
 *   actionLabel    – text for the last column header ('Watch' or 'Remove')
 *   onAction       – callback for the star/remove button, receives wallet string
 *   actionIcon     – what to show in the action button (defaults to ★)
 *   actionColor    – color of the icon
 *   styles         – CSS module object (passed from the page so we reuse their styles)
 *   headerClassName – optional override for the header row class
 *   rowClassName    – optional override for each row class
 *   footer         – optional JSX to render after the rows (load more, end message, etc.)
 */
export default function TraderTable({
  traders,
  sortBy,
  sortDirection,
  handleSort,
  onWalletClick,
  actionLabel = 'Watch',
  onAction,
  actionIcon = '★',
  actionColor = '#5865f2',
  styles,
  headerClassName,
  rowClassName,
  footer,
}) {
  return (
    <div className={styles.tableContainer}>
      {/* header row */}
      <div className={headerClassName || styles.tableHeader}>
        <div className={styles.colWallet}>Wallet</div>
        <div className={`${styles.colBalance} ${styles.sortable}`} onClick={() => handleSort('balance')}>
          Balance <SortIndicator sortBy={sortBy} column="balance" sortDirection={sortDirection} className={styles.sortIndicator} />
        </div>
        <div className={`${styles.colPnl} ${styles.sortable}`} onClick={() => handleSort('pnl')}>
          All-Time PnL <SortIndicator sortBy={sortBy} column="pnl" sortDirection={sortDirection} className={styles.sortIndicator} />
        </div>
        <div className={`${styles.colOpenTrades} ${styles.sortable}`} onClick={() => handleSort('openTrades')}>
          Open Trades <SortIndicator sortBy={sortBy} column="openTrades" sortDirection={sortDirection} className={styles.sortIndicator} />
        </div>
        <div className={`${styles.colWinrate} ${styles.sortable}`} onClick={() => handleSort('winrate')}>
          Winrate <SortIndicator sortBy={sortBy} column="winrate" sortDirection={sortDirection} className={styles.sortIndicator} />
        </div>
        <div className={`${styles.colDrawdown} ${styles.sortable}`} onClick={() => handleSort('drawdown')}>
          Max DD <SortIndicator sortBy={sortBy} column="drawdown" sortDirection={sortDirection} className={styles.sortIndicator} />
        </div>
        <div className={styles.colWatch}>{actionLabel}</div>
      </div>

      {/* rows */}
      <div className={styles.tableBody}>
        {traders.length > 0 ? (
          <>
            {traders.map((trader, index) => {
              const profitColor = trader.isProfitable ? '#3ba55d' : '#ed4245';
              return (
                <div key={`${trader.wallet}-${index}`} className={rowClassName || styles.tableRow}>
                  <div className={styles.colWallet}>
                    <div className={styles.walletCell}>
                      <div className={styles.statusDot} style={{ background: profitColor }} />
                      <span
                        className={styles.walletText}
                        title={trader.wallet}
                        onClick={() => onWalletClick(trader.wallet)}
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
                        ({trader.gainPercent > 0 ? '+' : ''}{trader.gainPercent?.toFixed(1)}%)
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
                      onClick={() => onAction(trader.wallet)}
                      title={actionLabel}
                      style={{ color: actionColor }}
                    >
                      {actionIcon}
                    </span>
                  </div>
                </div>
              );
            })}

            {/* page-specific footer (load more button, end message, etc.) */}
            {footer}
          </>
        ) : (
          <div className={styles.emptyState}>
            <p>No traders match your filters</p>
          </div>
        )}
      </div>
    </div>
  );
}

