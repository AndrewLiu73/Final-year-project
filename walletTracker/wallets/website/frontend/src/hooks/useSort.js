import { useState, useCallback } from 'react';

/**
 * Shared sorting hook so we don't copy-paste the same toggle logic
 * across profitability, watchlist, and open positions pages.
 *
 * Clicking the same column flips asc/desc.
 * Clicking a new column resets to desc (biggest first makes more sense
 * for financial data — nobody wants to see the smallest PnL on top).
 */
export default function useSort(initialColumn = 'pnl', initialDir = 'desc') {
  const [sortBy, setSortBy] = useState(initialColumn);
  const [sortDirection, setSortDirection] = useState(initialDir);

  const handleSort = useCallback((column) => {
    setSortBy(prev => {
      if (prev === column) {
        // same column — just flip direction
        setSortDirection(d => d === 'desc' ? 'asc' : 'desc');
        return prev;
      }
      // new column — default to descending
      setSortDirection('desc');
      return column;
    });
  }, []);

  return { sortBy, setSortBy, sortDirection, setSortDirection, handleSort };
}

