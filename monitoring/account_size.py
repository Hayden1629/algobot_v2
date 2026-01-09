"""
Account size monitoring module.
Periodically checks and logs account size to CSV file for graphing.
Also sends data to Railway database for remote dashboard.
"""
import csv
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
from loguru import logger
from schwab.account.client import AccountClient
from database.db_manager import DatabaseManager


class AccountSizeMonitor:
    """
    Monitors account size and logs to CSV file for graphing.
    """
    
    def __init__(self, account_client: AccountClient, log_file: Optional[str] = None):
        """
        Initialize account size monitor.
        
        Args:
            account_client: Schwab account client
            log_file: Path to CSV log file (default: account_size_history.csv in project root)
        """
        self.account_client = account_client
        
        if log_file is None:
            project_root = Path(__file__).parent.parent
            log_file = project_root / "account_size_history.csv"
        
        self.log_file = Path(log_file)
        
        # Initialize CSV file with headers if it doesn't exist
        if not self.log_file.exists():
            self._initialize_csv()
        
        # Initialize database manager for remote dashboard
        try:
            self.db_manager = DatabaseManager()
            if self.db_manager.is_available():
                logger.info("Database connection available - will send data to remote dashboard")
            else:
                logger.warning("Database not available - only logging locally to CSV")
                self.db_manager = None
        except Exception as e:
            logger.warning(f"Could not initialize database manager: {e} - only logging locally")
            self.db_manager = None
        
        logger.info(f"AccountSizeMonitor initialized - logging to {self.log_file}")
    
    def _initialize_csv(self):
        """Initialize CSV file with headers."""
        try:
            with open(self.log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp',
                    'account_value',
                    'buying_power',
                    'intraday_buying_power',
                    'cash_balance',
                    'equity',
                    'liquidation_value',
                    'long_exposure',
                    'short_exposure',
                    'net_exposure'
                ])
            logger.info(f"Initialized account size log file: {self.log_file}")
        except Exception as e:
            logger.error(f"Error initializing CSV file: {e}")
    
    def get_account_metrics(self) -> Dict:
        """
        Get current account metrics.
        
        Returns:
            dict: Account metrics including value, buying power, etc.
        """
        try:
            account_info = self.account_client.get_account_info()
            
            if not account_info:
                logger.error("Failed to retrieve account info")
                return {}
            
            # Parse account structure
            current_balances = None
            if 'securitiesAccount' in account_info:
                securities_account = account_info['securitiesAccount']
                if 'currentBalances' in securities_account:
                    current_balances = securities_account['currentBalances']
                elif 'balance' in securities_account:
                    current_balances = securities_account['balance']
            elif 'currentBalances' in account_info:
                current_balances = account_info['currentBalances']
            else:
                current_balances = account_info
            
            if not current_balances:
                logger.error("Could not find currentBalances in account info")
                return {}
            
            metrics = {
                'account_value': (
                    current_balances.get('liquidationValue') or
                    current_balances.get('totalEquity') or
                    current_balances.get('equity') or
                    current_balances.get('netValue')
                ),
                'buying_power': (
                    current_balances.get('buyingPower') or
                    current_balances.get('buyingPowerNonMarginableTrade') or
                    current_balances.get('availableFunds')
                ),
                'intraday_buying_power': (
                    current_balances.get('dayTradingBuyingPower') or
                    current_balances.get('intradayBuyingPower') or
                    current_balances.get('dayTradingBuyingPowerCall')
                ),
                'cash_balance': (
                    current_balances.get('cashBalance') or
                    current_balances.get('availableFunds')
                ),
                'equity': (
                    current_balances.get('equity') or
                    current_balances.get('totalEquity')
                ),
                'liquidation_value': current_balances.get('liquidationValue')
            }
            
            # Convert None to empty string for CSV
            return {k: (v if v is not None else '') for k, v in metrics.items()}
            
        except Exception as e:
            logger.error(f"Error getting account metrics: {e}")
            return {}
    
    def calculate_exposure(self) -> Dict[str, float]:
        """
        Calculate long, short, and net exposure from current positions.
        
        Returns:
            dict: {'long_exposure': float, 'short_exposure': float, 'net_exposure': float}
        """
        try:
            positions = self.account_client.get_positions()
            if positions is None:
                logger.warning("Could not retrieve positions for exposure calculation")
                return {'long_exposure': 0.0, 'short_exposure': 0.0, 'net_exposure': 0.0}
            
            long_exposure = 0.0
            short_exposure = 0.0
            
            for position in positions:
                long_qty = position.get('longQuantity', 0) or 0
                short_qty = position.get('shortQuantity', 0) or 0
                market_value = position.get('marketValue', 0) or 0
                
                # Use marketValue if available (most accurate)
                if market_value != 0:
                    if long_qty > 0:
                        # Long positions have positive market value
                        long_exposure += abs(market_value)
                    elif short_qty > 0:
                        # Short positions have negative market value
                        short_exposure += abs(market_value)
                else:
                    # Fallback: calculate from quantity and price
                    current_price = position.get('currentPrice', 0) or position.get('averagePrice', 0) or 0
                    if long_qty > 0 and current_price > 0:
                        long_exposure += long_qty * current_price
                    elif short_qty > 0 and current_price > 0:
                        short_exposure += short_qty * current_price
            
            net_exposure = long_exposure - short_exposure
            
            return {
                'long_exposure': round(long_exposure, 2),
                'short_exposure': round(short_exposure, 2),
                'net_exposure': round(net_exposure, 2)
            }
            
        except Exception as e:
            logger.error(f"Error calculating exposure: {e}")
            return {'long_exposure': 0.0, 'short_exposure': 0.0, 'net_exposure': 0.0}
    
    def log_account_size(self) -> bool:
        """
        Log current account size and exposure to CSV file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            metrics = self.get_account_metrics()
            
            if not metrics:
                logger.warning("No account metrics retrieved, skipping log")
                return False
            
            # Calculate exposure
            exposure = self.calculate_exposure()
            
            # Get current timestamp
            timestamp = datetime.now().isoformat()
            
            # Append to CSV file
            with open(self.log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    metrics.get('account_value', ''),
                    metrics.get('buying_power', ''),
                    metrics.get('intraday_buying_power', ''),
                    metrics.get('cash_balance', ''),
                    metrics.get('equity', ''),
                    metrics.get('liquidation_value', ''),
                    exposure.get('long_exposure', 0.0),
                    exposure.get('short_exposure', 0.0),
                    exposure.get('net_exposure', 0.0)
                ])
            
            account_value = metrics.get('account_value', 'N/A')
            long_exp = exposure.get('long_exposure', 0.0)
            short_exp = exposure.get('short_exposure', 0.0)
            net_exp = exposure.get('net_exposure', 0.0)
            
            logger.info(
                f"Account size logged: ${account_value:,.2f} | "
                f"Long: ${long_exp:,.2f} | "
                f"Short: ${short_exp:,.2f} | "
                f"Net: ${net_exp:,.2f}"
                if isinstance(account_value, (int, float)) 
                else f"Account size logged: {account_value} | Long: ${long_exp:,.2f} | Short: ${short_exp:,.2f} | Net: ${net_exp:,.2f}"
            )
            
            # Send to database for remote dashboard
            if self.db_manager and isinstance(account_value, (int, float)):
                try:
                    self.db_manager.insert_portfolio_value(account_value, datetime.now())
                    logger.debug("Portfolio value sent to database")
                except Exception as e:
                    logger.warning(f"Could not send portfolio value to database: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error logging account size: {e}")
            return False

