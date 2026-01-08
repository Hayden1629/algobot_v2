"""
Trade execution module for algobot_v2.
Executes trades using limit orders with optimal bid/ask pricing.
"""
from typing import List, Dict, Optional
from loguru import logger
from schwab.account.client import AccountClient
from schwab.market_data.client import MarketDataClient
from schwab.account.orders import OrderManager
from constants.parameters import USE_LIMIT_ORDERS, STOP_LOSS_PERCENT


class TradeExecutor:
    """
    Executes trades using limit orders with optimal pricing.
    Uses last price (primary) or bid/ask prices for limit order pricing.
    """
    
    def __init__(self, account_client: AccountClient, market_data_client: MarketDataClient, order_manager: OrderManager):
        """
        Initialize trade executor.
        
        Args:
            account_client: Schwab account client
            market_data_client: Schwab market data client
            order_manager: Order manager instance
        """
        self.account_client = account_client
        self.market_data_client = market_data_client
        self.order_manager = order_manager
        logger.info("TradeExecutor initialized")
    
    def get_bid_ask_prices(self, ticker: str) -> Optional[Dict[str, float]]:
        """
        Get bid and ask prices for a ticker.
        Uses last price as primary source since bid/ask may not be available.
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            dict: {'bid': float, 'ask': float} or None if unavailable
        """
        try:
            quote_data = self.market_data_client.get_quote_full(ticker)
            if not quote_data:
                logger.warning(f"Could not get quote for {ticker}")
                return None
            
            # Check nested 'quote' field first (primary structure in Schwab API)
            quote_field = quote_data.get('quote', {})
            if isinstance(quote_field, dict):
                # Try to get bid/ask from quote field
                bid_price = quote_field.get('bidPrice')
                ask_price = quote_field.get('askPrice')
                last_price = quote_field.get('lastPrice') or quote_field.get('regularMarketLastPrice')
                
                if bid_price is not None and ask_price is not None:
                    logger.debug(f"Using bid/ask from quote field for {ticker}: bid=${bid_price:.2f}, ask=${ask_price:.2f}")
                    return {
                        'bid': float(bid_price),
                        'ask': float(ask_price)
                    }
                
                # Use last price from quote field if bid/ask not available
                if last_price is not None:
                    logger.debug(f"Using last price from quote field for {ticker}: ${last_price:.2f}")
                    return {
                        'bid': float(last_price),
                        'ask': float(last_price)
                    }
            
            # Check nested 'regular' field
            regular_field = quote_data.get('regular', {})
            if isinstance(regular_field, dict):
                last_price = regular_field.get('regularMarketLastPrice')
                if last_price is not None:
                    logger.debug(f"Using last price from regular field for {ticker}: ${last_price:.2f}")
                    return {
                        'bid': float(last_price),
                        'ask': float(last_price)
                    }
            
            # Fallback to top-level fields
            last_price = (
                quote_data.get('lastPrice') or
                quote_data.get('regularMarketLastPrice') or
                quote_data.get('last') or
                quote_data.get('closePrice') or
                quote_data.get('regularMarketPrice')
            )
            
            if last_price is not None:
                logger.debug(f"Using last price (top-level) for {ticker}: ${last_price:.2f}")
                return {
                    'bid': float(last_price),
                    'ask': float(last_price)
                }
            
            # Fallback to top-level bid/ask if last price not available
            bid_price = (
                quote_data.get('bidPrice') or
                quote_data.get('bid')
            )
            ask_price = (
                quote_data.get('askPrice') or
                quote_data.get('ask')
            )
            
            if bid_price is not None and ask_price is not None:
                logger.debug(f"Using bid/ask (top-level) for {ticker}: bid=${bid_price:.2f}, ask=${ask_price:.2f}")
                return {
                    'bid': float(bid_price),
                    'ask': float(ask_price)
                }
            
            logger.warning(f"No price data available for {ticker}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting prices for {ticker}: {e}")
            return None
    
    def get_limit_price(self, ticker: str, direction: str) -> Optional[float]:
        """
        Get optimal limit price for a trade.
        Uses last price (or bid/ask if available) for limit orders.
        
        Args:
            ticker: Stock ticker symbol
            direction: 'LONG' or 'SHORT'
        
        Returns:
            float: Limit price, or None if unavailable
        """
        prices = self.get_bid_ask_prices(ticker)
        if not prices:
            return None
        
        direction_upper = direction.upper()
        
        if direction_upper == 'LONG':
            # For longs, use bid price (or last price if bid unavailable)
            limit_price = prices['bid']
            logger.debug(f"Long {ticker}: Using limit price ${limit_price:.2f}")
        elif direction_upper == 'SHORT':
            # For shorts, use ask price (or last price if ask unavailable)
            limit_price = prices['ask']
            logger.debug(f"Short {ticker}: Using limit price ${limit_price:.2f}")
        else:
            logger.error(f"Invalid direction: {direction}")
            return None
        
        return limit_price
    
    def execute_trade(self, sized_trade: Dict) -> Dict:
        """
        Execute a single trade using limit order.
        
        Args:
            sized_trade: Dict with 'ticker', 'direction', 'shares', 'price' keys
        
        Returns:
            dict: Execution result with 'success', 'order_id', 'ticker', 'direction', 'shares', 'price'
        """
        ticker = sized_trade.get('ticker', '').upper()
        direction = sized_trade.get('direction', '').upper()
        shares = sized_trade.get('shares', 0)
        expected_price = sized_trade.get('price', 0.0)
        
        if not ticker:
            logger.error("Trade missing ticker")
            return {'success': False, 'error': 'Missing ticker'}
        
        if direction not in ['LONG', 'SHORT']:
            logger.error(f"Invalid direction: {direction}")
            return {'success': False, 'error': f'Invalid direction: {direction}'}
        
        if shares <= 0:
            logger.error(f"Invalid share count: {shares}")
            return {'success': False, 'error': f'Invalid shares: {shares}'}
        
        # Get optimal limit price
        limit_price = self.get_limit_price(ticker, direction)
        if limit_price is None:
            logger.error(f"Could not get limit price for {ticker}")
            return {'success': False, 'error': 'Could not get limit price'}
        
        logger.info(f"Executing {direction} {ticker}: {shares} shares @ ${limit_price:.2f} limit")
        
        try:
            # Determine order instruction based on direction
            if direction == 'LONG':
                instruction = 'BUY'
            else:  # SHORT
                instruction = 'SELL_SHORT'
            
            # Create limit order
            if USE_LIMIT_ORDERS:
                result = self.order_manager.create_limit_order(
                    ticker=ticker,
                    instruction=instruction,
                    quantity=shares,
                    price=limit_price
                )
            else:
                # Fallback to market order if limit orders disabled
                logger.warning("Limit orders disabled, using market order")
                result = self.order_manager.create_market_order(
                    ticker=ticker,
                    instruction=instruction,
                    quantity=shares
                )
            
            if 'orderId' in result or 'success' in result:
                order_id = result.get('orderId', result.get('order_id', 'unknown'))
                logger.info(f"✓ Order placed: {direction} {ticker} {shares} shares @ ${limit_price:.2f} (Order ID: {order_id})")
                return {
                    'success': True,
                    'order_id': order_id,
                    'ticker': ticker,
                    'direction': direction,
                    'shares': shares,
                    'price': limit_price,
                    'expected_price': expected_price
                }
            else:
                error_msg = result.get('error', result.get('message', 'Unknown error'))
                logger.error(f"✗ Order failed for {ticker}: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'ticker': ticker,
                    'direction': direction
                }
                
        except Exception as e:
            logger.error(f"Error executing trade for {ticker}: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e),
                'ticker': ticker,
                'direction': direction
            }
    
    def execute_trades(self, sized_trades: List[Dict]) -> List[Dict]:
        """
        Execute multiple trades, check fills, and retry if needed.
        
        Args:
            sized_trades: List of sized trade dicts with 'ticker', 'direction', 'shares', 'price'
        
        Returns:
            list: List of execution results
        """
        logger.info("=" * 60)
        logger.info("Trade Execution")
        logger.info("=" * 60)
        logger.info(f"Executing {len(sized_trades)} trade(s)")
        
        execution_results = []
        pending_orders = []
        
        # Phase 1: Place all orders
        for i, sized_trade in enumerate(sized_trades, 1):
            ticker = sized_trade.get('ticker', 'Unknown')
            logger.info(f"[{i}/{len(sized_trades)}] Executing trade for {ticker}...")
            
            result = self.execute_trade(sized_trade)
            execution_results.append(result)
            
            # Track pending orders for fill checking
            if result.get('success') and result.get('order_id'):
                pending_orders.append({
                    'result': result,
                    'sized_trade': sized_trade,
                    'attempt': 1
                })
            
        # Phase 2: Check order fills and retry if needed
        if pending_orders:
            logger.info(f"Checking {len(pending_orders)} order(s) for fills...")
            import time
            time.sleep(2)  # Wait a moment for orders to process
            
            # Quick initial check - some orders may fill immediately
            filled_immediately = []
            for pending in pending_orders:
                order_id = pending['result'].get('order_id')
                ticker = pending['result'].get('ticker')
                
                order_status = self.order_manager.get_order_status(order_id)
                status = order_status.get('status', '').upper()
                
                if status == 'FILLED':
                    logger.info(f"✓ Order filled immediately for {ticker} (Order ID: {order_id})")
                    pending['result']['filled'] = True
                    filled_immediately.append(pending)
            
            # Remove filled orders from pending list
            for filled in filled_immediately:
                pending_orders.remove(filled)
            
            max_retries = 3
            retry_delay = 3  # seconds
            
            for attempt in range(max_retries):
                still_pending = []
                
                for pending in pending_orders:
                    order_id = pending['result'].get('order_id')
                    ticker = pending['result'].get('ticker')
                    sized_trade = pending['sized_trade']
                    
                    # Check order status
                    order_status = self.order_manager.get_order_status(order_id)
                    status = order_status.get('status', '').upper()
                    
                    if status == 'FILLED':
                        logger.info(f"✓ Order filled for {ticker} (Order ID: {order_id})")
                        # Update result to indicate fill
                        pending['result']['filled'] = True
                        # Get actual fill price if available
                        if 'averageFillPrice' in order_status:
                            pending['result']['price'] = float(order_status['averageFillPrice'])
                        elif 'price' in order_status:
                            pending['result']['price'] = float(order_status['price'])
                    elif status in ['REJECTED', 'CANCELED', 'EXPIRED']:
                        logger.warning(f"Order {status} for {ticker}, will retry")
                        still_pending.append(pending)
                    elif status in ['WORKING', 'PENDING_ACTIVATION', 'QUEUED', 'ACCEPTED']:
                        # Still working
                        if attempt < max_retries - 1:
                            still_pending.append(pending)
                        else:
                            # Last attempt - cancel and retry with new price
                            logger.warning(f"Order still {status} for {ticker} after {max_retries} checks, canceling and retrying")
                            self.order_manager.cancel_order(order_id)
                            still_pending.append(pending)
                    else:
                        logger.warning(f"Unknown order status '{status}' for {ticker}, will retry")
                        still_pending.append(pending)
                
                if not still_pending:
                    break
                
                if attempt < max_retries - 1:
                    logger.info(f"Waiting {retry_delay}s before checking {len(still_pending)} pending order(s) again...")
                    time.sleep(retry_delay)
                    
                    # Retry unfilled orders with new prices
                    filled_during_retry = []
                    for pending in still_pending:
                        ticker = pending['result'].get('ticker')
                        sized_trade = pending['sized_trade']
                        old_order_id = pending['result'].get('order_id')
                        
                        # Double-check order status before retrying
                        if old_order_id:
                            order_status = self.order_manager.get_order_status(old_order_id)
                            status = order_status.get('status', '').upper()
                            
                            if status == 'FILLED':
                                logger.info(f"✓ Order filled for {ticker} (Order ID: {old_order_id})")
                                pending['result']['filled'] = True
                                filled_during_retry.append(pending)
                                continue
                        
                        pending['attempt'] += 1
                        logger.info(f"Retrying {ticker} (attempt {pending['attempt']})...")
                        
                        # Get new limit price
                        direction = sized_trade.get('direction', '').upper()
                        limit_price = self.get_limit_price(ticker, direction)
                        
                        if limit_price is None:
                            logger.warning(f"Could not get new price for {ticker}, using market order")
                            # Cancel old order first
                            if old_order_id:
                                cancel_result = self.order_manager.cancel_order(old_order_id)
                                # Check if cancel failed because order was already filled
                                if cancel_result.get('error'):
                                    error_msg = cancel_result.get('error', '').upper()
                                    if 'FILLED' in error_msg and ('CANNOT' in error_msg or 'CANNOT BE CANCELED' in error_msg):
                                        logger.info(f"✓ Order for {ticker} was filled (cancel failed: order already filled)")
                                        pending['result']['filled'] = True
                                        filled_during_retry.append(pending)
                                        continue
                            
                            result = self.order_manager.create_market_order(
                                ticker,
                                'BUY' if direction == 'LONG' else 'SELL_SHORT',
                                sized_trade.get('shares', 0)
                            )
                        else:
                            # Cancel old order if still working
                            if old_order_id:
                                cancel_result = self.order_manager.cancel_order(old_order_id)
                                
                                # Check if cancel failed because order was already filled
                                if cancel_result.get('error'):
                                    error_msg = cancel_result.get('error', '').upper()
                                    if 'FILLED' in error_msg and ('CANNOT' in error_msg or 'CANNOT BE CANCELED' in error_msg):
                                        # Order was filled - treat as success
                                        logger.info(f"✓ Order for {ticker} was filled (cancel failed: order already filled)")
                                        pending['result']['filled'] = True
                                        filled_during_retry.append(pending)
                                        # Don't place new order - this one is done
                                        continue
                            
                            # Place new limit order
                            result = self.order_manager.create_limit_order(
                                ticker,
                                'BUY' if direction == 'LONG' else 'SELL_SHORT',
                                sized_trade.get('shares', 0),
                                limit_price
                            )
                        
                        if 'orderId' in result or 'success' in result:
                            new_order_id = result.get('orderId', result.get('order_id', 'unknown'))
                            pending['result']['order_id'] = new_order_id
                            logger.info(f"✓ Retry order placed for {ticker} (Order ID: {new_order_id})")
                        else:
                            logger.error(f"✗ Retry failed for {ticker}: {result.get('error', 'Unknown error')}")
                            # Mark as failed
                            pending['result']['success'] = False
                            pending['result']['error'] = result.get('error', 'Retry failed')
                    
                    # Remove filled orders from still_pending
                    for filled in filled_during_retry:
                        still_pending.remove(filled)
                        
                        if 'orderId' in result or 'success' in result:
                            new_order_id = result.get('orderId', result.get('order_id', 'unknown'))
                            pending['result']['order_id'] = new_order_id
                            logger.info(f"✓ Retry order placed for {ticker} (Order ID: {new_order_id})")
                        else:
                            logger.error(f"✗ Retry failed for {ticker}: {result.get('error', 'Unknown error')}")
                            # Mark as failed
                            pending['result']['success'] = False
                            pending['result']['error'] = result.get('error', 'Retry failed')
            
            # Final check for any remaining unfilled orders
            final_filled = []
            for pending in still_pending:
                order_id = pending['result'].get('order_id')
                ticker = pending['result'].get('ticker')
                
                # Final status check
                order_status = self.order_manager.get_order_status(order_id)
                status = order_status.get('status', '').upper()
                
                if status == 'FILLED':
                    logger.info(f"✓ Order filled for {ticker} (Order ID: {order_id})")
                    pending['result']['filled'] = True
                    final_filled.append(pending)
                    continue
                
                # Try to cancel before placing market order
                cancel_result = self.order_manager.cancel_order(order_id)
                
                # Check if cancel failed because order was already filled
                if cancel_result.get('error'):
                    error_msg = cancel_result.get('error', '').upper()
                    if 'FILLED' in error_msg and ('CANNOT' in error_msg or 'CANNOT BE CANCELED' in error_msg):
                        logger.info(f"✓ Order for {ticker} was filled (cancel failed: order already filled)")
                        pending['result']['filled'] = True
                        final_filled.append(pending)
                        continue
                
                # Order not filled - use market order as final fallback
                logger.warning(f"Order for {ticker} not filled after all retries (status: {status}), using market order")
                sized_trade = pending['sized_trade']
                direction = sized_trade.get('direction', '').upper()
                result = self.order_manager.create_market_order(
                    ticker,
                    'BUY' if direction == 'LONG' else 'SELL_SHORT',
                    sized_trade.get('shares', 0)
                )
                
                if 'orderId' in result or 'success' in result:
                    logger.info(f"✓ Market order placed for {ticker}")
                    pending['result']['filled'] = True
                    pending['result']['order_id'] = result.get('orderId', result.get('order_id', 'unknown'))
                else:
                    logger.error(f"✗ Market order failed for {ticker}: {result.get('error', 'Unknown error')}")
                    pending['result']['success'] = False
            
            # Remove filled orders
            for filled in final_filled:
                still_pending.remove(filled)
        
        # Update execution results with fill status
        filled_count = sum(1 for r in execution_results if r.get('filled', False) or r.get('success', False))
        failed_count = len(execution_results) - filled_count
        
        logger.info("=" * 60)
        logger.info(f"Trade Execution Complete")
        logger.info(f"Filled: {filled_count}, Failed: {failed_count}")
        logger.info("=" * 60)
        
        return execution_results

