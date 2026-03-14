import json
import os
from pathlib import Path

# Configuration
INPUT_FILE = Path('../../../data/leaderboard_accountvalue.json')  # JSON file with leaderboardRows
OUTPUT_FILE = Path('../../../data/filtered_eth_addresses.txt')
THRESHOLD = 1000.0  # accountValue threshold


def extractEthAddresses(inputPath: Path, outputPath: Path, threshold: float):
    """
    Read a JSON file containing leaderboard rows, filter entries with accountValue > threshold,
    and extract ethAddress values.
    """
    if not inputPath.exists():
        print(f"Input file not found: {inputPath}")
        return

    # Load JSON
    with open(inputPath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Determine if structure is list or dict with 'leaderboardRows'
    rows = data
    if isinstance(data, dict) and 'leaderboardRows' in data:
        rows = data['leaderboardRows']

    # Filter and extract
    addresses = []
    for entry in rows:
        try:
            value = float(entry.get('accountValue', 0))
        except (TypeError, ValueError):
            continue
        if value > threshold:
            addr = entry.get('ethAddress')
            if addr:
                addresses.append(addr)

    # Deduplicate
    uniqueAddresses = sorted(set(addresses))

    # Output results
    print(f"Found {len(uniqueAddresses)} addresses with accountValue > {threshold}:")
    for addr in uniqueAddresses:
        print(addr)

    # Write to file
    with open(outputPath, 'w', encoding='utf-8') as f:
        for addr in uniqueAddresses:
            f.write(addr + '\n')
    print(f"Addresses written to {outputPath}")


if __name__ == '__main__':
    extractEthAddresses(INPUT_FILE, OUTPUT_FILE, THRESHOLD)
