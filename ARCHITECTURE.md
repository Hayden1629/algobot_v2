# Algobot v2 Architecture

This document describes the architecture of algobot_v2. It is maintained and updated after every significant change.

## Overview

Algobot v2 is a modular trading algorithm system that interfaces with Godel Terminal for market data and executes trades through Schwab API. The system is designed with maintainability and organization as core principles.

## Directory Structure

```
algobot_v2/
├── constants/          # Global constants and parameters
│   ├── __init__.py
│   ├── parameters.py  # All configuration values, thresholds, hyperparameters
│   └── blacklist.py   # Commission blacklist for stocks
│
├── schwab/            # Schwab API integration
│   ├── __init__.py
│   ├── tokens/        # Token management (Schwab API)
│   │   ├── __init__.py
│   │   ├── acquisition.py  # Initial OAuth token acquisition
│   │   ├── storage.py      # Token file storage operations
│   │   ├── refresh.py      # Token refresh logic
│   │   └── manager.py      # Token manager (orchestrates token operations)
│   ├── account/       # Account data operations (Trader API)
│   │   ├── __init__.py
│   │   ├── client.py   # Account client (positions, orders, account info)
│   │   └── orders.py   # Order manager (order creation, cancellation)
│   └── market_data/   # Market data operations (Market Data API)
│       ├── __init__.py
│       └── client.py   # Market data client (quotes, market hours)
│
├── database/          # Database management
│   ├── __init__.py
│   ├── schema.sql     # SQLite database schema
│   └── init.py        # Database initialization
│
├── core/              # Core framework
│   ├── __init__.py
│   └── controller.py  # Godel Terminal controller and base classes
│
├── commands/          # Godel Terminal commands
│   ├── __init__.py
│   ├── des_command.py
│   ├── prt_command.py
│   ├── most_command.py
│   └── ...            # Other command implementations
│
├── strategy/          # Trading strategy
│   ├── __init__.py
│   ├── rolling_strategy.py  # Rolling strategy implementation
│   ├── trade_tracker.py     # Trade time tracking
│   ├── position_sizing.py   # Position sizing calculations
│   └── trade_executor.py    # Trade execution with limit orders
│
├── monitoring/        # System monitoring
│   ├── __init__.py
│   └── account_size.py      # Account size monitoring and CSV logging
│
├── scripts/           # Utility scripts
│   ├── __init__.py
│   ├── startup.py           # System startup and main trading loop
│   ├── algo_loop.py         # Main algorithm loop (alternative entry point)
│   └── close_all_positions.py  # Emergency position closer
│
├── RULES.md           # Architecture rules and guidelines
├── ARCHITECTURE.md    # This file
├── requirements.txt   # Python dependencies
└── README.md          # Project documentation
```

## Module Descriptions

### Constants Package (`constants/`)

**Purpose**: Centralized storage of all configuration values, parameters, and hyperparameters.

**Key Files**:
- `parameters.py`: Contains all global constants including:
  - Godel Terminal configuration (URL, credentials)
  - Schwab API configuration (app key, secret)
  - Token management parameters (refresh intervals, expiry buffers)
  - Database configuration (type, name, path)
  - Trading parameters (stop loss, take profit percentages, max position size)
  - PRT strategy parameters (prob_up thresholds, edge thresholds)
  - MOST command parameters (tab, limit)
  - Market hours parameters
  - Order parameters (limit order settings, price offsets)
  - Account monitoring parameters (check interval)
  - Timeouts and browser settings

- `blacklist.py`: Commission blacklist for stocks that have trading commissions

**Design Principle**: No magic numbers or hardcoded values in business logic. All constants are defined here.

### Schwab Package (`schwab/`)

**Purpose**: Complete Schwab API integration, organized by API type.

#### Tokens Subpackage (`schwab/tokens/`)

**Purpose**: Manages Schwab API authentication tokens.

**Modules**:
1. **`acquisition.py`**: Handles initial OAuth flow
   - Constructs authorization URL
   - Opens browser for user authorization
   - Exchanges authorization code for tokens
   - Saves tokens to storage

2. **`storage.py`**: Manages token file storage
   - Saves tokens to secure JSON file
   - Loads tokens from file
   - Checks token expiry
   - Provides access to access/refresh tokens

3. **`refresh.py`**: Handles token refresh
   - Uses refresh token to get new access token
   - Updates stored tokens

4. **`manager.py`**: Orchestrates token operations
   - Singleton pattern for global access
   - Thread-safe token access
   - Automatic background refresh
   - Provides `get_access_token()` method

**Control Flow**:
```
User runs acquisition → Tokens saved to storage
System starts → TokenManager loads tokens
TokenManager runs background thread → Refreshes tokens every 29 minutes
Application code → Calls TokenManager.get_access_token()
```

#### Account Subpackage (`schwab/account/`)

**Purpose**: Handles Schwab Trader API operations for account data.

**Modules**:
1. **`client.py`**: AccountClient class
   - Account information retrieval
   - Position management (get_positions)
   - Account hash value retrieval
   - Uses Trader API base URL: `https://api.schwabapi.com/trader/v1`

2. **`orders.py`**: OrderManager class
   - Order creation (market orders, limit orders)
   - Order cancellation
   - Order status checking (`get_order_status()`)
   - Retry logic with exponential backoff for rate limiting
   - Handles "Order in state FILLED cannot be canceled" error detection

**Key Methods**:
- `AccountClient.get_account_info()`: Get account balance, equity, buying power
- `AccountClient.get_positions()`: Get current positions
- `OrderManager.create_market_order()`: Create market order
- `OrderManager.create_limit_order()`: Create limit order with price
- `OrderManager.cancel_order()`: Cancel an order
- `OrderManager.get_order_status()`: Get order status and fill information

#### Market Data Subpackage (`schwab/market_data/`)

**Purpose**: Handles Schwab Market Data API operations.

**Modules**:
1. **`client.py`**: MarketDataClient class
   - Market hours checking
   - Quote retrieval (get_quote, get_quote_full)
   - Uses Market Data API base URL: `https://api.schwabapi.com/marketdata/v1`

**Key Methods**:
- `get_market_hours()`: Get market hours for a date
- `is_market_open()`: Check if market is open with delay check
- `get_quote()`: Get current price for a symbol
- `get_quote_full()`: Get full quote data including exchange info
  - Returns nested structure with `quote` field containing `bidPrice`, `askPrice`, `lastPrice`
  - Also includes `regular` field with `regularMarketLastPrice`

### Database Package (`database/`)

**Purpose**: Manages local SQLite database for trade and PRT data storage.

**Modules**:
1. **`schema.sql`**: Database schema definition
   - Tables: trades, trade_parameters, prt_data, des_data, etc.
   - Indexes for performance
   - Foreign key relationships

2. **`init.py`**: Database initialization
   - Creates database file if it doesn't exist
   - Executes schema to create tables
   - Provides connection management

**Database Structure**:
- **trades**: Main trade records
- **trade_parameters**: Trade-specific parameters (stop loss, take profit)
- **prt_data**: PRT (Probability Return Table) data associated with trades
- **des_data**: Stock description data from Godel Terminal
- **dashboard_snapshots**: Historical dashboard statistics
- **active_trades**: Real-time active trade tracking
- **portfolio_value_history**: Portfolio value over time
- **beta_over_time**: Portfolio beta tracking
- **spy_prt_snapshots**: SPY PRT data over time

### Core Package (`core/`)

**Purpose**: Core framework for Godel Terminal interaction.

**Modules**:
1. **`controller.py`**: Main controller and base classes
   - `DOMMonitor`: Monitors DOM for new windows
   - `BaseCommand`: Abstract base class for all commands
   - `GodelTerminalController`: Main controller class

**Key Classes**:

#### `DOMMonitor`
- Monitors DOM for new command windows
- Tracks window creation and loading states
- Provides methods to wait for windows and loading completion

#### `BaseCommand` (Abstract)
- Base class for all Godel Terminal commands
- Handles command execution flow:
  1. Get command string
  2. Send command to terminal
  3. Wait for new window
  4. Wait for loading
  5. Extract data
- Provides window closing functionality

#### `GodelTerminalController`
- Manages browser automation
- Handles login and authentication
- Manages command registration and execution
- Provides methods:
  - `connect()`: Initialize browser
  - `login()`: Authenticate with Godel Terminal
  - `load_layout()`: Load specific layout
  - `open_terminal()`: Open terminal interface
  - `send_command()`: Send command string
  - `execute_command()`: Execute registered command
  - `disconnect()`: Clean shutdown

**Control Flow**:
```
Controller.connect() → Browser opens → Navigate to Godel Terminal
Controller.login() → Enter credentials → Wait for main page
Controller.load_layout() → Select layout → Wait for layout load
Controller.open_terminal() → Press backtick → Terminal opens
Controller.execute_command() → Send command → Wait for window → Extract data
```

### Commands Package (`commands/`)

**Purpose**: Implementations of specific Godel Terminal commands.

**Design**: Each command inherits from `BaseCommand` and implements:
- `get_command_string()`: Returns the command string to send
- `extract_data()`: Extracts data from the command window

**Implemented Commands**:
- **DES**: Description command - gets stock information
- **PRT**: Probability Return Table command - batch analysis of tickers
- **MOST**: Most Active Stocks command - gets active/gainers/losers lists
- **G**: Generic command
- **GIP**: Generic IP command
- **QM**: Query Market command

### Strategy Package (`strategy/`)

**Purpose**: Trading strategy implementation.

**Modules**:
1. **`rolling_strategy.py`**: RollingStrategy class
   - Implements rolling (continuous) strategy (not batch-based)
   - Collects tickers from MOST
   - Sorts by prob_up thresholds
   - Creates positions based on PRT predictions
   - Maintains positions by re-running PRT
   - **Position Direction Checking**:
     - Compares PRT direction (prob_up > 50% = LONG, < 50% = SHORT) with current position direction
     - If PRT direction matches position direction → Keep position (log it)
     - If PRT direction is opposite → Close position
   - **Boxed Position Prevention**:
     - Checks existing positions before opening new ones
     - Only opens positions for tickers not already in portfolio
     - Prevents attempting to open positions that would create boxed positions
   - **Position Closing**:
     - Uses limit orders first when closing positions
     - Falls back to market orders if limit orders don't fill
     - Checks order fills and retries if needed
   - **Rolling Cycle Logic**:
     - First iteration: MOST tickers only → PRT → Open positions
     - Subsequent iterations: (Active positions from previous) + MOST → PRT → Maintain/close/open
   - **Key Methods**:
     - `get_position_details()`: Get position direction (LONG/SHORT) and quantity
     - `should_close_position()`: Determine if position should be closed based on PRT
     - `execute_cycle()`: Main strategy execution cycle

2. **`trade_tracker.py`**: TradeTracker class
   - Tracks trade entry times
   - Calculates trade ages
   - Identifies trades exceeding maximum hold time
   - Ensures trades don't exceed MAX_HOLD_TIME_MINUTES

3. **`position_sizing.py`**: PositionSizer class
   - Retrieves buying power from Schwab account
     - Prioritizes intraday buying power (dayTradingBuyingPower) for day trading
     - Falls back to regular buying power if intraday not available
     - Logs both intraday and regular buying power when available
   - Gets current market prices
     - Checks nested `quote` field first (primary structure in Schwab API)
     - Falls back to `regular` field, then top-level fields
     - Handles various price field names (lastPrice, regularMarketLastPrice, bidPrice, askPrice)
   - Calculates position sizes based on:
     - Maximum position size constraint (MAX_POSITION_SIZE_DOLLARS)
     - Available buying power
   - Sizes trades to ensure each position is under max size limit

4. **`trade_executor.py`**: TradeExecutor class
   - Executes trades using limit orders
   - Gets bid/ask prices from market data
     - Checks nested `quote` field first for bid/ask prices
     - Falls back to last price if bid/ask not available
     - Uses last price as primary source (bid/ask may not be available)
   - Uses optimal pricing:
     - **Longs**: Uses bid price (or last price if bid unavailable)
     - **Shorts**: Uses ask price (or last price if ask unavailable)
   - **Order Fill Verification**:
     - After placing all orders, checks each order's fill status
     - If not filled, cancels order, gets new price quote, and places new order
     - Retries up to 3 times with updated prices
     - Falls back to market orders if limit orders don't fill after retries
     - Handles "Order in state FILLED cannot be canceled" error (treats as fill)
     - Only reports "Trade Execution Complete" when all orders are filled
   - Handles order execution with error handling

**Strategy Flow**:
```
Get tickers from MOST → Get open positions with directions → Combine tickers
→ Run PRT analysis → Compare PRT direction with position direction
→ Keep positions where PRT matches position direction
→ Close positions where PRT direction is opposite (using limit orders, fallback to market)
→ Filter new candidates (exclude tickers already in positions to avoid boxed positions)
→ Size positions (PositionSizer) → Execute trades (TradeExecutor)
→ Verify order fills → Retry unfilled orders with new prices
→ Track trade times → Close expired trades
→ Next iteration: Active positions feed into PRT analysis
```

### Monitoring Package (`monitoring/`)

**Purpose**: System monitoring and performance tracking.

**Modules**:
1. **`account_size.py`**: AccountSizeMonitor class
   - Periodically checks account size and metrics
   - Logs to CSV file (`account_size_history.csv`) for easy graphing
   - Tracks: account_value, buying_power, intraday_buying_power, cash_balance, equity, liquidation_value
   - Configurable check interval (ACCOUNT_SIZE_CHECK_INTERVAL_MINUTES)
   - CSV format with timestamp for easy visualization

**Key Methods**:
- `get_account_metrics()`: Retrieves current account metrics from Schwab API
- `log_account_size()`: Appends account metrics to CSV file with timestamp

### Scripts Package (`scripts/`)

**Purpose**: Utility and startup scripts.

**Modules**:
1. **`startup.py`**: Main system startup and trading loop
   - Checks prerequisites (database, tokens)
   - Checks token file age (re-acquires if > 29 minutes old)
   - Initializes database if needed
   - Acquires tokens if needed
   - Initializes Schwab API clients (AccountClient, MarketDataClient, OrderManager)
   - Initializes Godel Terminal controller
   - Initializes AccountSizeMonitor for periodic account tracking
   - Runs supervisor loop (when market closed)
   - Runs trading loop (when market open)
   - Executes rolling strategy cycles continuously
   - Monitors market hours and closes positions before market close
   - Logs account size periodically during trading
   - Handles cleanup on exit

2. **`algo_loop.py`**: Alternative algorithm loop entry point
   - Similar functionality to startup.py
   - Can be used as alternative entry point

3. **`close_all_positions.py`**: Emergency position closer
   - Standalone script for emergency closure
   - Cancels all open orders
   - Closes all positions with market orders
   - Includes confirmation prompts for safety

**Control Flow**:
```
startup.py → Check prerequisites → Initialize database → Check tokens
→ Initialize Schwab clients → Initialize Godel controller
→ Supervisor loop (market closed) OR Trading loop (market open)
→ Rolling strategy cycles → Position sizing → Trade execution
→ Monitor market hours → Close positions before market close
→ Cleanup on exit
```

## Class Hierarchy

```
BaseCommand (ABC)
    ├── DESCommand
    ├── PRTCommand
    ├── MOSTCommand
    ├── GCommand
    ├── GIPCommand
    └── QMCommand

TokenManager (Singleton)
    ├── Uses: schwab.tokens.storage
    ├── Uses: schwab.tokens.refresh
    └── Provides: get_access_token()

AccountClient
    ├── Uses: schwab.tokens.manager
    └── Provides: get_positions(), get_account_info(), get_all_open_orders()

MarketDataClient
    ├── Uses: schwab.tokens.manager
    └── Provides: get_market_hours(), is_market_open(), get_quote()

GodelTerminalController
    ├── Uses: DOMMonitor
    ├── Manages: BaseCommand instances
    └── Provides: execute_command()

RollingStrategy
    ├── Uses: GodelTerminalController
    ├── Uses: AccountClient
    ├── Uses: MarketDataClient
    ├── Uses: TradeTracker
    ├── Uses: OrderManager
    └── Provides: execute_cycle()

TradeTracker
    └── Provides: track trades, check expiration

PositionSizer
    ├── Uses: AccountClient
    ├── Uses: MarketDataClient
    └── Provides: size_trades(), get_buying_power(), get_current_price()

TradeExecutor
    ├── Uses: AccountClient
    ├── Uses: MarketDataClient
    ├── Uses: OrderManager
    └── Provides: execute_trades(), execute_trade(), get_limit_price(), get_bid_ask_prices()

OrderManager
    ├── Uses: AccountClient
    ├── Uses: MarketDataClient
    └── Provides: create_market_order(), create_limit_order(), cancel_order(), get_order_status()

AccountSizeMonitor
    ├── Uses: AccountClient
    └── Provides: log_account_size(), get_account_metrics()
```

## Dependencies

### External Dependencies
- `selenium`: Browser automation
- `webdriver-manager`: Chrome driver management
- `pandas`: Data manipulation
- `requests`: HTTP requests (token management)
- `loguru`: Logging
- `yfinance`: Market data (if needed)

### Internal Dependencies
- `constants.parameters` → Used by all modules
- `constants.blacklist` → Used by `strategy.rolling_strategy`
- `tokens.storage` → Used by `tokens.acquisition`, `tokens.refresh`, `tokens.manager`
- `tokens.refresh` → Used by `tokens.manager`
- `tokens.manager` → Used by `schwab.account.client`, `schwab.market_data.client`
- `core.controller` → Used by `commands.*`, `strategy.rolling_strategy`
- `database.init` → Used by `scripts.startup`
- `schwab.account.client` → Used by `schwab.account.orders`, `strategy.*`
- `schwab.market_data.client` → Used by `schwab.account.orders`, `strategy.*`
- `schwab.account.orders` → Used by `strategy.trade_executor`, `scripts.*`

## Data Flow

### Token Flow
```
User → tokens.acquisition.acquire_tokens()
  → OAuth flow → tokens.storage.save_tokens()
  → tokens.manager.TokenManager (loads on init)
  → Background thread refreshes periodically
  → Application calls TokenManager.get_access_token()
```

### Command Execution Flow
```
Application → GodelTerminalController.execute_command()
  → BaseCommand.execute()
  → Controller.send_command()
  → DOMMonitor.get_new_window()
  → DOMMonitor.wait_for_loading()
  → BaseCommand.extract_data()
  → Return data to application
```

### Database Flow
```
Application → database.init.get_connection()
  → SQLite connection
  → Insert/query trades, PRT data, etc.
```

### Trading Flow
```
RollingStrategy.execute_cycle()
  → Get tickers from MOST
  → Get active positions with directions (get_position_details())
  → Combine and run PRT
  → Compare PRT direction with position direction
  → Keep positions where directions match
  → Close positions where directions are opposite
    → TradeExecutor.get_limit_price() for closing price
    → OrderManager.create_limit_order() (limit order first)
    → Check order fills → Fallback to market order if needed
  → Filter new candidates (exclude existing positions)
  → PositionSizer.size_trades()
    → Get buying power (prioritize intraday)
    → Get current prices (check nested quote field)
    → Calculate position sizes
  → TradeExecutor.execute_trades()
    → Get bid/ask prices (from nested quote field, fallback to last price)
    → Determine limit prices (bid for longs, ask for shorts, or last price)
    → OrderManager.create_limit_order()
    → Place orders via Schwab API
    → Check order fills (get_order_status())
    → Retry unfilled orders with new prices
    → Handle "FILLED cannot be canceled" error (treat as fill)
    → Fallback to market orders if limit orders don't fill
```

### Account Monitoring Flow
```
Trading loop → AccountSizeMonitor initialized
  → Every ACCOUNT_SIZE_CHECK_INTERVAL_MINUTES:
    → AccountSizeMonitor.get_account_metrics()
      → AccountClient.get_account_info()
      → Extract account_value, buying_power, etc.
    → AccountSizeMonitor.log_account_size()
      → Append to account_size_history.csv
      → Format: timestamp, account_value, buying_power, intraday_buying_power, cash_balance, equity, liquidation_value
```

## Design Patterns

1. **Singleton Pattern**: `TokenManager` - ensures single instance for token management
2. **Abstract Base Class**: `BaseCommand` - defines interface for commands
3. **Factory Pattern**: `GodelTerminalController.register_command()` - registers command types
4. **Repository Pattern**: `tokens.storage` - abstracts token storage details

## Recent Updates

### Order Fill Verification
- TradeExecutor now verifies all orders are filled before reporting completion
- Checks order status after placement
- Retries unfilled orders with updated prices
- Handles "Order in state FILLED cannot be canceled" error correctly
- Falls back to market orders if limit orders don't fill after retries

### Boxed Position Prevention
- RollingStrategy now checks existing positions before opening new ones
- Compares PRT direction with current position direction
- Only opens positions for tickers not already in portfolio
- Prevents attempting to create boxed positions

### Position Direction Matching
- Compares PRT prediction direction (prob_up > 50% = LONG, < 50% = SHORT) with current position
- Keeps positions where PRT direction matches position direction
- Closes positions where PRT direction is opposite
- Uses limit orders first when closing, with market order fallback

### Price Data Extraction
- Updated to check nested `quote` field in Schwab API response
- Handles various price field names (lastPrice, regularMarketLastPrice, bidPrice, askPrice)
- Falls back through multiple field locations for robustness

### Account Size Monitoring
- New monitoring package tracks account size periodically
- Logs to CSV file for easy graphing
- Tracks account value, buying power, cash balance, equity, etc.
- Configurable check interval

### Buying Power Display
- PositionSizer now prioritizes and displays intraday buying power
- Shows both intraday and regular buying power when available
- Better suited for day trading operations

## Future Enhancements

1. **Database Manager**: Add database manager class for trade operations
2. **Error Handling**: Enhanced error handling and recovery
3. **Testing**: Unit tests for critical components
4. **Configuration**: Environment-based configuration management
5. **Risk Management**: Enhanced risk management features (position limits, daily loss limits)
6. **Performance Metrics**: Track strategy performance and statistics
7. **Backtesting**: Historical backtesting capabilities

## Maintenance Notes

- This document should be updated after every significant architectural change
- When adding new modules, update the directory structure section
- When adding new classes, update the class hierarchy section
- When changing control flow, update the relevant control flow sections

