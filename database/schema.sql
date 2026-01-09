-- Simplified Trading Database Schema for algobot_v2
-- This schema is designed for Railway MySQL database
-- Only tracks portfolio value over time and past trades
-- DES_DATA table is kept for compatibility with other programs

-- Portfolio value history (for portfolio value over time chart)
CREATE TABLE IF NOT EXISTS portfolio_value_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    portfolio_value DECIMAL(15, 2) NOT NULL,
    account_value DECIMAL(15, 2) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_timestamp (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Simplified trades table (only essential fields)
CREATE TABLE IF NOT EXISTS trades (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,  -- 'LONG' or 'SHORT'
    quantity INT NOT NULL,
    entry_price DECIMAL(10, 4) NOT NULL,
    exit_price DECIMAL(10, 4) NULL,
    profit_loss DECIMAL(12, 6) NULL,
    profit_loss_percent DECIMAL(10, 6) NULL,
    time_placed DATETIME NOT NULL,
    close_time DATETIME NULL,
    hold_time_minutes DECIMAL(10, 4) NULL,
    order_id VARCHAR(50) NOT NULL,
    is_closed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_ticker (ticker),
    INDEX idx_time_placed (time_placed),
    INDEX idx_is_closed (is_closed),
    INDEX idx_order_id (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- DES_DATA table (kept for compatibility with other programs)
-- This table is managed by a different program, so we don't create it here
-- It should already exist in the database
