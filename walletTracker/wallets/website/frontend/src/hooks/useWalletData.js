import { useState, useEffect, useCallback } from 'react';
import API_BASE from '../config';

// fetches both live + cached data for a single trader and merges them.
// live data overwrites the cached fields so positions and balances are current
export function useTraderData(wallet) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [dataSource, setDataSource] = useState('cached');

    const fetchData = useCallback(async (signal) => {
        if (!wallet) return;
        setLoading(true);
        setError(null);

        try {
            // fire both requests at once so we're not waiting sequentially
            const [liveRes, dbRes] = await Promise.all([
                fetch(`${API_BASE}/api/users/trader/${wallet}/live`, { signal }),
                fetch(`${API_BASE}/api/users/trader/${wallet}`, { signal })
            ]);

            const liveData = liveRes.ok ? await liveRes.json() : null;
            const dbData = dbRes.ok ? await dbRes.json() : null;

            if (!dbData || dbData.error) {
                setError('Trader not found');
                return;
            }

            // merge live data on top of cached data. if the live call failed
            // we just show the cached version with a "cached" badge
            const merged = {
                ...dbData,
                ...(liveData && !liveData.error ? {
                    account_value: liveData.account_value,
                    withdrawable_balance: liveData.withdrawable_balance,
                    total_pnl: liveData.total_pnl,
                    realized_pnl: liveData.realized_pnl,
                    unrealized_pnl: liveData.unrealized_pnl,
                    profit_percentage: liveData.profit_percentage,
                    open_positions: liveData.open_positions,
                    open_positions_count: liveData.open_positions_count,
                    data_source: 'live',
                } : { data_source: 'cached' })
            };

            setData(merged);
            setDataSource(merged.data_source);
        } catch (err) {
            if (err.name !== 'AbortError') setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [wallet]);

    useEffect(() => {
        const controller = new AbortController();
        fetchData(controller.signal);
        return () => controller.abort();
    }, [fetchData]);

    return { data, loading, error, dataSource };
}
