-- Trading Database Schema for SQLite
-- This schema is designed for local SQLite database

-- Main trades table
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,  -- 'LONG' or 'SHORT'
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NULL,
    profit_loss REAL NULL,
    profit_loss_percent REAL NULL,
    time_placed DATETIME NOT NULL,
    close_time DATETIME NULL,
    hold_time_minutes REAL NULL,
    order_id VARCHAR(50) NOT NULL,
    close_order_id VARCHAR(50) NULL,
    stop_loss_order_id VARCHAR(50) NULL,
    stop_loss_price REAL NULL,
    take_profit_price REAL NULL,
    is_winner INTEGER NULL,  -- SQLite uses INTEGER for BOOLEAN
    entry_order_type VARCHAR(20) NULL,
    exit_order_type VARCHAR(20) NULL,
    entry_spread REAL NULL,
    exit_spread REAL NULL,
    is_closed INTEGER DEFAULT 0,  -- SQLite uses INTEGER for BOOLEAN
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for trades table
CREATE INDEX IF NOT EXISTS idx_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_time_placed ON trades(time_placed);
CREATE INDEX IF NOT EXISTS idx_is_closed ON trades(is_closed);
CREATE INDEX IF NOT EXISTS idx_order_id ON trades(order_id);

-- Trade parameters table (one-to-one with trades)
CREATE TABLE IF NOT EXISTS trade_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    stop_loss_percent REAL NULL,
    take_profit_percent REAL NULL,
    trade_hold_minutes INTEGER NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE CASCADE,
    UNIQUE(trade_id)
);

-- PRT data table (one-to-one with trades)
CREATE TABLE IF NOT EXISTS prt_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    edge REAL NULL,
    prob_up REAL NULL,
    mean REAL NULL,
    p10 REAL NULL,
    p90 REAL NULL,
    dist1 REAL NULL,
    n INTEGER NULL,
    timestamp VARCHAR(50) NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE CASCADE,
    UNIQUE(trade_id)
);

-- Dashboard statistics snapshot table (for historical tracking)
CREATE TABLE IF NOT EXISTS dashboard_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate REAL NULL,
    total_profit_loss REAL DEFAULT 0,
    total_profit_loss_percent REAL DEFAULT 0,
    avg_profit_per_trade REAL NULL,
    avg_loss_per_trade REAL NULL,
    account_value REAL NULL,
    buying_power REAL NULL,
    cash_balance REAL NULL,
    day_trading_buying_power REAL NULL,
    snapshot_data TEXT NULL,  -- JSON stored as TEXT in SQLite
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_timestamp ON dashboard_snapshots(timestamp);

-- Active trades tracking (for real-time monitoring)
CREATE TABLE IF NOT EXISTS active_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    time_placed DATETIME NOT NULL,
    age_minutes REAL NULL,
    stop_loss_price REAL NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE CASCADE,
    UNIQUE(trade_id)
);

CREATE INDEX IF NOT EXISTS idx_ticker_active ON active_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_time_placed_active ON active_trades(time_placed);

-- Portfolio value history (for portfolio value over time chart)
CREATE TABLE IF NOT EXISTS portfolio_value_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    portfolio_value REAL NOT NULL,
    account_value REAL NULL,
    cumulative_pnl REAL NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_timestamp_portfolio ON portfolio_value_history(timestamp);

-- Portfolio beta history (for portfolio beta over time chart)
CREATE TABLE IF NOT EXISTS beta_over_time (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    portfolio_beta REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_timestamp_beta ON beta_over_time(timestamp);

-- DES (Description) data table (stock information from Godel Terminal)
CREATE TABLE IF NOT EXISTS des_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker VARCHAR(10) NOT NULL,
    company_name VARCHAR(255) NULL,
    asset_class VARCHAR(10) NULL,
    logo_url VARCHAR(500) NULL,
    website VARCHAR(500) NULL,
    address TEXT NULL,
    ceo VARCHAR(255) NULL,
    description TEXT NULL,
    eps_estimates TEXT NULL,  -- JSON stored as TEXT in SQLite
    -- Snapshot fields (flattened from JSON)
    exchange VARCHAR(255) NULL,
    currency VARCHAR(10) NULL,
    float_value VARCHAR(50) NULL,
    employees VARCHAR(50) NULL,
    insiders VARCHAR(20) NULL,
    institutions VARCHAR(20) NULL,
    p_sales VARCHAR(20) NULL,
    p_book VARCHAR(20) NULL,
    ev_ebitda VARCHAR(20) NULL,
    ev_r VARCHAR(20) NULL,
    ev VARCHAR(50) NULL,
    trl_pe VARCHAR(20) NULL,
    fwd_pe VARCHAR(20) NULL,
    trl_yld VARCHAR(20) NULL,
    fwd_yld VARCHAR(20) NULL,
    five_y_avg_yld VARCHAR(20) NULL,
    payout_ratio VARCHAR(20) NULL,
    ex_div_date DATE NULL,
    div_date DATE NULL,
    beta VARCHAR(20) NULL,
    short VARCHAR(50) NULL,
    short_ratio VARCHAR(20) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker)
);

CREATE INDEX IF NOT EXISTS idx_ticker_des ON des_data(ticker);
CREATE INDEX IF NOT EXISTS idx_updated_at_des ON des_data(updated_at);

-- SPY PRT snapshots table (for tracking SPY PRT data over time)
CREATE TABLE IF NOT EXISTS spy_prt_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    prob_up REAL NULL,
    edge REAL NULL,
    mean REAL NULL,
    p10 REAL NULL,
    p90 REAL NULL,
    dist1 REAL NULL,
    n INTEGER NULL,
    target_beta REAL NULL,  -- Calculated target beta from prob_up
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_timestamp_spy ON spy_prt_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_prob_up ON spy_prt_snapshots(prob_up);
CREATE INDEX IF NOT EXISTS idx_target_beta ON spy_prt_snapshots(target_beta);

