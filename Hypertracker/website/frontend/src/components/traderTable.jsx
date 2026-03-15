import SortIndicator from './sortIndicator';
import { formatBalance } from '../utils/formatters';

const COLUMNS = [
  { key: 'balance',    label: 'Balance',      col: 'colBalance'    },
  { key: 'pnl',        label: 'All-Time PnL', col: 'colPnl'        },
  { key: 'openTrades', label: 'Open Trades',  col: 'colOpenTrades' },
  { key: 'winrate',    label: 'Winrate',      col: 'colWinrate'    },
  { key: 'drawdown',   label: 'Max DD',       col: 'colDrawdown'   },
];

export default function TraderTable({
  traders, sortBy, sortDirection, handleSort, onWalletClick,
  actionLabel = 'Watch', onAction, actionIcon = '★', actionColor = '#5865f2',
  styles, headerClassName, rowClassName, footer,
}) {
  return (
    <div className={styles.tableContainer}>
      <div className={headerClassName || styles.tableHeader}>
        <div className={styles.colWallet}>Wallet</div>
        {COLUMNS.map(({ key, label, col }) => (
          <div key={key} className={`${styles[col]} ${styles.sortable}`} onClick={() => handleSort(key)}>
            {label} <SortIndicator sortBy={sortBy} column={key} sortDirection={sortDirection} className={styles.sortIndicator} />
          </div>
        ))}
        <div className={styles.colWatch}>{actionLabel}</div>
      </div>

      <div className={styles.tableBody}>
        {traders.length > 0 ? (
          <>
            {traders.map((t, i) => {
              const c = t.isProfitable ? '#3ba55d' : '#ed4245';
              return (
                <div key={`${t.wallet}-${i}`} className={rowClassName || styles.tableRow}>
                  <div className={styles.colWallet}>
                    <div className={styles.walletCell}>
                      <div className={styles.statusDot} style={{ background: c }} />
                      <span className={styles.walletText} title={t.wallet} onClick={() => onWalletClick(t.wallet)}>
                        {t.wallet.slice(0, 6)}...{t.wallet.slice(-4)}
                      </span>
                    </div>
                  </div>

                  <div className={styles.colBalance}>
                    <span className={styles.valueText}>{formatBalance(t.currentBalance)}</span>
                  </div>

                  <div className={styles.colPnl}>
                    <div className={styles.pnlCell}>
                      <span className={styles.pnlValue} style={{ color: c }}>
                        {t.gainDollar > 0 ? '+' : ''}{formatBalance(t.gainDollar)}
                      </span>
                      <span className={styles.pnlPercent} style={{ color: c }}>
                        ({t.gainPercent > 0 ? '+' : ''}{t.gainPercent?.toFixed(1)}%)
                      </span>
                    </div>
                  </div>

                  <div className={styles.colOpenTrades}>
                    <span className={styles.valueText}>{t.openPositionsCount || 0}</span>
                  </div>

                  <div className={styles.colWinrate}>
                    <span className={styles.valueText}>{t.winrate ? `${t.winrate.toFixed(1)}%` : '-'}</span>
                  </div>

                  <div className={styles.colDrawdown}>
                    <span className={styles.valueText}>{t.maxDrawdown ? `${t.maxDrawdown.toFixed(1)}%` : '-'}</span>
                  </div>

                  <div className={styles.colWatch}>
                    <span className={styles.watchStar} onClick={() => onAction(t.wallet)} title={actionLabel} style={{ color: actionColor }}>
                      {actionIcon}
                    </span>
                  </div>
                </div>
              );
            })}
            {footer}
          </>
        ) : (
          <div className={styles.emptyState}><p>No traders match your filters</p></div>
        )}
      </div>
    </div>
  );
}
