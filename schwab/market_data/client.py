"""
Schwab Market Data API client.
Handles market hours, quotes, and market data operations.
"""
import requests
from typing import Optional, Dict, Tuple, List
from datetime import datetime
import pytz
from loguru import logger
from schwab.tokens.manager import get_token_manager
from constants.parameters import SHOW_ORDER_OUTPUT


class MarketDataClient:
    """
    Client for Schwab Market Data API operations.
    Handles market hours, quotes, and market data.
    """
    
    def __init__(self):
        """Initialize the market data client."""
        self.token_manager = get_token_manager()
        # Market Data API base URL - for market hours and market data
        self.base_url = "https://api.schwabapi.com/marketdata/v1"
        # Cache headers to avoid frequent token requests
        self._headers_cache = None
        self._headers_cache_time = None
        self._headers_cache_ttl = 60  # Cache headers for 1 minute
        self._update_headers()
    
    def _update_headers(self, force: bool = False):
        """
        Update headers with current access token.
        Uses caching to avoid frequent token requests.
        
        Args:
            force: If True, force update even if cache is valid
        """
        import time
        current_time = time.time()
        
        # Use cached headers if available and not expired
        if not force and self._headers_cache and self._headers_cache_time:
            age = current_time - self._headers_cache_time
            if age < self._headers_cache_ttl:
                self.headers = self._headers_cache
                return
        
        try:
            access_token = self.token_manager.get_access_token()
            self.headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
            # Cache the headers
            self._headers_cache = self.headers.copy()
            self._headers_cache_time = current_time
        except Exception as e:
            logger.error(f"Failed to get access token: {e}")
            raise
    
    def get_market_hours(self, date: Optional[str] = None) -> Optional[Dict]:
        """
        Get market hours for a specific date.
        
        Args:
            date: Date in YYYY-MM-DD format. If None, uses today.
        
        Returns:
            dict: Market hours data or None if error
        """
        try:
            self._update_headers()
            
            # Get current date in Eastern timezone if not provided
            if date is None:
                eastern = pytz.timezone('US/Eastern')
                now_eastern = datetime.now(eastern)
                date = now_eastern.strftime('%Y-%m-%d')
            
            url = f"{self.base_url}/markets/hours"
            params = {
                'markets': 'EQUITY',
                'date': date
            }
            
            logger.debug(f"Requesting market hours from {url} with params {params}")
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                logger.debug("Market hours retrieved successfully")
                return data
            else:
                logger.error(f"Failed to get market hours: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting market hours: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting market hours: {e}")
            return None
    
    def is_market_open(self, delay_minutes: int = 0) -> Tuple[bool, str]:
        """
        Check if the stock market is open and has been open for at least delay_minutes.
        
        Args:
            delay_minutes: Minimum minutes market must have been open
        
        Returns:
            tuple: (is_open_for_delay, message)
        """
        try:
            self._update_headers()
            
            eastern = pytz.timezone('US/Eastern')
            now_eastern = datetime.now(eastern)
            current_date = now_eastern.strftime('%Y-%m-%d')
            
            market_hours_data = self.get_market_hours(current_date)
            if not market_hours_data:
                return False, "Could not retrieve market hours"
            
            # Parse response structure
            equity_data = None
            if 'equity' in market_hours_data and isinstance(market_hours_data['equity'], dict):
                if 'EQ' in market_hours_data['equity']:
                    equity_data = market_hours_data['equity']['EQ']
                else:
                    for key in market_hours_data['equity']:
                        equity_data = market_hours_data['equity'][key]
                        break
            elif 'EQUITY' in market_hours_data:
                equity_data = market_hours_data['EQUITY']
            elif 'isOpen' in market_hours_data:
                equity_data = market_hours_data
            
            if not equity_data or not isinstance(equity_data, dict):
                return False, "Could not parse market hours response"
            
            is_open = equity_data.get('isOpen', False)
            if not is_open:
                return False, "Market is currently closed"
            
            # Get regular market session times
            session_hours = equity_data.get('sessionHours', {})
            regular_market = session_hours.get('regularMarket', [])
            
            if regular_market and len(regular_market) > 0:
                regular_session = regular_market[0]
                open_time_str = regular_session.get('start', '2025-12-23T09:30:00-05:00')
            else:
                logger.warning("Could not find regularMarket session hours, using default 09:30")
                open_time_str = '09:30'
            
            # Parse open time
            try:
                if isinstance(open_time_str, str) and 'T' in open_time_str:
                    open_time_str_clean = open_time_str.replace('Z', '+00:00')
                    open_time = datetime.fromisoformat(open_time_str_clean)
                    if open_time.tzinfo is None:
                        open_time = eastern.localize(open_time)
                    else:
                        open_time = open_time.astimezone(eastern)
                elif isinstance(open_time_str, str) and ':' in open_time_str:
                    hour, minute = map(int, open_time_str.split(':'))
                    open_time = eastern.localize(datetime(
                        now_eastern.year, now_eastern.month, now_eastern.day, hour, minute
                    ))
                else:
                    raise ValueError(f"Unexpected open time format: {open_time_str}")
            except Exception as e:
                logger.warning(f"Could not parse open time, using default 09:30 ET: {e}")
                open_time = eastern.localize(datetime(
                    now_eastern.year, now_eastern.month, now_eastern.day, 9, 30
                ))
            
            # Calculate time difference from market open
            time_diff = now_eastern - open_time
            minutes_open = time_diff.total_seconds() / 60
            
            if minutes_open < 0:
                open_time_display = open_time.strftime('%H:%M') if isinstance(open_time, datetime) else open_time_str
                return False, f"Market opens at {open_time_display} ET (opens in {abs(int(minutes_open))} minutes)"
            elif minutes_open >= delay_minutes:
                return True, f"Market is open (open for {int(minutes_open)} minutes)"
            else:
                return False, f"Market is open but has only been open for {int(minutes_open)} minutes (need {delay_minutes})"
                
        except Exception as e:
            logger.error(f"Error checking market hours: {e}")
            return False, f"Error checking market hours: {str(e)}"
    
    def get_quote(self, symbol: str) -> Optional[float]:
        """
        Get current quote price for a symbol.
        
        Args:
            symbol: Stock ticker symbol
        
        Returns:
            float: Current price or None if error
        """
        quote_data = self.get_quote_full(symbol)
        if quote_data:
            # Try to get last price
            return quote_data.get('lastPrice') or quote_data.get('bidPrice') or quote_data.get('askPrice')
        return None
    
    def get_quotes_batch(self, symbols: List[str], max_retries: int = 3) -> Dict[str, Dict]:
        """
        Get full quote data for multiple symbols in a single API call.
        
        Args:
            symbols: List of stock ticker symbols
            max_retries: Maximum retry attempts
        
        Returns:
            dict: Dictionary mapping symbol to quote data, e.g. {'AAPL': {...}, 'MSFT': {...}}
        """
        if not symbols:
            return {}
        
        # Schwab API accepts comma-separated symbols
        symbols_str = ','.join([s.upper() for s in symbols])
        
        for attempt in range(max_retries):
            try:
                self._update_headers()
                
                url = f"{self.base_url}/quotes"
                params = {
                    'symbols': symbols_str
                }
                
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    # Response is a dict with symbols as keys
                    if SHOW_ORDER_OUTPUT:
                        logger.debug(f"Batch quotes retrieved for {len(data)} symbol(s)")
                    return data
                elif response.status_code == 404:
                    logger.debug(f"No quote data found (404)")
                    return {}
                else:
                    logger.warning(f"Failed to get batch quotes: {response.status_code} - {response.text}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    return {}
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"Network error getting batch quotes (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return {}
        
        return {}
    
    def get_quote_full(self, symbol: str, max_retries: int = 3) -> Optional[Dict]:
        """
        Get full quote data for a symbol.
        
        Args:
            symbol: Stock ticker symbol
            max_retries: Maximum retry attempts
        
        Returns:
            dict: Full quote data or None if error
        """
        for attempt in range(max_retries):
            try:
                self._update_headers()
                
                url = f"{self.base_url}/quotes"
                params = {
                    'symbols': symbol.upper()
                }
                
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    # Response is a dict with symbol as key
                    if symbol.upper() in data:
                        quote_data = data[symbol.upper()]
                        if SHOW_ORDER_OUTPUT:
                            logger.debug(f"Quote retrieved for {symbol}")
                        return quote_data
                    else:
                        logger.warning(f"Symbol {symbol} not found in quote response")
                        return None
                elif response.status_code == 404:
                    logger.debug(f"No quote data found for {symbol} (404)")
                    return None
                else:
                    logger.warning(f"Failed to get quote for {symbol}: {response.status_code} - {response.text}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    return None
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"Network error getting quote for {symbol} (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return None
            except Exception as e:
                logger.error(f"Error getting quote for {symbol}: {e}")
                return None
        
        return None

