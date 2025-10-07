const fs = require('fs');


async function fetchLeaderboardJson() {
    const url = 'https://stats-data.hyperliquid.xyz/Mainnet/leaderboard';
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to fetch leaderboard: ${res.status}`);
    const data = await res.json();
    fs.writeFileSync('leaderboard_raw.json', JSON.stringify(data, null, 2));
    console.log('Fetched and saved leaderboard_raw.json');
    return data;
}


function writeTopAccountValueLeaderboard() {
    const raw = JSON.parse(fs.readFileSync('leaderboard_raw.json', 'utf8'));
    const rows = raw.leaderboardRows || [];

    const withAccountValue = rows
        .map(row => {
            if (!row.accountValue) return null;
            const accountValue = parseFloat(row.accountValue);
            if (isNaN(accountValue)) return null;
            return { ...row, accountValue };
        })
        .filter(Boolean);

    withAccountValue.sort((a, b) => b.accountValue - a.accountValue);

    // Remove the slice to include all sorted wallets
    fs.writeFileSync('leaderboard_accountvalue.json',
        JSON.stringify(
            withAccountValue.map(({ displayName, ethAddress, accountValue }) => ({
                displayName,
                ethAddress,
                accountValue
            })),
            null,
            2
        )
    );
    console.log('Wrote all wallets sorted by account value to leaderboard_accountvalue.json');
}

// Call this function after fetching the leaderboard
async function main() {
    await fetchLeaderboardJson();

    writeTopAccountValueLeaderboard();
}

main();
