// src/utils/biasUtils.js

export function calculateDirectionalBias(openPositions) {
    if (!openPositions || openPositions.length === 0) {
        return { label: 'No Open Positions', color: '#96989d', longCount: 0, shortCount: 0 };
    }

    let longCount  = 0;
    let shortCount = 0;

    openPositions.forEach((pos) => {
        const dir = String(pos.direction || '').trim().toUpperCase();
        if (dir === 'LONG')  longCount++;
        if (dir === 'SHORT') shortCount++;
    });

    const total = longCount + shortCount;

    if (total === 0) {
        return { label: 'Neutral', color: '#96989d', longCount: 0, shortCount: 0 };
    }

    const longPct  = ((longCount  / total) * 100).toFixed(1);
    const shortPct = ((shortCount / total) * 100).toFixed(1);

    if (longCount > shortCount) {
        return {
            label: `Long Bias — ${longCount}L / ${shortCount}S (${longPct}% Long)`,
            color: '#3ba55d',
            longCount,
            shortCount
        };
    }

    if (shortCount > longCount) {
        return {
            label: `Short Bias — ${shortCount}S / ${longCount}L (${shortPct}% Short)`,
            color: '#ed4245',
            longCount,
            shortCount
        };
    }

    return {
        label: `Neutral — ${longCount}L / ${shortCount}S (50/50)`,
        color: '#96989d',
        longCount,
        shortCount
    };
}
