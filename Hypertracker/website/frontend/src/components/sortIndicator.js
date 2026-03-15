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

