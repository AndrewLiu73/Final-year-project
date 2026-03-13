/**
 * Tiny arrow indicator for sortable table headers.
 * Extracted into its own component because profitability, watchlist,
 * and open positions all had their own inline version doing the same thing.
 *
 * arrowStyle prop lets open positions use triangles (▲▼) while the
 * trader tables stick with plain arrows (↑↓) — keeps the original look.
 */
export default function SortIndicator({ sortBy, column, sortDirection, className, arrowStyle = 'arrow' }) {
  if (sortBy !== column) return null;

  const arrows = arrowStyle === 'triangle'
    ? { asc: '▲', desc: '▼' }
    : { asc: '↑', desc: '↓' };

  return (
    <span className={className}>
      {sortDirection === 'asc' ? arrows.asc : arrows.desc}
    </span>
  );
}

