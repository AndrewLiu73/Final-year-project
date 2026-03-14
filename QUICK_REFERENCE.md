# Trading Tool Repository - Quick Reference Guide

## 📊 Analysis Overview

- **Total Files Analyzed:** 45
- **Total Lines of Code:** 8,141
- **Snake_case Identifiers:** 300+ (Python), 50+ (JavaScript)
- **Estimated Conversion Time:** 25-30 hours

---

## 🎯 Priority Conversion Order

### 🔴 Tier 1 - CRITICAL (Start Here)
Focus on highest impact files with most identifiers:

| File | Snake_case Count | Hours | Priority |
|------|-----------------|-------|----------|
| `fullWalletTracker.py` | 100+ | 8 | 1️⃣ |
| `history.py` | 80+ | 7 | 2️⃣ |
| `main.py` | 50+ | 6 | 3️⃣ |

**Key conversions in these files:**
- `fetch_account_value()` → `fetchAccountValue()`
- `calculate_trade_metrics()` → `calculateTradeMetrics()`
- `trader_address` → `traderAddress`
- `total_pnl` → `totalPnl`
- `cumulative_pnl` → `cumulativePnl`
- `extract_all_users()` → `extractAllUsers()`
- `backfill_from_s3_limited()` → `backfillFromS3Limited()`

### 🟠 Tier 2 - HIGH PRIORITY

| File | Snake_case Count | Hours |
|------|-----------------|-------|
| `snipeBot.py` | 25 | 3 |
| `Hotkeys.py` | 20 | 2 |
| `output.py` | 18 | 2 |

### �� Tier 3 - MEDIUM PRIORITY

| File | Snake_case Count | Hours |
|------|-----------------|-------|
| `fetchOI.py` | 15 | 2 |
| `whaleFinder.py` | 12 | 1.5 |
| `activeTraders.py` | 8 | 1 |

### 🟢 Tier 4 - LOW PRIORITY

- React/JavaScript files: Mostly already camelCase ✓ (~1 hour)

---

## 📝 Common Conversion Patterns

### Functions
```python
# Before
def get_user_data(user_id):
    pass

def calculate_total_pnl():
    pass

# After
def getUserData(user_id):
    pass

def calculateTotalPnl():
    pass
```

### Variables
```python
# Before
trader_address = "0x123..."
total_pnl = 1000
max_drawdown = -5.2
current_time = datetime.now()

# After
trader_address = "0x123..."  # Keep if from database
traderAddress = "0x123..."   # Use when processing in code
totalPnl = 1000
maxDrawdown = -5.2
currentTime = datetime.now()
```

### Parameters
```python
# Before
def get_profitable_traders(
    page_size: int,
    sort_by: str,
    min_winrate: float
):
    pass

# After
def getProfitableTraders(
    page_size: int,  # Keep for consistency with API
    sort_by: str,     # Keep for API compatibility
    min_winrate: float  # Keep for API compatibility
):
    pass
```

---

## ⚠️ DO NOT CONVERT

### MongoDB Field Names
These are part of the database schema - NEVER CONVERT:

```python
# ✗ DO NOT CHANGE THESE
wallet_address
account_value
total_pnl_usdc
win_rate_percentage
max_drawdown_percentage
has_trading_activity
is_likely_bot
is_vault_depositor
open_positions
trade_count
historical_pnl
historical_balance
last_updated
```

### API Query Parameters
Keep snake_case for backend compatibility:

```javascript
// Keep as-is in API calls
const params = new URLSearchParams();
params.append('page_size', 100);
params.append('sort_by', 'pnl');
params.append('sort_direction', 'desc');
params.append('min_winrate', 50);
params.append('max_drawdown', 30);
```

---

## 🔍 Top Snake_case Identifiers by File

### fullWalletTracker.py (HIGHEST PRIORITY)
```
trader_address → traderAddress
start_date → startDate
end_date → endDate
total_trades → totalTrades
winning_trades → winningTrades
win_rate → winRate
max_drawdown → maxDrawdown
sharpe_ratio → sharpeRatio
volume_to_profit_ratio → volumeToProfitRatio
fetch_account_value() → fetchAccountValue()
calculate_trade_metrics() → calculateTradeMetrics()
build_pnl_series() → buildPnlSeries()
create_enhanced_plots() → createEnhancedPlots()
plot_filename → plotFilename
metrics_filename → metricsFilename
```

### history.py (HIGH IMPACT)
```
shutdown_event → shutdownEvent
extract_all_users() → extractAllUsers()
batch_add_users() → batchAddUsers()
user_batch → userBatch
users_collection → usersCollection
current_time → currentTime
first_seen → firstSeen
last_seen → lastSeen
setup_indexes() → setupIndexes()
backfill_from_s3_limited() → backfillFromS3Limited()
s3_client → s3Client
addressing_style → addressingStyle
total_estimated_cost → totalEstimatedCost
```

### main.py (Backend API)
```
cache_get() → cacheGet()
cache_set() → cacheSet()
page_size → pageSize
sort_by → sortBy
sort_direction → sortDirection
min_winrate → minWinrate
max_drawdown → maxDrawdown
count_pipeline → countPipeline
total_count → totalCount
get_profitable_traders() → getProfitableTraders()
get_trader_details() → getTraderDetails()
```

---

## 🛠️ Conversion Strategy

### Step 1: Start with Tier 1 Files
- Focus on `fullWalletTracker.py`, `history.py`, `main.py`
- These have the most identifiers and highest impact

### Step 2: Use IDE Refactoring
- Use "Rename" feature in PyCharm/VS Code
- This will automatically update all references
- Test thoroughly after each refactor

### Step 3: Handle Database Fields Carefully
- Do NOT convert MongoDB field names
- Create mapping layer if needed:
  ```python
  # Python - keep DB field, use camelCase in code
  db_doc = collection.find_one()
  wallet_address = db_doc.get('wallet_address')  # From DB
  traderAddress = walletAddress  # Use in code
  ```

### Step 4: Update Tests
- Update all test files that reference renamed functions
- Ensure tests still pass after conversion

### Step 5: Documentation
- Update docstrings with new function names
- Update any API documentation if applicable

---

## 📚 Detailed Resources

For complete line-by-line breakdown, see:
- **SNAKE_CASE_ANALYSIS.md** - Full technical details
- **ANALYSIS_SUMMARY.txt** - Executive summary with priorities

---

## ✅ Conversion Checklist

- [ ] Start with fullWalletTracker.py
- [ ] Continue with history.py
- [ ] Convert main.py (backend API)
- [ ] Handle snipeBot.py, Hotkeys.py, output.py
- [ ] Convert backend scripts (fetchOI, whaleFinder, etc.)
- [ ] Update React components as needed
- [ ] Run full test suite
- [ ] Verify database operations still work
- [ ] Check API parameter handling

---

## 📞 Questions?

Refer to the detailed analysis files for:
- Specific line numbers for each identifier
- Code context and examples
- Conversion recommendations
- Effort estimates per file

Good luck with your refactoring! ��
