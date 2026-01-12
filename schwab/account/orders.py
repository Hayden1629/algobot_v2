"""
Order management operations for Schwab Trader API.
Handles order creation, cancellation, and status checking.
"""
import requests
import time
from typing import Dict, Optional
from loguru import logger
from schwab.account.client import AccountClient
from schwab.market_data.client import MarketDataClient
from constants.parameters import (
    USE_LIMIT_ORDERS,
    LIMIT_ORDER_TIMEOUT_SECONDS,
    LIMIT_ORDER_MAX_ATTEMPTS,
    LIMIT_ORDER_PRICE_OFFSET_PERCENT,
    LIMIT_ORDER_ADJUSTMENT_PERCENT,
    SHOW_ORDER_OUTPUT
)


class OrderManager:
    """
    Manages order operations for Schwab Trader API.
    Handles order creation, cancellation, and status checking.
    """
    
    def __init__(self, account_client: AccountClient, market_data_client: MarketDataClient):
        """
        Initialize order manager.
        
        Args:
            account_client: Account client instance
            market_data_client: Market data client instance
        """
        self.account_client = account_client
        self.market_data_client = market_data_client
    
    def create_order(self, order_payload: Dict, max_retries: int = 5, skip_delays: bool = False) -> Dict:
        """
        Create an order via Schwab API.
        Includes retry logic for failed requests.
        
        Args:
            order_payload: Order payload dictionary
            max_retries: Maximum number of retry attempts
            skip_delays: If True, skip delays on retries (for urgent orders like stop losses)
        
        Returns:
            dict: API response with order details
        """
        self.account_client._update_headers()
        
        # Add Content-Type header for POST requests
        headers = self.account_client.headers.copy()
        headers["Content-Type"] = "application/json"
        
        url = f"{self.account_client.base_url}/accounts/{self.account_client.account_hash_value}/orders"
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=order_payload,
                    timeout=10
                )
                
                if response.status_code in [200, 201]:
                    response_data = response.json() if response.text else {}
                    
                    # Check for order ID in response headers (Location header)
                    if 'Location' in response.headers:
                        location = response.headers['Location']
                        order_id = location.split('/')[-1]
                        response_data['orderId'] = order_id
                    
                    if SHOW_ORDER_OUTPUT:
                        logger.info(f"Order created successfully (Status {response.status_code}, Order ID: {response_data.get('orderId', 'N/A')})")
                    return response_data
                elif response.status_code == 429:
                    # Rate limited - retry without delay
                    if attempt < max_retries - 1:
                        logger.warning(f"Rate limited (429) creating order (attempt {attempt + 1}/{max_retries}), retrying immediately...")
                        self.account_client._update_headers()
                        headers = self.account_client.headers.copy()
                        headers["Content-Type"] = "application/json"
                        continue
                    else:
                        error_msg = f"Failed to create order: 429 Too Many Requests (after {max_retries} attempts)"
                        logger.error(error_msg)
                        return {'error': error_msg, 'status_code': 429}
                else:
                    error_msg = f"Failed to create order: {response.status_code}"
                    if response.text:
                        error_msg += f" - {response.text}"
                    logger.error(error_msg)
                    return {'error': error_msg, 'status_code': response.status_code}
                    
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries - 1:
                    if skip_delays:
                        logger.warning(f"Connection error creating order (attempt {attempt + 1}/{max_retries}), retrying immediately (no delay)...")
                    else:
                        wait_time = 2.0 * (2 ** attempt)
                        logger.warning(f"Connection error creating order (attempt {attempt + 1}/{max_retries}), waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                    self.account_client._update_headers()
                    headers = self.account_client.headers.copy()
                    headers["Content-Type"] = "application/json"
                    continue
                else:
                    logger.error(f"Error creating order after {max_retries} attempts: {e}")
                    return {'error': str(e)}
            except Exception as e:
                logger.error(f"Error creating order: {e}")
                return {'error': str(e)}
        
        return {'error': f'Failed after {max_retries} attempts'}
    
    def cancel_order(self, order_id: str) -> Dict:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            dict: API response
        """
        self.account_client._update_headers()
        
        url = f"{self.account_client.base_url}/accounts/{self.account_client.account_hash_value}/orders/{order_id}"
        
        try:
            response = requests.delete(url, headers=self.account_client.headers, timeout=10)
            
            if response.status_code in [200, 204]:
                logger.info(f"Order {order_id} cancelled successfully")
                return {'success': True}
            else:
                # Check if order is already canceled - this is fine, treat as success
                response_text = response.text if response.text else ""
                if "CANCELED cannot be canceled" in response_text or "already canceled" in response_text.lower():
                    logger.debug(f"Order {order_id} was already canceled (status: CANCELED)")
                    return {'success': True, 'already_canceled': True}
                
                error_msg = f"Failed to cancel order {order_id}: {response.status_code}"
                if response_text:
                    error_msg += f" - {response_text}"
                logger.error(error_msg)
                return {'error': error_msg, 'status_code': response.status_code}
                
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return {'error': str(e)}
    
    def create_market_order(self, ticker: str, instruction: str, quantity: int) -> Dict:
        """
        Create a market order.
        
        Args:
            ticker: Stock ticker symbol
            instruction: Order instruction ('BUY', 'SELL', 'SELL_SHORT', 'BUY_TO_COVER')
            quantity: Number of shares
        
        Returns:
            dict: API response with order details
        """
        order_payload = {
            "orderType": "MARKET",
            "session": "NORMAL",
            "duration": "DAY",
            "orderStrategyType": "SINGLE",
            "orderLegCollection": [{
                "instruction": instruction.upper(),
                "quantity": int(quantity),
                "instrument": {
                    "symbol": ticker.upper(),
                    "assetType": "EQUITY"
                }
            }]
        }
        
        logger.info(f"Creating market order: {ticker} {instruction} {quantity} shares")
        return self.create_order(order_payload)
    
    def create_limit_order(self, ticker: str, instruction: str, quantity: int, price: float) -> Dict:
        """
        Create a limit order.
        
        Args:
            ticker: Stock ticker symbol
            instruction: Order instruction ('BUY', 'SELL', 'SELL_SHORT', 'BUY_TO_COVER')
            quantity: Number of shares
            price: Limit price
        
        Returns:
            dict: API response with order details
        """
        order_payload = {
            "orderType": "LIMIT",
            "price": str(round(price, 4) if price < 1.0 else round(price, 2)),
            "session": "NORMAL",
            "duration": "DAY",
            "orderStrategyType": "SINGLE",
            "orderLegCollection": [{
                "instruction": instruction.upper(),
                "quantity": int(quantity),
                "instrument": {
                    "symbol": ticker.upper(),
                    "assetType": "EQUITY"
                }
            }]
        }
        
        if SHOW_ORDER_OUTPUT:
            logger.info(f"Creating limit order: {ticker} {instruction} {quantity} shares @ ${price:.4f}")
        return self.create_order(order_payload)
    
    def get_order_status(self, order_id: str) -> Dict:
        """
        Get order status and details.
        
        Args:
            order_id: Order ID to check
        
        Returns:
            dict: Order details including status, or error dict
        """
        self.account_client._update_headers()
        
        url = f"{self.account_client.base_url}/accounts/{self.account_client.account_hash_value}/orders/{order_id}"
        
        try:
            response = requests.get(url, headers=self.account_client.headers, timeout=10)
            
            if response.status_code == 200:
                order_data = response.json()
                return order_data
            elif response.status_code == 404:
                logger.warning(f"Order {order_id} not found (404)")
                return {'error': 'Order not found', 'status_code': 404}
            else:
                error_msg = f"Failed to get order status {order_id}: {response.status_code}"
                if response.text:
                    error_msg += f" - {response.text}"
                logger.error(error_msg)
                return {'error': error_msg, 'status_code': response.status_code}
                
        except Exception as e:
            logger.error(f"Error getting order status {order_id}: {e}")
            return {'error': str(e)}
    
    def create_stop_loss_order(self, ticker: str, instruction: str, quantity: int, 
                               entry_price: float, stop_loss_percent: float) -> Dict:
        """
        Create a stop loss order.
        
        Args:
            ticker: Stock ticker symbol
            instruction: Order instruction ('SELL' for LONG, 'BUY_TO_COVER' for SHORT)
            quantity: Number of shares
            entry_price: Entry price of the position
            stop_loss_percent: Stop loss percentage (e.g., 0.2 for 0.2%)
        
        Returns:
            dict: API response with order details
        """
        # Calculate stop loss price based on entry price
        if instruction.upper() in ['SELL', 'SELL_SHORT']:
            # For LONG positions: stop loss is below entry price
            stop_price = entry_price * (1 - stop_loss_percent / 100)
        elif instruction.upper() in ['BUY_TO_COVER', 'BUY']:
            # For SHORT positions: stop loss is above entry price
            stop_price = entry_price * (1 + stop_loss_percent / 100)
        else:
            logger.error(f"Invalid instruction for stop loss: {instruction}")
            return {'error': f'Invalid instruction: {instruction}'}
        
        # Get current bid/ask to validate stop price meets Schwab requirements
        # Schwab requires:
        # - SELL stop orders: stop price must be BELOW current bid
        # - BUY stop orders: stop price must be ABOVE current ask
        quote_data = self.market_data_client.get_quote_full(ticker)
        if quote_data:
            quote_field = quote_data.get('quote', {})
            if isinstance(quote_field, dict):
                bid_price = quote_field.get('bidPrice')
                ask_price = quote_field.get('askPrice')
                
                if bid_price is not None and ask_price is not None:
                    bid_price = float(bid_price)
                    ask_price = float(ask_price)
                    
                    if instruction.upper() in ['SELL', 'SELL_SHORT']:
                        # SELL stop: must be below bid
                        if stop_price >= bid_price:
                            # Adjust stop to be below bid (use bid - $0.01 minimum)
                            stop_price = bid_price - 0.01
                            if SHOW_ORDER_OUTPUT:
                                logger.warning(f"Adjusted stop price for {ticker} SELL stop: ${stop_price:.2f} (was above bid ${bid_price:.2f})")
                    elif instruction.upper() in ['BUY_TO_COVER', 'BUY']:
                        # BUY stop: must be above ask
                        if stop_price <= ask_price:
                            # Adjust stop to be above ask (use ask + $0.01 minimum)
                            stop_price = ask_price + 0.01
                            if SHOW_ORDER_OUTPUT:
                                logger.warning(f"Adjusted stop price for {ticker} BUY stop: ${stop_price:.2f} (was below ask ${ask_price:.2f})")
        
        # Round to appropriate decimal places (Schwab API requirement)
        if stop_price >= 1.0:
            stop_price = round(stop_price, 2)
        else:
            stop_price = round(stop_price, 4)
        
        order_payload = {
            "orderType": "STOP",
            "stopPrice": str(stop_price),
            "session": "NORMAL",
            "duration": "DAY",
            "orderStrategyType": "SINGLE",
            "orderLegCollection": [{
                "instruction": instruction.upper(),
                "quantity": int(quantity),
                "instrument": {
                    "symbol": ticker.upper(),
                    "assetType": "EQUITY"
                }
            }]
        }
        
        if SHOW_ORDER_OUTPUT:
            logger.info(f"Creating stop loss order: {ticker} {instruction} {quantity} shares @ ${stop_price:.4f} stop (entry: ${entry_price:.4f}, {stop_loss_percent}% loss)")
        return self.create_order(order_payload, skip_delays=True)

