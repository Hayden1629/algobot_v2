"""
Trade time tracking module.
Tracks trade ages and ensures they don't exceed maximum hold time.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger
import pytz
from constants.parameters import MAX_HOLD_TIME_MINUTES


class TradeTracker:
    """
    Tracks trade times and ensures they don't exceed maximum hold time.
    """
    
    def __init__(self, max_hold_minutes: float = None):
        """
        Initialize trade tracker.
        
        Args:
            max_hold_minutes: Maximum hold time in minutes (defaults to MAX_HOLD_TIME_MINUTES)
        """
        self.max_hold_minutes = max_hold_minutes or MAX_HOLD_TIME_MINUTES
        self.trades: Dict[str, Dict] = {}  # ticker -> trade info
    
    def add_trade(self, ticker: str, trade_id: Optional[str] = None, 
                  entry_time: Optional[datetime] = None) -> None:
        """
        Add a trade to tracking.
        
        Args:
            ticker: Stock ticker symbol
            trade_id: Optional trade ID
            entry_time: Entry time (defaults to now in UTC)
        """
        if entry_time is None:
            entry_time = datetime.now(pytz.UTC)
        elif entry_time.tzinfo is None:
            entry_time = pytz.UTC.localize(entry_time)
        else:
            entry_time = entry_time.astimezone(pytz.UTC)
        
        self.trades[ticker.upper()] = {
            'ticker': ticker.upper(),
            'trade_id': trade_id,
            'entry_time': entry_time,
            'age_minutes': 0.0
        }
        logger.debug(f"Added trade to tracker: {ticker} at {entry_time}")
    
    def remove_trade(self, ticker: str) -> None:
        """
        Remove a trade from tracking.
        
        Args:
            ticker: Stock ticker symbol
        """
        ticker_upper = ticker.upper()
        if ticker_upper in self.trades:
            del self.trades[ticker_upper]
            logger.debug(f"Removed trade from tracker: {ticker}")
    
    def update_ages(self) -> None:
        """Update age for all tracked trades."""
        now = datetime.now(pytz.UTC)
        for ticker, trade_info in self.trades.items():
            entry_time = trade_info['entry_time']
            age = now - entry_time
            trade_info['age_minutes'] = age.total_seconds() / 60
    
    def get_trade_age(self, ticker: str) -> Optional[float]:
        """
        Get the age of a trade in minutes.
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            float: Age in minutes, or None if trade not found
        """
        ticker_upper = ticker.upper()
        if ticker_upper not in self.trades:
            return None
        
        self.update_ages()
        return self.trades[ticker_upper]['age_minutes']
    
    def get_expired_trades(self) -> List[str]:
        """
        Get list of tickers that have exceeded maximum hold time.
        
        Returns:
            list: List of ticker symbols that should be closed
        """
        self.update_ages()
        expired = []
        
        for ticker, trade_info in self.trades.items():
            if trade_info['age_minutes'] >= self.max_hold_minutes:
                expired.append(ticker)
        
        return expired
    
    def get_all_tracked_tickers(self) -> List[str]:
        """
        Get all currently tracked tickers.
        
        Returns:
            list: List of ticker symbols being tracked
        """
        return list(self.trades.keys())
    
    def clear(self) -> None:
        """Clear all tracked trades."""
        self.trades.clear()
        logger.debug("Cleared all tracked trades")

