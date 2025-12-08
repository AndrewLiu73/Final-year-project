import { useState, useEffect, useCallback } from 'react';

export function useProfitableTraders(minGain = 0, maxGain = 1000) {
  const [traders, setTraders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchTraders = useCallback(async () => {
    setLoading(true);
    try {
      // Construct the URL with query parameters for the gain percentage range
      const response = await fetch(
        `http://localhost:8000/api/users/with-balances?min_gain_percent=${minGain}&max_gain_percent=${maxGain}`
      );

      if (!response.ok) {
        throw new Error('Failed to fetch traders from the API');
      }

      const data = await response.json();
      setTraders(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [minGain, maxGain]); // This function is re-created only when minGain or maxGain changes

  // useEffect runs the fetch function whenever it's re-created
  useEffect(() => {
    fetchTraders();
  }, [fetchTraders]);

  // The hook returns the data, loading state, error state, and a refetch function
  return { traders, loading, error, refetch: fetchTraders };
}
