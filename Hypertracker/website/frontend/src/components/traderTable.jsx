import SortIndicator from './sortIndicator';
import { formatBalance } from '../utils/formatters';

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

