- Line 20: `telegramId`, `setTelegramId` → ✓ Already camelCase
- Line 21: `tgSaved`, `setTgSaved` → ✓ Already camelCase
- Line 28: `loadWatchlist` → ✓ Already camelCase
- Line 34: `watchlistItems` → ✓ Already camelCase
- Line 35: `traderPromises` → ✓ Already camelCase
- Line 52: `saveTelegramId` → ✓ Already camelCase
- Line 65: `removeFromWatchlist` → ✓ Already camelCase
- Line 74: `sortedTraders` → ✓ Already camelCase
- Line 79: `fieldMap` → ✓ Already camelCase
- Line 85: `groupBias` → ✓ Already camelCase
- Line 87: `openPositions` → ✓ Already camelCase
- Line 89: `entry_price` (from data) → Keep from backend
### walletTracker/wallets/website/frontend/src/hooks/useProfitability.js
- Line 4: `API_URL` → Keep (constant)
- Line 6: `useProfitableTraders` → ✓ Already camelCase
- Line 12: `total_count`, `page_size` → Keep from backend (JSON response)
- Line 28: `URLSearchParams` → Keep (API)
- Line 29: `page`, `page_size` → Keep (params)
- Line 31: `sort_by`, `sort_direction` → Keep (params)
- Line 34: `min_winrate`, `max_drawdown`, `min_balance`, `max_balance` → Keep (params)
- Line 38: `active_only` → Keep (param)
- Line 75: `has_more` → Keep from backend
- Line 87: `has_more` → Keep from backend
### walletTracker/wallets/website/frontend/src/components/TraderTable.jsx
- Line 28: `TraderTable` → Keep (component)
- Line 54: `openTrades` → ✓ Already camelCase
- Line 57: `winrate` → ✓ Already camelCase
- Line 60: `drawdown` → ✓ Already camelCase
- Line 71: `isProfitable` → ✓ Already camelCase
- Line 76: `statusDot` → ✓ Already camelCase
- Line 88: `currentBalance` → ✓ Already camelCase
- Line 93: `pnlValue`, `pnlPercent` → ✓ Already camelCase
- Line 94: `gainDollar` → ✓ Already camelCase
- Line 97: `gainPercent` → ✓ Already camelCase
---
## 5. SUMMARY OF CONVERSION EFFORT
### Python Files (Highest Priority)
**Files with 50+ snake_case identifiers:**
1. `fullWalletTracker.py` - 100+ instances (dataclass fields, methods, variables)
2. `main.py` - 50+ instances (API parameters, MongoDB mapping)
3. `history.py` - 80+ instances (AWS S3, MongoDB operations)
**Files with 20+ instances:**
4. `snipeBot.py` - 25 instances
5. `Hotkeys.py` - 20 instances
6. `walletTracker.py` - 20+ instances
**Files with 10-20 instances:**
7. `output.py` - 18 instances
8. `fetchOI.py` - 15 instances
9. `whaleFinder.py` - 12 instances
10. `activeTraders.py` - 8 instances
11. `removeDupUsers.py` - 10 instances
### JavaScript/React Files (Medium Priority)
**Status:** Mostly compliant with camelCase already ✓
**Minor fixes needed:**
- API parameter names in query strings (keep as-is for backend compatibility)
- localStorage keys: `hl_user_id` → `hlUserId`, `telegram_id` → `telegramId`
- Data transformation layer where snake_case from MongoDB is converted to camelCase
### MongoDB Field Names (Keep as-is)
These should remain in snake_case for consistency with database schema:
- `wallet_address`, `account_value`, `total_pnl_usdc`
- `win_rate_percentage`, `max_drawdown_percentage`
- `has_trading_activity`, `is_likely_bot`, `is_vault_depositor`
- `open_positions`, `trade_count`, `historical_pnl`
---
## 6. KEY STATISTICS
- **Total Lines of Code:** 8,141
- **Python Files:** 25
- **JavaScript/React Files:** 20
- **Configuration Files:** 1 (package.json)
- **Total Snake_case Identifiers:** 300+ in Python, 50+ in JS
- **Estimated Conversion Effort:** 20-30 hours for thorough refactoring
---
## 7. PRIORITY CONVERSION ORDER
1. **Tier 1 (Critical):** fullWalletTracker.py, main.py, history.py
2. **Tier 2 (High):** snipeBot.py, Hotkeys.py, output.py
3. **Tier 3 (Medium):** Backend scripts (fetchOI, activeTraders, whaleFinder)
4. **Tier 4 (Low):** JavaScript/React (mostly already compliant)
5. **Tier 5 (Not Needed):** MongoDB field names, API parameters
EOF
cat /tmp/COMPREHENSIVE_ANALYSIS.md
                EC=$?
                echo "___BEGIN___COMMAND_DONE_MARKER___$EC"
            }
___BEGIN___COMMAND_OUTPUT_MARKER___
# Trading Tool Repository - Comprehensive Analysis

## 1. Directory Structure

```
tradingTool/
├── .git/
├── .gitignore
├── .idea/
├── fyp-25pma008-srv.cs.nuim.ie
└── walletTracker/
    ├── __init__.py
    ├── .gitignore
    ├── scripts/                          # Standalone trading scripts
    │   ├── snipeBot.py                   # OKX automated trading bot
    │   ├── Hotkeys.py                    # Single order executor
    │   ├── output.py                     # Top traders filter
    │   ├── singleScan.py                 # Individual wallet scanner
    │   ├── fullWalletTracker.py          # Comprehensive PnL analysis
    │   ├── walletViewer.py               # Wallet history plotter
    │   ├── history.py                    # Historical data processor
    │   ├── extractLeaderboardWallets.py  # Extract high-value wallets
    │   ├── exportMongodb.py              # MongoDB backup utility
    │   ├── removeDupUsers.py             # MongoDB cleanup
    │   └── leaderboardFetch.js           # Leaderboard data fetcher
    │
    └── wallets/website/
        ├── backend/                      # FastAPI backend (25+ routes)
        │   ├── main.py                   # Main API endpoints
        │   ├── scripts/
        │   │   ├── fetchOI.py            # Open Interest monitor
        │   │   ├── activeTraders.py      # WebSocket trader tracker
        │   │   ├── whaleFinder.py        # Millionaire extractor
        │   │   ├── profitabilityScanner.py
        │   │   ├── millionaireBias.py
        │   │   ├── alert.py
        │   │   ├── OpenTrades.py
        │   │   └── ... other scripts
        │   └── tests/
        │       ├── API_test.py
        │       └── test_profitability_scanner.py
        │
        └── frontend/                    # React web app
            ├── src/
            │   ├── App.js               # Main component
            │   ├── config.js            # API config
            │   ├── components/
            │   │   ├── TraderTable.jsx
            │   │   ├── biasHistoryChart.jsx
            │   │   ├── OITabs.jsx
            │   │   ├── positionBar.js
            │   │   ├── ErrorBoundary.jsx
            │   │   └── ... more
            │   ├── pages/
            │   │   ├── profitability.jsx
            │   │   ├── watchlist.jsx
            │   │   ├── TraderDetail.jsx
            │   │   └── openPositions.jsx
            │   ├── hooks/
            │   │   ├── useUsers.js
            │   │   ├── useProfitability.js
            │   │   └── useSort.js
            │   └── utils/
            │       ├── formatters.js
            │       ├── biasUtils.js
            │       └── constants.js
            └── package.json
```

## 2. Configuration Files

### Found:
- `walletTracker/wallets/website/frontend/package.json`
  - React 19.2, React Router 7.13, Recharts 3.7, DayJS 1.11
  - Test libraries: @testing-library/react 16.3

### Not in Repository (Environment):
- `.env` files in `walletTracker/wallets/website/backend/`
  - Required: `MONGO_URI`, `TELEGRAM_BOT_TOKEN`

---

## 3. PYTHON FILES - SNAKE_CASE IDENTIFIERS

### walletTracker/scripts/snipeBot.py
**Lines with snake_case needing camelCase conversion:**
- Line 29: `set_position_mode`, `long_short_mode` → `setPositionMode`, `longShortMode`
- Line 30: `set_leverage` → `setLeverage`
- Line 38: `get_active_orders` → `getActiveOrders`
- Line 40: `get_order_list` → `getOrderList`
- Line 52: `get_open_positions` → `getOpenPositions`
- Line 56: `long_entry_price`, `short_entry_price` → `longEntryPrice`, `shortEntryPrice`
- Line 58: `long_size`, `short_size` → `longSize`, `shortSize`
- Line 63: `avg_price` → `avgPrice`
- Line 64: `pos_size` → `posSize`
- Line 82: `place_tp_sl_orders` → `placeTpSlOrders`
- Line 85: `tp_price` → `tpPrice`
- Line 86: `sl_price` → `slPrice`
- Line 87: `close_side` → `closeSide`
- Line 96: `tp_order` → `tpOrder`
- Line 112: `sl_order` → `slOrder`
- Line 129: `amend_or_place_order` → `amendOrPlaceOrder`
- Line 155: `amend_response` → `amendResponse`
- Line 171: `mark_price` → `markPrice`
- Line 172: `long_price` → `longPrice`
- Line 173: `short_price` → `shortPrice`
- Line 179: `last_long_order_id`, `last_short_order_id` → `lastLongOrderId`, `lastShortOrderId`
- Line 183: `long_entry`, `short_entry` → `longEntry`, `shortEntry`

### walletTracker/scripts/Hotkeys.py
**Lines with snake_case needing camelCase:**
- Line 28: `set_position_mode`, `long_short_mode`
- Line 31: `set_leverage`
- Line 34: `wait_for_order_fill`, `order_id` → `waitForOrderFill`, `orderId`
- Line 38: `get_order` → `getOrder`
- Line 50: `place_tp_sl`, `order_side`, `entry_price`, `order_size`
- Line 53: `tp_price` → `tpPrice`
- Line 54: `sl_price` → `slPrice`
- Line 55: `tp_side`, `sl_side` → `tpSide`, `slSide`
- Line 67: `tp_order`, `place_order` → `tpOrder`, `placeOrder`
- Line 72: `post_only` → `postOnly`
- Line 83: `sl_order` → `slOrder`
- Line 101: `mark_price_data`, `get_mark_price` → `markPriceData`, `getMarkPrice`
- Line 104: `mark_price` → `markPrice`
- Line 113: `buy_price` → `buyPrice`
- Line 115: `order_result` → `orderResult`
- Line 134: `sell_price` → `sellPrice`

### walletTracker/scripts/output.py
**Lines with snake_case:**
- Line 13: `get_float_input` → `getFloatInput`
- Line 25: `get_top_traders` → `getTopTraders`
- Line 27: `mongo_uri` → `mongoUri`
- Line 30: `metrics_collection` → `metricsCollection`
- Line 39: `balance_min`, `balance_max` → `balanceMin`, `balanceMax`
- Line 43: `winrate_min` → `winrateMin`
- Line 46: `pnl_min` → `pnlMin`
- Line 49: `drawdown_max` → `drawdownMax`
- Line 52: `filter_profitable` → `filterProfitable`
- Line 55: `has_trading_activity` → `hasTransactionActivity` (but keep DB field as-is)
- Line 58: `account_value` → Keep as-is for MongoDB
- Line 65: `win_rate_percentage` → Keep as-is for MongoDB
- Line 68: `total_pnl_usdc` → Keep as-is for MongoDB
- Line 71: `max_drawdown_percentage` → Keep as-is for MongoDB
- Line 100: `wallet_address` → `walletAddress`
- Line 111: `total_pnl`, `avg_pnl` → `totalPnl`, `avgPnl`
- Line 113: `avg_balance` → `avgBalance`
- Line 114: `avg_winrate`, `avg_drawdown` → `avgWinrate`, `avgDrawdown`
- Line 116: `profitable_count` → `profitableCount`

### walletTracker/scripts/singleScan.py
**Lines with snake_case:**
- Line 23: `scan_wallet` → `scanWallet`
- Line 33: `calculate_profitability` → `calculateProfitability`
- Line 88: `wallet_address` → `walletAddress`
- Line 94: `upserted_id` → `upsertedId`

### walletTracker/scripts/extractLeaderboardWallets.py
**Lines with snake_case:**
- Line 6: `leaderboard_accountvalue` (filename) → `leaderboardAccountValue`
- Line 7: `filtered_eth_addresses` → `filteredEthAddresses`
- Line 11: `extract_eth_addresses` → `extractEthAddresses`
- Line 11: `input_path`, `output_path` → `inputPath`, `outputPath`
- Line 42: `unique_addresses` → `uniqueAddresses`

### walletTracker/scripts/exportMongodb.py
**Lines with snake_case:**
- Line 8: `mongo_backup` (directory) → `mongoBackup`
- Line 10: `list_collection_names` → Keep as-is (MongoDB API)

### walletTracker/scripts/removeDupUsers.py
**Lines with snake_case:**
- Line 13: `clean_users_collection` → `cleanUsersCollection`
- Line 15: `mongo_uri` → `mongoUri`
- Line 40-52: MongoDB fields → Keep as-is (database schema)
- Line 78: `total_to_delete` → `totalToDelete`
- Line 99: `docs_to_delete` → `docsToDelete`

### walletTracker/scripts/fullWalletTracker.py (MAJOR - 100+ instances)
**Dataclass fields (lines 28-61):**
- Line 29: `PnLConfig` class → Keep name but convert parameters:
  - `trader_address` → `traderAddress`
  - `start_date` → `startDate`
  - `end_date` → `endDate`
  - `initial_window` → `initialWindow`
  - `max_trades` → `maxTrades`
  - `max_window` → `maxWindow`
  - `min_window` → `minWindow`
  - `max_retries` → `maxRetries`
  - `save_data` → `saveData`
  - `output_dir` → `outputDir`

- Line 44: `TradeMetrics` class fields → All snake_case to camelCase:
  - `total_trades` → `totalTrades`
  - `winning_trades` → `winningTrades`
  - `losing_trades` → `losingTrades`
  - `win_rate` → `winRate`
  - `total_pnl` → `totalPnl`
  - `max_drawdown` → `maxDrawdown`
  - `max_profit` → `maxProfit`
  - `avg_win` → `avgWin`
  - `avg_loss` → `avgLoss`
  - `profit_factor` → `profitFactor`
  - `sharpe_ratio` → `sharpeRatio`
  - `total_volume` → `totalVolume`
  - `volume_to_profit_ratio` → `volumeToProfitRatio`
  - `account_value` → `accountValue`
  - `squared_volume_profit_ratio` → `squaredVolumeProfitRatio`

**Methods and functions (lines 63-430+):**
- Line 72: `_ensure_output_dir` → `_ensureOutputDir`
- Line 76: `fetch_account_value` → `fetchAccountValue`
- Line 79: `user_state` → `userState`
- Line 93: `fetch_fills_with_adaptive_window` → `fetchFillsWithAdaptiveWindow`
- Line 96: `window_start` → `windowStart`
- Line 104: `window_end` → `windowEnd`
- Line 105: `start_ms`, `end_ms` → `startMs`, `endMs`
- Line 112: `user_fills_by_time` → `userFillsByTime`
- Line 114: `start_time`, `end_time` → `startTime`, `endTime`
- Line 174: `deduplicate_and_sort_fills` → `deduplicateAndSortFills`
- Line 186: `deduped_fills` → `dedupedFills`
- Line 191: `calculate_trade_metrics` → `calculateTradeMetrics`
- Line 199: `pnl_values` → `pnlValues`
- Line 200: `cumulative_pnl` → `cumulativePnl`
- Line 219: `running_max` → `runningMax`
- Line 232: `total_wins`, `total_losses` → `totalWins`, `totalLosses`
- Line 238: `returns_std` → `returnsStd`
- Line 271: `build_pnl_series` → `buildPnlSeries`
- Line 274: `cum_pnl` → `cumPnl`
- Line 276: `running_pnl`, `peak_pnl` → `runningPnl`, `peakPnl`
- Line 290: `create_enhanced_plots` → `createEnhancedPlots`
- Line 320: `metrics_data` → `metricsData`
- Line 334: `auto_set_font_size`, `set_fontsize` → `autoSetFontSize`, `setFontsize`
- Line 366: `plot_filename` → `plotFilename`
- Line 379: `fills_filename` → `fillsFilename`
- Line 383: `metrics_filename` → `metricsFilename`
- Line 387: `config_filename` → `configFilename`
- Line 393: `print_summary` → `printSummary`
- Line 413: `run_analysis` → `runAnalysis`
- Line 418: `raw_fills` → `rawFills`
- Line 424: `processed_fills` → `processedFills`

### walletTracker/scripts/walletViewer.py
**Lines with snake_case:**
- Line 15: `plot_pnl_from_trades` → `plotPnlFromTrades`
- Line 24: `wallet_address` → `walletAddress`
- Line 32: `status_code` → `statusCode`
- Line 45: `sorted_fills` → `sortedFills`
- Line 49: `cumulative_pnl`, `running_total` → `cumulativePnl`, `runningTotal`
- Line 57: `closed_pnl` → `closedPnl`

### walletTracker/scripts/history.py (MAJOR - 80+ instances)
**Lines with significant snake_case:**
- Line 68: `shutdown_event` → `shutdownEvent`
- Line 71: `handle_shutdown` → `handleShutdown`
- Line 82: `max_calls` → `maxCalls`
- Line 93: `sleep_time` → `sleepTime`
- Line 102: `extract_all_users` → `extractAllUsers`
- Line 106: `user_fields` → `userFields`
- Line 112: `extract_recursive` → `extractRecursive`
- Line 133: `batch_add_users` → `batchAddUsers`
- Line 133: `user_batch`, `users_collection` → `userBatch`, `usersCollection`
- Line 139: `current_time` → `currentTime`
- Line 147: `first_seen` → `firstSeen`
- Line 149: `last_seen` → `lastSeen`
- Line 150: `tx_count` → `txCount`
- Line 157: `bulk_write` → `bulkWrite`
- Line 158: `new_users`, `upserted_count` → `newUsers`, `upsertedCount`
- Line 159: `updated_users`, `modified_count` → `updatedUsers`, `modifiedCount`
- Line 172: `log_metrics`, `metric_type` → `logMetrics`, `metricType`
- Line 173: `metrics_collection` → `metricsCollection`
- Line 187: `setup_indexes` → `setupIndexes`
- Line 193: `existing_indexes`, `index_information` → `existingIndexes`, `indexInformation`
- Line 219: `get_active_coins` → `getActiveCoins`
- Line 238: `backfill_from_s3_limited` → `backfillFromS3Limited`
- Line 261: `s3_client` → `s3Client`
- Line 263: `region_name` → `regionName`
- Line 265: `signature_version` → `signatureVersion`
- Line 267: `addressing_style` → `addressingStyle`
- Line 272: `bucket_name` → `bucketName`
- Line 273: `explorer_blocks` → `explorerBlocks`
- Line 276: `total_blocks_to_list` → `totalBlocksToList`
- Line 279: `get_paginator`, `list_objects_v2` → Keep as-is (AWS API)
- Line 281: `all_blocks` → `allBlocks`
- Line 322: `blocks_to_consider` → `blocksToConsider`
- Line 329: `max_bytes` → `maxBytes`
- Line 330: `cumulative_size` → `cumulativeSize`
- Line 331: `blocks_to_process` → `blocksToProcess`
- Line 339: `total_size_gb` → `totalSizeGb`
- Line 343: `first_block_date`, `last_block_date` → `firstBlockDate`, `lastBlockDate`
- Line 350: `request_cost`, `transfer_cost` → `requestCost`, `transferCost`
- Line 352: `total_estimated_cost` → `totalEstimatedCost`
- Line 380: `total_new_users`, `downloaded_bytes` → `totalNewUsers`, `downloadedBytes`
- Line 384: `block_obj` → `blockObj`
- Line 385: `is_set` → Keep as-is (method name)
- Line 391: `block_size_mb` → `blockSizeMb`
- Line 395: `actual_block_num` → `actualBlockNum`

### walletTracker/wallets/website/backend/main.py (50+ instances)
**Lines with snake_case:**
- Line 26: `_cache` (internal) → `_cache` (keep)
- Line 28: `cache_get` → `cacheGet`
- Line 34: `cache_set` → `cacheSet`
- Line 42: `mongodb_client` → `mongodbClient`
- Line 43: `http_client` → `httpClient`
- Line 76: All MongoDB operations - Keep field names as-is
- Line 136: `sort_by` → `sortBy` (parameter)
- Line 153: `currentBalance` (from `balance_float`) ✓ Already camelCase
- Line 156: `count_pipeline`, `count_result` → `countPipeline`, `countResult`
- Line 158: `total_count` → `totalCount`
- Line 172: `get_profitable_traders` → `getProfitableTraders`
- Line 176: `page_size`, `sort_by`, `sort_direction` → `pageSize`, `sortBy`, `sortDirection`
- Line 189: `min_winrate`, `max_drawdown`, `min_balance`, `max_balance` → `minWinrate`, `maxDrawdown`, `minBalance`, `maxBalance`
- Line 205: `sort_field_map` → `sortFieldMap`
- Line 215: `total_count` → `totalCount`
- Line 216: `skip` → Keep (standard)
- Line 223: Store as-is for MongoDB but use camelCase in output
- Line 228: `withdrawableBalance`, `currentBalance` → Map DB fields
- Line 230: `gainDollar`, `gainPercent` → ✓ Already camelCase
- Line 234: `maxDrawdown` → ✓ Already camelCase
- Line 238: `openPositionsCount`, `openPositions` → ✓ Already camelCase
- Line 241: `totalVolume`, `avgTradeSize` → ✓ Already camelCase
- Line 242: `realizedPnl`, `unrealizedPnl` → ✓ Already camelCase
- Line 254: `historicalPnl`, `historicalBalance` → ✓ Already camelCase
- Line 256: `lastUpdated` → ✓ Already camelCase

### walletTracker/wallets/website/backend/scripts/activeTraders.py
- Line 26: `add_user` → `addUser`
- Line 28: `users_collection` → `usersCollection`
- Line 39: `websocket_watcher` → `websocketWatcher`
- Line 68: `daily_monitor` → `dailyMonitor`
- Line 76: `user_count` → `userCount`
- Line 78: `user_monitor` → `userMonitor`

### walletTracker/wallets/website/backend/scripts/fetchOI.py
- Line 14: `TARGET_COINS`, `SPIKE_THRESHOLD` → Keep constants
- Line 20: `get_trend_label` → `getTrendLabel`
- Line 21: `oi_chg`, `px_chg` → `oiChg`, `pxChg`
- Line 21: `oi_up`, `oi_down`, `px_up`, `px_down` → `oiUp`, `oiDown`, `pxUp`, `pxDown`
- Line 41: `fetch_binance_oi` → `fetchBinanceOi`
- Line 48: `oi_coins`, `price_url`, `mark_px` → `oiCoins`, `priceUrl`, `markPx`
- Line 59: `fetch_bybit_oi` → `fetchBybitOi`
- Line 73: `oi_data`, `retCode`, `open_interest` → `oiData`, `retCode`, `openInterest`
- Line 79: `mark_px` → `markPx`

### walletTracker/wallets/website/backend/scripts/whaleFinder.py
- Line 19: `extract_millionaires` → `extractMillionaires`
- Line 23: `profitability_coll`, `millionaires_coll` → `profitabilityColl`, `millionairesColl`
- Line 48: `inserted`, `updated`, `skipped` → Keep (counters)
- Line 52: `wallet_address` → `walletAddress`
- Line 54: `account_value` → Keep for MongoDB
- Line 61: `wallet_address` → `walletAddress` (local)
- Line 65: `last_updated` → Keep for MongoDB
- Line 70: `added_at` → Keep for MongoDB
- Line 89: `remove_below_threshold` → `removeBelowThreshold`

---

## 4. JAVASCRIPT/REACT FILES - SNAKE_CASE IDENTIFIERS

### walletTracker/scripts/leaderboardFetch.js
(Need to view file for specific identifiers)

### walletTracker/wallets/website/frontend/src/config.js
- Line 1: `REACT_APP_API_URL` → Keep (env var)
- Line 1: `API_BASE` → ✓ Already camelCase

### walletTracker/wallets/website/frontend/src/App.js
- Line 20: `isMarket` → ✓ Already camelCase
- Line 21: `isTraders` → ✓ Already camelCase
- Line 61: `MarketView` → Keep (component)
- Line 64: `selectedCoin` → ✓ Already camelCase
- Line 65: `chartType` → ✓ Already camelCase
- Line 83: `now` → ✓ Already camelCase
- Line 84: `filtered` → ✓ Already camelCase
- Line 89: `latest` → ✓ Already camelCase
- Line 90: `aggregate` → ✓ Already camelCase
- Line 93: `totalLong`, `totalShort` → ✓ Already camelCase
- Line 95: `totalOI` → ✓ Already camelCase
- Line 96: `netBiasPct` → ✓ Already camelCase
- Line 97: `biasColor` → ✓ Already camelCase
- Line 100: `periodBtns` → ✓ Already camelCase
- Line 105: `coinBtns` → ✓ Already camelCase
- Line 112: `typeBtns` → ✓ Already camelCase
- Line 263: `long_pct`, `short_pct` (in data) → Keep from backend

### walletTracker/wallets/website/frontend/src/hooks/useUsers.js
- Line 3: `useUserId` → Keep (hook convention)
- Line 7: `hl_user_id` → `hlUserId` (localStorage key)

### walletTracker/wallets/website/frontend/src/utils/formatters.js
- Line 3: `formatBalance` → ✓ Already camelCase

### walletTracker/wallets/website/frontend/src/utils/biasUtils.js
- Line 3: `calculateDirectionalBias` → ✓ Already camelCase
- Line 8: `longCount`, `shortCount` → ✓ Already camelCase
- Line 23: `longPct`, `shortPct` → ✓ Already camelCase

### walletTracker/wallets/website/frontend/src/utils/constants.js
- Line 1: `COIN_COLOURS` → Keep (constant)

### walletTracker/wallets/website/frontend/src/components/OITabs.jsx
- **Lines with snake_case in data variables:**
  - `oi_usd` → `oiUsd`
  - `total_oi` → `totalOi`
  - `mark_px` → `markPx`
  - `px_chg` → `pxChg`

### walletTracker/wallets/website/frontend/src/pages/profitability.jsx
- Line 15: `minWinrateInput`, `setMinWinrateInput` → ✓ Already camelCase
- Line 16: `maxDrawdownInput`, `setMaxDrawdownInput` → ✓ Already camelCase
- Line 17: `minBalanceInput`, `setMinBalanceInput` → ✓ Already camelCase
- Line 18: `maxBalanceInput`, `setMaxBalanceInput` → ✓ Already camelCase
- Line 19: `pageSizeInput`, `setPageSizeInput` → ✓ Already camelCase
- Line 20: `botFilterInput`, `setBotFilterInput` → ✓ Already camelCase
- Line 21: `activityFilterInput`, `setActivityFilterInput` → ✓ Already camelCase
- Line 23: `appliedFilters` → ✓ Already camelCase
- Line 24: `minWinrate`, `maxDrawdown`, `minBalance`, `maxBalance` → ✓ Already camelCase
- Line 28: `botFilter`, `activeOnly` → ✓ Already camelCase
- Line 33: `saved`, `traderFilters` → ✓ Already camelCase
- Line 62: `pageSize`, `setPageSize` → ✓ Already camelCase
- Line 63: `searchQuery`, `setSearchQuery` → ✓ Already camelCase
- Line 65: `sortBy`, `setSortBy`, `sortDirection`, `setSortDirection` → ✓ Already camelCase
- Line 89: `handleApplyFilters` → ✓ Already camelCase

### walletTracker/wallets/website/frontend/src/pages/watchlist.jsx
- Line 14: `setTraders` → ✓ Already camelCase
- Line 15: `setLoading` → ✓ Already camelCase
- Line 16: `searchQuery` → ✓ Already camelCase
- Line 20: `telegramId`, `setTelegramId` → ✓ Already camelCase
- Line 21: `tgSaved`, `setTgSaved` → ✓ Already camelCase
- Line 28: `loadWatchlist` → ✓ Already camelCase
- Line 34: `watchlistItems` → ✓ Already camelCase
- Line 35: `traderPromises` → ✓ Already camelCase
- Line 52: `saveTelegramId` → ✓ Already camelCase
- Line 65: `removeFromWatchlist` → ✓ Already camelCase
- Line 74: `sortedTraders` → ✓ Already camelCase
- Line 79: `fieldMap` → ✓ Already camelCase
- Line 85: `groupBias` → ✓ Already camelCase
- Line 87: `openPositions` → ✓ Already camelCase
- Line 89: `entry_price` (from data) → Keep from backend

### walletTracker/wallets/website/frontend/src/hooks/useProfitability.js
- Line 4: `API_URL` → Keep (constant)
- Line 6: `useProfitableTraders` → ✓ Already camelCase
- Line 12: `total_count`, `page_size` → Keep from backend (JSON response)
- Line 28: `URLSearchParams` → Keep (API)
- Line 29: `page`, `page_size` → Keep (params)
- Line 31: `sort_by`, `sort_direction` → Keep (params)
- Line 34: `min_winrate`, `max_drawdown`, `min_balance`, `max_balance` → Keep (params)
- Line 38: `active_only` → Keep (param)
- Line 75: `has_more` → Keep from backend
- Line 87: `has_more` → Keep from backend

### walletTracker/wallets/website/frontend/src/components/TraderTable.jsx
- Line 28: `TraderTable` → Keep (component)
- Line 54: `openTrades` → ✓ Already camelCase
- Line 57: `winrate` → ✓ Already camelCase
- Line 60: `drawdown` → ✓ Already camelCase
- Line 71: `isProfitable` → ✓ Already camelCase
- Line 76: `statusDot` → ✓ Already camelCase
- Line 88: `currentBalance` → ✓ Already camelCase
- Line 93: `pnlValue`, `pnlPercent` → ✓ Already camelCase
- Line 94: `gainDollar` → ✓ Already camelCase
- Line 97: `gainPercent` → ✓ Already camelCase

---

## 5. SUMMARY OF CONVERSION EFFORT

### Python Files (Highest Priority)
**Files with 50+ snake_case identifiers:**
1. `fullWalletTracker.py` - 100+ instances (dataclass fields, methods, variables)
2. `main.py` - 50+ instances (API parameters, MongoDB mapping)
3. `history.py` - 80+ instances (AWS S3, MongoDB operations)

**Files with 20+ instances:**
4. `snipeBot.py` - 25 instances
5. `Hotkeys.py` - 20 instances
6. `walletTracker.py` - 20+ instances

**Files with 10-20 instances:**
7. `output.py` - 18 instances
8. `fetchOI.py` - 15 instances
9. `whaleFinder.py` - 12 instances
10. `activeTraders.py` - 8 instances
11. `removeDupUsers.py` - 10 instances

### JavaScript/React Files (Medium Priority)
**Status:** Mostly compliant with camelCase already ✓

**Minor fixes needed:**
- API parameter names in query strings (keep as-is for backend compatibility)
- localStorage keys: `hl_user_id` → `hlUserId`, `telegram_id` → `telegramId`
- Data transformation layer where snake_case from MongoDB is converted to camelCase

### MongoDB Field Names (Keep as-is)
These should remain in snake_case for consistency with database schema:
- `wallet_address`, `account_value`, `total_pnl_usdc`
- `win_rate_percentage`, `max_drawdown_percentage`
- `has_trading_activity`, `is_likely_bot`, `is_vault_depositor`
- `open_positions`, `trade_count`, `historical_pnl`

---

## 6. KEY STATISTICS

- **Total Lines of Code:** 8,141
- **Python Files:** 25
- **JavaScript/React Files:** 20
- **Configuration Files:** 1 (package.json)
- **Total Snake_case Identifiers:** 300+ in Python, 50+ in JS
- **Estimated Conversion Effort:** 20-30 hours for thorough refactoring

---

## 7. PRIORITY CONVERSION ORDER

1. **Tier 1 (Critical):** fullWalletTracker.py, main.py, history.py
2. **Tier 2 (High):** snipeBot.py, Hotkeys.py, output.py
3. **Tier 3 (Medium):** Backend scripts (fetchOI, activeTraders, whaleFinder)
4. **Tier 4 (Low):** JavaScript/React (mostly already compliant)
5. **Tier 5 (Not Needed):** MongoDB field names, API parameters
___BEGIN___COMMAND_DONE_MARKER___0
