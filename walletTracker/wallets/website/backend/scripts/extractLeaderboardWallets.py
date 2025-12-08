import json
import os
from pathlib import Path

# Configuration
INPUT_FILE = Path('../../../data/leaderboard_accountvalue.json')  # JSON file with leaderboardRows
OUTPUT_FILE = Path('../../../data/filtered_eth_addresses.txt')
THRESHOLD = 1000.0  # accountValue threshold


def extract_eth_addresses(input_path: Path, output_path: Path, threshold: float):
    """
    Read a JSON file containing leaderboard rows, filter entries with accountValue > threshold,
    and extract ethAddress values.
    """
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return

    # Load JSON
    with open(input_path, 'r', encoding='utf-8') as f:
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
    unique_addresses = sorted(set(addresses))

    # Output results
    print(f"Found {len(unique_addresses)} addresses with accountValue > {threshold}:")
    for addr in unique_addresses:
        print(addr)

    # Write to file
    with open(output_path, 'w', encoding='utf-8') as f:
        for addr in unique_addresses:
            f.write(addr + '\n')
    print(f"Addresses written to {output_path}")


if __name__ == '__main__':
    extract_eth_addresses(INPUT_FILE, OUTPUT_FILE, THRESHOLD)
