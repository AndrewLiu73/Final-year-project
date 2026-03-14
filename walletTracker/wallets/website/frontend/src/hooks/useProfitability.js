import { useState, useEffect, useCallback, useRef } from 'react';
import API_BASE from '../config';

const API_URL = `${API_BASE}/api`;

export const useProfitableTraders = (filters = {}, pageSize = 100, sortBy = 'pnl', sortDirection = 'desc') => {
  const [traders, setTraders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pagination, setPagination] = useState({
    total_count: 0,
    page: 1,
    page_size: pageSize,
  });

  const abortRef = useRef(null);

  const fetchTraders = useCallback(async (page = 1, append = false) => {
    // cancel any in-flight request so we don't get stale data coming in late
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();

    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams();
      params.append('page', page);
      params.append('pageSize', pageSize);
      params.append('sortBy', sortBy);
      params.append('sortDirection', sortDirection);

      if (filters.minWinrate !== undefined) params.append('minWinrate', filters.minWinrate);
      if (filters.maxDrawdown !== undefined) params.append('maxDrawdown', filters.maxDrawdown);
      if (filters.minBalance !== undefined) params.append('minBalance', filters.minBalance);
      if (filters.maxBalance !== undefined) params.append('maxBalance', filters.maxBalance);
      if (filters.activeOnly) params.append('activeOnly', 'true');

      if (filters.botFilter === 'yes') {
        params.append('isBot', 'true');
      } else if (filters.botFilter === 'no') {
        params.append('isBot', 'false');
      }

      const response = await fetch(`${API_URL}/users/profitable?${params}`, {
        signal: abortRef.current.signal,
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
