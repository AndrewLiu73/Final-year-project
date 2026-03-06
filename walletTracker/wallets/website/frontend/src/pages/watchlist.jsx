import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import useUserId from '../hooks/useUsers';
import { formatBalance } from '../utils/formatters';
import styles from './profitability.module.css';
import watchStyles from './watchlist.module.css';

export default function Watchlist() {
    const navigate = useNavigate();
    const userId   = useUserId();

    const [traders,     setTraders]     = useState([]);
    const [loading,     setLoading]     = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [sortBy,      setSortBy]      = useState('pnl');
    const [sortDirection, setSortDirection] = useState('desc');

    // add these two here, inside the component
    const [telegramId, setTelegramId] = useState(localStorage.getItem("telegram_id") || "");
    const [tgSaved,    setTgSaved]    = useState(!!localStorage.getItem("telegram_id"));

    useEffect(() => {
        if (!userId) return;
        async function loadWatchlist() {
            setLoading(true);
            try {
                const res            = await fetch(`http://localhost:8000/api/watchlist/${userId}`);
                const watchlistItems = await res.json();
                const traderPromises = watchlistItems.map(item =>
                    fetch(`http://localhost:8000/api/users/trader/${item.wallet_address}`)
                        .then(r => r.json())
                        .then(data => ({
                            wallet:             data.wallet_address,
                            currentBalance:     data.account_value,
                            gainDollar:         data.total_pnl,
                            gainPercent:        data.profit_percentage,
                            winrate:            data.win_rate_percentage,
                            maxDrawdown:        data.max_drawdown_percentage,
                            openPositionsCount: data.open_positions_count,
                            isProfitable:       data.total_pnl > 0,
                            openPositions:      data.open_positions || [],
                        }))
                );
                const results = await Promise.all(traderPromises);
                setTraders(results);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        }
        loadWatchlist();
    }, [userId]);

    // add this function here, inside the component
    const saveTelegramId = () => {
        if (!telegramId) return;
        localStorage.setItem("telegram_id", telegramId);
        fetch("http://localhost:8000/api/users/telegram", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ user_id: userId, telegram_id: telegramId })
        }).then(() => setTgSaved(true));
    };

    function removeFromWatchlist(wallet) {
        fetch(`http://localhost:8000/api/watchlist/${userId}/${wallet}`, { method: 'DELETE' })
            .then(() => setTraders(prev => prev.filter(t => t.wallet !== wallet)));
    }

    const handleSort = (column) => {
        if (sortBy === column) {
            setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(column);
            setSortDirection('desc');
        }
    };

    const SortIndicator = ({ column }) => {
        if (sortBy !== column) return null;
        return <span className={styles.sortIndicator}>{sortDirection === 'asc' ? '↑' : '↓'}</span>;
    };

    const sortedTraders = useMemo(() => {
        const filtered = searchQuery
            ? traders.filter(t => t.wallet.toLowerCase().includes(searchQuery.toLowerCase()))
            : traders;
        return [...filtered].sort((a, b) => {
            const fieldMap = { pnl: 'gainDollar', balance: 'currentBalance', winrate: 'winrate', drawdown: 'maxDrawdown', openTrades: 'openPositionsCount' };
            const field = fieldMap[sortBy] || 'gainDollar';
            return sortDirection === 'desc' ? (b[field] || 0) - (a[field] || 0) : (a[field] || 0) - (b[field] || 0);
        });
    }, [traders, searchQuery, sortBy, sortDirection]);

    const groupBias = useMemo(() => {
        const biases = traders.map(trader => {
            let longVal = 0, shortVal = 0;
            trader.openPositions.forEach(pos => {
                const notional = pos.size * pos.entry_price;
                if (pos.direction === 'LONG') longVal += notional;
                else shortVal += notional;
            });
            const total = longVal + shortVal;
            if (total === 0) return null;
            return ((longVal - shortVal) / total) * 100;
        }).filter(b => b !== null);

        if (biases.length === 0) return null;
        const avg      = biases.reduce((sum, b) => sum + b, 0) / biases.length;
        const longPct  = (avg + 100) / 2;
        const shortPct = 100 - longPct;
        return { avg, longPct, shortPct, voterCount: biases.length };
    }, [traders]);

    if (loading) {
        return (
            <div className={styles.discordContainer}>
                <div className={styles.loadingState}>
                    <div className={styles.spinner}></div>
                    <p>Loading watchlist...</p>
                </div>
            </div>
        );
    }

    return (
        <div className={styles.discordContainer}>
            <div className={styles.mainContent}>

                <div className={styles.channelHeader}>
                    <div className={styles.channelInfo}>
                        <span className={styles.channelIcon}>#</span>
                        <h1 className={styles.channelName}>my-watchlist</h1>
                        <span className={styles.channelCount}>{sortedTraders.length} traders</span>
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

                {/* Bias bar */}
                {groupBias && (
                    <div style={{ padding: '12px 20px', background: '#2f3136', borderBottom: '1px solid #202225' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '11px', color: '#96989d', textTransform: 'uppercase', fontWeight: 700, letterSpacing: '0.5px' }}>
                            <span>Watchlist Bias ({groupBias.voterCount} active traders)</span>
                            <span style={{ color: groupBias.avg >= 0 ? '#3ba55d' : '#ed4245' }}>
                                {groupBias.avg >= 0 ? 'NET LONG' : 'NET SHORT'} {Math.abs(groupBias.avg).toFixed(1)}%
                            </span>
                        </div>
                        <div style={{ display: 'flex', height: '10px', borderRadius: '4px', overflow: 'hidden', background: '#202225' }}>
                            <div style={{ width: `${groupBias.longPct}%`, background: '#3ba55d', transition: 'width 0.4s ease' }} />
                            <div style={{ width: `${groupBias.shortPct}%`, background: '#ed4245', transition: 'width 0.4s ease' }} />
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontSize: '11px' }}>
                            <span style={{ color: '#3ba55d' }}>Long {groupBias.longPct.toFixed(1)}%</span>
                            <span style={{ color: '#ed4245' }}>Short {groupBias.shortPct.toFixed(1)}%</span>
                        </div>
                    </div>
                )}

                {/* Telegram alert input — sits between bias bar and table */}
                <div style={{
                    background:   '#2f3136',
                    padding:      '12px 20px',
                    borderBottom: '1px solid #202225',
                    display:      'flex',
                    alignItems:   'center',
                    gap:          '10px',
                }}>
                    <span style={{ color: '#b9bbbe', fontSize: '13px', whiteSpace: 'nowrap' }}>
                        Telegram Alerts:
                    </span>
                    <input
                        type="text"
                        placeholder="Enter your Telegram chat ID"
                        value={telegramId}
                        onChange={e => { setTelegramId(e.target.value); setTgSaved(false); }}
                        style={{
                            background:   '#202225',
                            border:       '1px solid #40444b',
                            borderRadius: '4px',
                            padding:      '6px 10px',
                            color:        'white',
                            fontSize:     '13px',
                            width:        '200px',
                        }}
                    />
                    <button
                        onClick={saveTelegramId}
                        style={{
                            background:   tgSaved ? '#3ba55d' : '#5865f2',
                            color:        'white',
                            border:       'none',
                            borderRadius: '4px',
                            padding:      '6px 14px',
                            cursor:       'pointer',
                            fontSize:     '13px',
                            fontWeight:   '600',
                        }}
                    >
                        {tgSaved ? 'Saved' : 'Save'}
                    </button>
                    <span style={{ color: '#72767d', fontSize: '11px' }}>
                        Message @HyperTrack_Alert_Bot on Telegram to get your ID, then start a chat with @your_bot_name
                    </span>
                </div>

                {/* Table */}
                <div className={styles.tableContainer}>
                    <div className={watchStyles.tableHeader}>
                        <div className={styles.colWallet}>Wallet</div>
                        <div className={`${styles.colBalance} ${styles.sortable}`} onClick={() => handleSort('balance')}>Balance <SortIndicator column="balance" /></div>
                        <div className={`${styles.colPnl} ${styles.sortable}`} onClick={() => handleSort('pnl')}>All-Time PnL <SortIndicator column="pnl" /></div>
                        <div className={`${styles.colOpenTrades} ${styles.sortable}`} onClick={() => handleSort('openTrades')}>Open Trades <SortIndicator column="openTrades" /></div>
                        <div className={`${styles.colWinrate} ${styles.sortable}`} onClick={() => handleSort('winrate')}>Winrate <SortIndicator column="winrate" /></div>
                        <div className={`${styles.colDrawdown} ${styles.sortable}`} onClick={() => handleSort('drawdown')}>Max DD <SortIndicator column="drawdown" /></div>
                        <div className={styles.colWatch}>Remove</div>
                    </div>

                    <div className={styles.tableBody}>
                        {sortedTraders.length === 0 ? (
                            <div className={styles.emptyState}>
                                <p>No traders in your watchlist yet. Hit the star on the Profitable Traders page to add some.</p>
                            </div>
                        ) : (
                            sortedTraders.map((trader, index) => {
                                const profitColor = trader.isProfitable ? '#3ba55d' : '#ed4245';
                                return (
                                    <div key={`${trader.wallet}-${index}`} className={watchStyles.tableRow}>
                                        <div className={styles.colWallet}>
                                            <div className={styles.walletCell}>
                                                <div className={styles.statusDot} style={{ background: profitColor }} />
                                                <span className={styles.walletText} title={trader.wallet} onClick={() => navigate(`/trader/${trader.wallet}`)}>
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
                                            <span className={styles.valueText}>{trader.winrate ? `${trader.winrate.toFixed(1)}%` : '-'}</span>
                                        </div>
                                        <div className={styles.colDrawdown}>
                                            <span className={styles.valueText}>{trader.maxDrawdown ? `${trader.maxDrawdown.toFixed(1)}%` : '-'}</span>
                                        </div>
                                        <div className={styles.colWatch}>
                                            <span className={styles.watchStar} onClick={() => removeFromWatchlist(trader.wallet)} title="Remove from watchlist" style={{ color: '#f0b132' }}>
                                                ★
                                            </span>
                                        </div>
                                    </div>
                                );
                            })
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
