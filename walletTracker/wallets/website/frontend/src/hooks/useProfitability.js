import { useState, useEffect, useCallback, useRef } from 'react';

const API_BASE_URL = 'http://localhost:8000/api';

export const useProfitableTraders = (filters = {}, pageSize = 100, sortBy = 'pnl', sortDirection = 'desc') => {
  const [traders, setTraders]               = useState([]);
  const [loading, setLoading]               = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError]                   = useState(null);
  const [pagination, setPagination]         = useState({
    total_count: 0,
    page:        1,
    page_size:   pageSize,
  });

  const abortControllerRef = useRef(null);

  const fetchTraders = useCallback(async (page = 1, append = false) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams();
      params.append('page',           page);
      params.append('page_size',      pageSize);
      params.append('sort_by',        sortBy);
      params.append('sort_direction', sortDirection);

      if (filters.minWinrate  !== undefined) params.append('min_winrate',  filters.minWinrate);
      if (filters.maxDrawdown !== undefined) params.append('max_drawdown', filters.maxDrawdown);
      if (filters.minBalance  !== undefined) params.append('min_balance',  filters.minBalance);
      if (filters.maxBalance  !== undefined) params.append('max_balance',  filters.maxBalance);
      if (filters.activeOnly)                params.append('active_only',  'true');

      if (filters.botFilter === 'yes') {
        params.append('is_bot', 'true');
      } else if (filters.botFilter === 'no') {
        params.append('is_bot', 'false');
      }

      const response = await fetch(`${API_BASE_URL}/users/profitable?${params}`, {
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

      const data = await response.json();

      if (append) {
        setTraders(prev => [...prev, ...data.data]);
      } else {
        setTraders(data.data);
      }

      setPagination(data.pagination);
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message);
        console.error('Error fetching traders:', err);
      }
    } finally {
      setLoading(false);
      setInitialLoading(false);
    }
  }, [filters, pageSize, sortBy, sortDirection]);

  useEffect(() => {
    fetchTraders(1, false);
  }, [fetchTraders]);

  const loadMore = useCallback(() => {
    if (pagination.has_more && !loading) {
      fetchTraders(pagination.page + 1, true);
    }
  }, [fetchTraders, pagination, loading]);

  return {
    traders,
    loading,
    initialLoading,
    error,
    pagination,
    loadMore,
    hasMore: pagination.has_more || false,
  };
};
