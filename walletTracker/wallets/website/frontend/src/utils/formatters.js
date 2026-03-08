
export function formatBalance(val) {
    if (val === null || val === undefined) return '$0';
    const abs  = Math.abs(val);
    const sign = val < 0 ? '-' : '';
    if (abs >= 1_000_000_000_000) return `${sign}$${(abs / 1_000_000_000_000).toFixed(2)}T`;
    if (abs >= 1_000_000_000)     return `${sign}$${(abs / 1_000_000_000).toFixed(2)}B`;
    if (abs >= 1_000_000)         return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000)             return `${sign}$${(abs / 1_000).toFixed(1)}K`;
    return `${sign}$${abs.toFixed(0)}`;
}
