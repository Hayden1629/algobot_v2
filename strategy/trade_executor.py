"""
Trade execution module for algobot_v2.
Executes trades using limit orders with optimal bid/ask pricing.
"""
from typing import List, Dict, Optional
from loguru import logger
from schwab.account.client import AccountClient
from schwab.market_data.client import MarketDataClient
from schwab.account.orders import OrderManager
from constants.parameters import USE_LIMIT_ORDERS


class TradeExecutor:
    """
    Executes trades using limit orders with optimal pricing.
    Uses bid price for longs, ask price for shorts.
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
            
            bid_price = quote_data.get('bidPrice')
            ask_price = quote_data.get('askPrice')
            
            if bid_price is None or ask_price is None:
                logger.warning(f"Missing bid/ask for {ticker}: bid={bid_price}, ask={ask_price}")
                # Fallback to last price if available
                last_price = quote_data.get('lastPrice')
                if last_price:
                    logger.info(f"Using last price as fallback for {ticker}: ${last_price:.2f}")
                    return {'bid': float(last_price), 'ask': float(last_price)}
                return None
            
            return {
                'bid': float(bid_price),
                'ask': float(ask_price)
            }
            
        except Exception as e:
            logger.error(f"Error getting bid/ask for {ticker}: {e}")
            return None
    
    def get_limit_price(self, ticker: str, direction: str) -> Optional[float]:
        """
        Get optimal limit price for a trade.
        Uses bid price for longs, ask price for shorts.
        
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
            # For longs, use bid price (what we're willing to pay)
            limit_price = prices['bid']
            logger.debug(f"Long {ticker}: Using bid price ${limit_price:.2f}")
        elif direction_upper == 'SHORT':
            # For shorts, use ask price (what we're willing to sell at)
            limit_price = prices['ask']
            logger.debug(f"Short {ticker}: Using ask price ${limit_price:.2f}")
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
        Execute multiple trades.
        
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
        
        for i, sized_trade in enumerate(sized_trades, 1):
            ticker = sized_trade.get('ticker', 'Unknown')
            logger.info(f"[{i}/{len(sized_trades)}] Executing trade for {ticker}...")
            
            result = self.execute_trade(sized_trade)
            execution_results.append(result)
            
            # Small delay between orders to avoid rate limiting
            if i < len(sized_trades):
                import time
                time.sleep(0.5)
        
        # Summary
        successful = sum(1 for r in execution_results if r.get('success', False))
        failed = len(execution_results) - successful
        
        logger.info("=" * 60)
        logger.info(f"Trade Execution Complete")
        logger.info(f"Successful: {successful}, Failed: {failed}")
        logger.info("=" * 60)
        
        return execution_results

