"""
Schwab Trader API client for account operations.
Handles positions, orders, and account information.
"""
import requests
import pandas
from typing import Optional, List, Dict
from loguru import logger
from datetime import datetime
import pytz
from schwab.tokens.manager import get_token_manager


class AccountClient:
    """
    Client for Schwab Trader API account operations.
    Handles positions, orders, and account information.
    """
    
    def __init__(self):
        """Initialize the account client."""
        self.token_manager = get_token_manager()
        self.account_hash_value = None
        # Trader API base URL - for account and order operations
        self.base_url = "https://api.schwabapi.com/trader/v1"
        # Cache headers to avoid frequent token requests
        self._headers_cache = None
        self._headers_cache_time = None
        self._headers_cache_ttl = 60  # Cache headers for 1 minute
        self._update_headers()
        self.get_account_number_hash_value()
    
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
    
    def get_account_number_hash_value(self):
        """Get and store the account hash value."""
        self._update_headers()
        response = requests.get(
            self.base_url + "/accounts/accountNumbers", 
            headers=self.headers
        )
        if response.status_code != 200:
            logger.error(f"Failed to get account numbers: {response.status_code} - {response.text}")
            raise RuntimeError(f"API request failed: {response.status_code}")
        response_frame = pandas.json_normalize(response.json())
        self.account_hash_value = response_frame["hashValue"].iloc[0]
        logger.debug(f"Account hash value retrieved: {self.account_hash_value}")
    
    def get_account_info(self) -> Dict:
        """
        Get account information including balance, equity, buying power, etc.
        
        Returns:
            dict: Account information or empty dict if unavailable
        """
        try:
            self._update_headers()
            
            if not self.account_hash_value:
                logger.error("Account hash value not set")
                return {}
            
            url = f"{self.base_url}/accounts/{self.account_hash_value}"
            response = requests.get(url, headers=self.headers)
            
            if response.status_code == 200:
                account_data = response.json()
                logger.debug("Account info retrieved successfully")
                return account_data
            else:
                logger.error(f"Failed to get account info: {response.status_code} - {response.text}")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return {}
    
    def get_positions(self) -> Optional[List[Dict]]:
        """
        Get current account positions.
        
        Returns:
            list: List of position dictionaries or empty list if no positions
            None: If there was an API error (to distinguish from "no positions")
        """
        try:
            self._update_headers()
            
            if not self.account_hash_value:
                logger.error("Account hash value not set")
                return None
            
            # Primary endpoint
            url = f"{self.base_url}/accounts/{self.account_hash_value}?fields=positions"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            logger.debug(f"get_positions API response: status={response.status_code}")
            
            if response.status_code == 200:
                account_data = response.json()
                securities_account = account_data.get('securitiesAccount', {})
                positions = securities_account.get('positions', [])
                
                # Filter out zero-quantity positions
                valid_positions = [
                    p for p in positions 
                    if (p.get('longQuantity', 0) != 0 or p.get('shortQuantity', 0) != 0)
                ]
                logger.debug(f"Found {len(valid_positions)} positions (from {len(positions)} total)")
                return valid_positions
            elif response.status_code == 404:
                logger.debug("No positions found (404)")
                return []
            else:
                logger.error(f"Failed to get positions: {response.status_code} - {response.text}")
                # Try fallback endpoint
                return self._get_positions_fallback()
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting positions: {e}")
            return self._get_positions_fallback()
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return None
    
    def _get_positions_fallback(self) -> Optional[List[Dict]]:
        """
        Fallback method to get positions using direct /positions endpoint.
        """
        try:
            url = f"{self.base_url}/accounts/{self.account_hash_value}/positions"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                positions_data = response.json()
                if isinstance(positions_data, list):
                    valid_positions = [
                        p for p in positions_data 
                        if (p.get('longQuantity', 0) != 0 or p.get('shortQuantity', 0) != 0)
                    ]
                    logger.info(f"Fallback endpoint found {len(valid_positions)} positions")
                    return valid_positions
                elif isinstance(positions_data, dict) and 'positions' in positions_data:
                    valid_positions = [
                        p for p in positions_data['positions'] 
                        if (p.get('longQuantity', 0) != 0 or p.get('shortQuantity', 0) != 0)
                    ]
                    logger.info(f"Fallback endpoint found {len(valid_positions)} positions")
                    return valid_positions
                else:
                    logger.warning(f"Fallback endpoint: Unexpected data format")
                    return []
            elif response.status_code == 404:
                logger.debug("Fallback endpoint: No positions found")
                return []
            else:
                logger.error(f"Fallback endpoint also failed: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Fallback endpoint error: {e}")
            return None
    
    def get_all_open_orders(self) -> List[Dict]:
        """
        Get all open/pending orders from the account.
        
        Returns:
            list: List of order dictionaries or empty list if unavailable
        """
        try:
            self._update_headers()
            
            if not self.account_hash_value:
                logger.error("Account hash value not set")
                return []
            
            # Schwab API requires fromEnteredTime and toEnteredTime parameters
            eastern = pytz.timezone('US/Eastern')
            now_eastern = datetime.now(eastern)
            start_of_today = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_today = now_eastern.replace(hour=23, minute=59, second=59, microsecond=999999)
            from_date = start_of_today.isoformat()
            to_date = end_of_today.isoformat()
            
            url = f"{self.base_url}/accounts/{self.account_hash_value}/orders"
            params = {
                'fromEnteredTime': from_date,
                'toEnteredTime': to_date
            }
            
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code == 200:
                orders_data = response.json()
                # Handle different response formats
                if isinstance(orders_data, list):
                    orders = orders_data
                elif isinstance(orders_data, dict):
                    # Sometimes API returns {'orders': [...]}
                    orders = orders_data.get('orders', [])
                    if not orders:
                        orders = orders_data.get('orderList', [])
                else:
                    orders = []
                
                # Filter to only open/pending orders (exclude FILLED, CANCELED, REJECTED, EXPIRED)
                open_statuses = ['WORKING', 'PENDING_ACTIVATION', 'QUEUED', 'ACCEPTED', 'AWAITING_PARENT_ORDER', 'PENDING']
                closed_statuses = ['FILLED', 'CANCELED', 'REJECTED', 'EXPIRED', 'DONE']
                
                open_orders = []
                for o in orders:
                    status = o.get('status', '').upper()
                    if status in open_statuses:
                        open_orders.append(o)
                    elif status not in closed_statuses:
                        # If status is unknown, include it to be safe
                        logger.warning(f"Unknown order status '{status}' for order {o.get('orderId')} - including in cancellation")
                        open_orders.append(o)
                
                logger.info(f"Found {len(open_orders)} open orders from {len(orders)} total orders")
                if len(open_orders) > 0:
                    logger.info(f"Open order statuses: {[o.get('status') for o in open_orders]}")
                return open_orders
            elif response.status_code == 404:
                logger.debug("No orders found (404)")
                return []
            else:
                logger.error(f"Failed to get orders: {response.status_code} - {response.text}")
                return []
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting open orders: {e}")
            return []
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []

