import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import useUserId from '../hooks/useUsers';
import useSort from '../hooks/useSort';
import styles from './profitability.module.css';
import watchStyles from './watchlist.module.css';
import API_BASE from '../config';
import TraderTable from '../components/TraderTable';

export default function Watchlist() {
    const navigate = useNavigate();
    const userId = useUserId();

    const [traders, setTraders] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    // same sorting hook used across all pages now
    const { sortBy, sortDirection, handleSort } = useSort('pnl', 'desc');

    const [telegramId, setTelegramId] = useState(localStorage.getItem("telegram_id") || "");
    const [tgSaved, setTgSaved] = useState(!!localStorage.getItem("telegram_id"));

    useEffect(() => {
        if (!userId) return;
        async function loadWatchlist() {
            setLoading(true);
            try {
                const res            = await fetch(`${API_BASE}/api/watchlist/${userId}`);
                const watchlistItems = await res.json();
                const traderPromises = watchlistItems.map(item =>
                    fetch(`${API_BASE}/api/users/trader/${item.wallet_address}`)
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
        fetch(`${API_BASE}/api/users/telegram`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ userId: userId, telegramId: telegramId })
        }).then(() => setTgSaved(true));
    };

    function removeFromWatchlist(wallet) {
        fetch(`${API_BASE}/api/watchlist/${userId}/${wallet}`, { method: 'DELETE' })
            .then(() => setTraders(prev => prev.filter(t => t.wallet !== wallet)));
    }

    // handleSort now comes from useSort hook (shared with profitability + open positions)

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
                {/* Reusing the same TraderTable component as profitability page */}
                <TraderTable
                    traders={sortedTraders}
                    sortBy={sortBy}
                    sortDirection={sortDirection}
                    handleSort={handleSort}
                    onWalletClick={(wallet) => navigate(`/trader/${wallet}`)}
                    actionLabel="Remove"
                    onAction={removeFromWatchlist}
                    actionIcon="★"
                    actionColor="#f0b132"
                    styles={styles}
                    headerClassName={watchStyles.tableHeader}
                    rowClassName={watchStyles.tableRow}
                />
            </div>
        </div>
    );
}
