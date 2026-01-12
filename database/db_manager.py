"""
Database Manager for algobot_v2
Handles database operations for storing portfolio value and trades to Railway MySQL.
Simplified version - only tracks portfolio value over time and past trades.
"""
import mysql.connector
from mysql.connector import Error
from typing import Dict, List, Optional, Any
from datetime import datetime
import pytz
from loguru import logger
import os


class DatabaseManager:
    """Manages database connections and operations for algobot_v2."""
    
    def __init__(self):
        """Initialize database manager with Railway MySQL configuration."""
        self.config = self._get_db_config()
        self.connection = None
        if self.config:
            self._ensure_connection()
    
    def _get_db_config(self) -> Optional[Dict[str, Any]]:
        """
        Get database configuration from environment variables.
        Supports Railway (MYSQLHOST) and standard (MYSQL_HOST) naming.
        """
        # Check for Railway variables first (Railway naming convention)
        railway_host = os.getenv('MYSQLHOST') or os.getenv('MYSQL_HOST')
        railway_user = os.getenv('MYSQLUSER') or os.getenv('MYSQL_USER')
        railway_password = os.getenv('MYSQLPASSWORD') or os.getenv('MYSQL_PASSWORD') or os.getenv('MYSQL_ROOT_PASSWORD')
        railway_database = os.getenv('MYSQLDATABASE') or os.getenv('MYSQL_DATABASE')
        railway_port = os.getenv('MYSQLPORT') or os.getenv('MYSQL_PORT', '3306')
        
        if not railway_host:
            logger.warning("Railway MySQL environment variables not set - database features disabled")
            return None
        
        return {
            'host': railway_host,
            'port': int(railway_port),
            'user': railway_user or 'root',
            'password': railway_password,
            'database': railway_database or 'railway',
            'charset': 'utf8mb4',
            'collation': 'utf8mb4_unicode_ci',
            'autocommit': False
        }
    
    def _ensure_connection(self):
        """Ensure database connection is active, reconnect if needed."""
        if not self.config:
            return
        
        try:
            if self.connection is None or not self.connection.is_connected():
                self.connection = mysql.connector.connect(**self.config)
                logger.debug("Database connection established")
        except Error as e:
            logger.error(f"Error connecting to database: {e}")
            self.connection = None
    
    def _reconnect_if_needed(self):
        """Reconnect if connection is lost."""
        if not self.config or not self.connection:
            return
        
        try:
            self.connection.ping(reconnect=True, attempts=3, delay=1)
        except Error:
            self._ensure_connection()
    
    def is_available(self) -> bool:
        """Check if database is available."""
        if not self.config:
            return False
        
        try:
            self._reconnect_if_needed()
            return self.connection is not None and self.connection.is_connected()
        except Error:
            return False
    
    def insert_portfolio_value(self, account_value: float, timestamp: Optional[datetime] = None) -> bool:
        """
        Insert portfolio value snapshot into database.
        
        Args:
            account_value: Account value in dollars
            timestamp: Timestamp (defaults to now in UTC)
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_available():
            return False
        
        self._reconnect_if_needed()
        
        try:
            cursor = self.connection.cursor()
            
            if timestamp is None:
                timestamp = datetime.now(pytz.UTC)
            elif timestamp.tzinfo is None:
                timestamp = pytz.UTC.localize(timestamp)
            else:
                timestamp = timestamp.astimezone(pytz.UTC)
            
            insert_query = """
                INSERT INTO portfolio_value_history (
                    timestamp, portfolio_value, account_value
                ) VALUES (%s, %s, %s)
            """
            
            cursor.execute(insert_query, (
                timestamp,
                account_value,
                account_value
            ))
            
            self.connection.commit()
            cursor.close()
            logger.debug(f"Portfolio value inserted: ${account_value:,.2f} at {timestamp}")
            return True
            
        except Error as e:
            logger.error(f"Error inserting portfolio value: {e}")
            try:
                self.connection.rollback()
            except:
                pass
            return False
    
    def insert_trade(self, trade_data: Dict[str, Any]) -> Optional[int]:
        """
        Insert a trade into the database.
        
        Args:
            trade_data: Dictionary with trade information:
                - ticker: Stock ticker
                - action: 'LONG' or 'SHORT'
                - quantity: Number of shares
                - entry_price: Entry price
                - exit_price: Exit price (optional)
                - profit_loss: Profit/loss in dollars (optional)
                - profit_loss_percent: Profit/loss percentage (optional)
                - time_placed: Entry time (datetime)
                - close_time: Close time (datetime, optional)
                - order_id: Order ID
        
        Returns:
            int: Trade ID if successful, None otherwise
        """
        if not self.is_available():
            return None
        
        self._reconnect_if_needed()
        
        try:
            cursor = self.connection.cursor()
            
            # Parse timestamps
            time_placed = trade_data.get('time_placed')
            if isinstance(time_placed, str):
                time_placed = datetime.fromisoformat(time_placed.replace('Z', '+00:00'))
            if time_placed and time_placed.tzinfo is None:
                time_placed = pytz.UTC.localize(time_placed)
            elif time_placed:
                time_placed = time_placed.astimezone(pytz.UTC)
            
            close_time = trade_data.get('close_time')
            if isinstance(close_time, str):
                close_time = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            if close_time and close_time.tzinfo is None:
                close_time = pytz.UTC.localize(close_time)
            elif close_time:
                close_time = close_time.astimezone(pytz.UTC)
            
            # Calculate hold time if both times are available
            hold_time_minutes = None
            if time_placed and close_time:
                hold_time_minutes = (close_time - time_placed).total_seconds() / 60.0
            
            # Determine if trade is closed
            is_closed = close_time is not None
            
            trade_insert = """
                INSERT INTO trades (
                    ticker, action, quantity, entry_price, exit_price,
                    profit_loss, profit_loss_percent, time_placed, close_time,
                    hold_time_minutes, order_id, is_closed
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            trade_values = (
                trade_data.get('ticker'),
                trade_data.get('action'),
                trade_data.get('quantity'),
                trade_data.get('entry_price'),
                trade_data.get('exit_price'),
                trade_data.get('profit_loss'),
                trade_data.get('profit_loss_percent'),
                time_placed,
                close_time,
                hold_time_minutes,
                trade_data.get('order_id'),
                is_closed
            )
            
            cursor.execute(trade_insert, trade_values)
            trade_id = cursor.lastrowid
            
            self.connection.commit()
            cursor.close()
            logger.debug(f"Trade inserted successfully: ID {trade_id}, Ticker {trade_data.get('ticker')}")
            return trade_id
            
        except Error as e:
            logger.error(f"Error inserting trade: {e}")
            try:
                self.connection.rollback()
            except:
                pass
            return None
    
    def update_trade_on_close(self, ticker: str, exit_price: float, close_time: Optional[datetime] = None) -> bool:
        """
        Update a trade record when it is closed.
        
        Args:
            ticker: Stock ticker symbol
            exit_price: Exit price
            close_time: Close time (defaults to now in UTC)
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_available():
            return False
        
        self._reconnect_if_needed()
        
        try:
            cursor = self.connection.cursor()
            
            if close_time is None:
                close_time = datetime.now(pytz.UTC)
            elif close_time.tzinfo is None:
                close_time = pytz.UTC.localize(close_time)
            else:
                close_time = close_time.astimezone(pytz.UTC)
            
            # Find the most recent open trade for this ticker
            find_query = "SELECT id, entry_price, time_placed FROM trades WHERE ticker = %s AND is_closed = FALSE ORDER BY time_placed DESC LIMIT 1"
            cursor.execute(find_query, (ticker.upper(),))
            trade = cursor.fetchone()
            
            if not trade:
                logger.debug(f"Could not find open trade for ticker {ticker}")
                cursor.close()
                return False
            
            trade_id, entry_price, time_placed = trade
            
            # Calculate profit/loss
            # For LONG: profit = (exit_price - entry_price) * quantity
            # For SHORT: profit = (entry_price - exit_price) * quantity
            # We need to get the action and quantity from the trade record
            get_trade_query = "SELECT action, quantity FROM trades WHERE id = %s"
            cursor.execute(get_trade_query, (trade_id,))
            trade_info = cursor.fetchone()
            
            if not trade_info:
                cursor.close()
                return False
            
            action, quantity = trade_info
            
            # Convert database Decimal types to float for calculations
            entry_price = float(entry_price) if entry_price is not None else 0.0
            quantity = float(quantity) if quantity is not None else 0.0
            exit_price = float(exit_price) if exit_price is not None else 0.0
            
            # Calculate profit/loss
            if action == 'LONG':
                profit_loss = (exit_price - entry_price) * quantity
                # Profit percent for LONG: ((exit_price - entry_price) / entry_price) * 100
                profit_loss_percent = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            else:  # SHORT
                profit_loss = (entry_price - exit_price) * quantity
                # Profit percent for SHORT: ((entry_price - exit_price) / entry_price) * 100
                profit_loss_percent = ((entry_price - exit_price) / entry_price) * 100 if entry_price > 0 else 0
            
            # Calculate hold time
            if time_placed:
                if isinstance(time_placed, str):
                    time_placed = datetime.fromisoformat(time_placed.replace('Z', '+00:00'))
                if time_placed.tzinfo is None:
                    time_placed = pytz.UTC.localize(time_placed)
                else:
                    time_placed = time_placed.astimezone(pytz.UTC)
                
                hold_time_minutes = (close_time - time_placed).total_seconds() / 60.0
            else:
                hold_time_minutes = None
            
            # Update the trade record
            update_query = """
                UPDATE trades 
                SET exit_price = %s,
                    profit_loss = %s,
                    profit_loss_percent = %s,
                    close_time = %s,
                    hold_time_minutes = %s,
                    is_closed = TRUE
                WHERE id = %s
            """
            
            cursor.execute(update_query, (
                exit_price,
                profit_loss,
                profit_loss_percent,
                close_time,
                hold_time_minutes,
                trade_id
            ))
            
            self.connection.commit()
            cursor.close()
            logger.info(f"✓ Trade updated on close: ID {trade_id}, Ticker {ticker}, Exit price ${exit_price:.2f}, Entry price ${entry_price:.2f}, P&L ${profit_loss:.2f} ({profit_loss_percent:.2f}%)")
            return True
            
        except Error as e:
            logger.error(f"Error updating trade on close: {e}")
            try:
                self.connection.rollback()
            except:
                pass
            return False
    
    def close(self):
        """Close database connection."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logger.debug("Database connection closed")

