"""
Rolling strategy implementation for algobot_v2.

This strategy:
1. Collects tickers from MOST
2. Sorts by prob_up (thresholds in parameters)
3. Creates positions that fulfill prob_up requirements
4. Immediately runs PRT again
5. Maintains rolling positions (not batch-based)
6. Includes open positions in the PRT list
7. Closes trades that don't match PRT predictions
8. Opens new positions if they fit criteria
"""
from typing import List, Dict, Optional, Tuple
from loguru import logger
from core.controller import GodelTerminalController
from commands.most_command import MOSTCommand
from commands.prt_command import PRTCommand
from schwab.account.client import AccountClient
from schwab.market_data.client import MarketDataClient
from constants.parameters import (
    PROB_UP_MIN_LONG,
    PROB_UP_MIN_SHORT,
    PROB_UP_EDGE_THRESHOLD,
    MOST_TAB,
    MOST_LIMIT,
    PRT_MAX_TICKERS,
    MAX_POSITIONS,
    STOP_LOSS_PERCENT,
    DO_OPPOSITE,
    SHOW_ORDER_OUTPUT
)
from constants.blacklist import filter_blacklisted_tickers
from strategy.trade_tracker import TradeTracker
from strategy.position_sizing import PositionSizer
from strategy.trade_executor import TradeExecutor
from database.db_manager import DatabaseManager


class RollingStrategy:
    """
    Rolling strategy that continuously maintains positions based on PRT predictions.
    """
    
    def __init__(self, controller: GodelTerminalController, 
                 account_client: AccountClient,
                 market_data_client: MarketDataClient,
                 trade_tracker: TradeTracker,
                 order_manager=None):
        """
        Initialize rolling strategy.
        
        Args:
            controller: Godel Terminal controller
            account_client: Schwab account client
            market_data_client: Schwab market data client
            trade_tracker: Trade time tracker
            order_manager: Order manager for trade execution
        """
        self.controller = controller
        self.account_client = account_client
        self.market_data_client = market_data_client
        self.trade_tracker = trade_tracker
        self.order_manager = order_manager
        
        # Initialize position sizing and trade execution modules
        if order_manager:
            self.position_sizer = PositionSizer(account_client, market_data_client)
            self.trade_executor = TradeExecutor(account_client, market_data_client, order_manager)
        else:
            self.position_sizer = None
            self.trade_executor = None
            logger.warning("OrderManager not provided - position sizing and trade execution disabled")
        
        # Initialize database manager for trade tracking
        try:
            self.db_manager = DatabaseManager()
            if self.db_manager.is_available():
                logger.debug("Database manager initialized - trades will be sent to dashboard")
            else:
                logger.debug("Database not available - trades will only be logged locally")
                self.db_manager = None
        except Exception as e:
            logger.warning(f"Could not initialize database manager: {e} - trades will only be logged locally")
            self.db_manager = None
        
        # Register commands
        self.controller.register_command("MOST", MOSTCommand)
        self.controller.register_command("PRT", PRTCommand)
    
    def _close_trade_with_db_update(self, ticker: str, order_id: Optional[str] = None) -> None:
        """
        Close a trade and update it in the database.
        CRITICAL: Always updates database, even if exit price retrieval fails (uses fallback).
        
        Args:
            ticker: Stock ticker symbol
            order_id: Optional order ID to get fill price from
        """
        exit_price = None
        
        # Try to get exit price from order status if order_id provided
        if order_id and self.order_manager:
            try:
                order_status = self.order_manager.get_order_status(order_id)
                
                # Check for error in response
                if 'error' in order_status:
                    logger.debug(f"Error getting order status for {order_id}: {order_status.get('error')}")
                else:
                    # Try top-level averageFillPrice first
                    if 'averageFillPrice' in order_status:
                        exit_price = float(order_status['averageFillPrice'])
                        logger.debug(f"Got exit price from top-level averageFillPrice for {ticker}: ${exit_price:.2f}")
                    # Try orderLegCollection (for stop loss orders, fill price is often here)
                    elif 'orderLegCollection' in order_status and len(order_status['orderLegCollection']) > 0:
                        leg = order_status['orderLegCollection'][0]
                        # Check executionDetails first (most accurate for filled orders)
                        if 'executionDetails' in leg and leg['executionDetails']:
                            executions = leg['executionDetails']
                            if executions:
                                # Calculate average fill price from all executions
                                total_price = 0
                                total_quantity = 0
                                for execution in executions:
                                    if 'price' in execution and 'quantity' in execution:
                                        total_price += execution['price'] * execution['quantity']
                                        total_quantity += execution['quantity']
                                if total_quantity > 0:
                                    exit_price = total_price / total_quantity
                                    logger.debug(f"Got exit price from executionDetails for {ticker}: ${exit_price:.2f}")
                        # Fallback to other leg fields
                        if exit_price is None:
                            if 'averageFillPrice' in leg:
                                exit_price = float(leg['averageFillPrice'])
                                logger.debug(f"Got exit price from orderLegCollection averageFillPrice for {ticker}: ${exit_price:.2f}")
                            elif 'averagePrice' in leg:
                                exit_price = float(leg['averagePrice'])
                                logger.debug(f"Got exit price from orderLegCollection averagePrice for {ticker}: ${exit_price:.2f}")
                            elif 'filledPrice' in leg:
                                exit_price = float(leg['filledPrice'])
                                logger.debug(f"Got exit price from orderLegCollection filledPrice for {ticker}: ${exit_price:.2f}")
                            elif 'price' in leg:
                                exit_price = float(leg['price'])
                                logger.debug(f"Got exit price from orderLegCollection price for {ticker}: ${exit_price:.2f}")
                    # Try top-level price
                    elif 'price' in order_status:
                        exit_price = float(order_status['price'])
                        logger.debug(f"Got exit price from top-level price for {ticker}: ${exit_price:.2f}")
                    else:
                        # Log available fields for debugging
                        available_fields = list(order_status.keys())
                        logger.warning(f"⚠️  Order status for {order_id} ({ticker}) does not contain fill price fields. Available fields: {available_fields}")
                        # Check if orderLegCollection exists but is empty
                        if 'orderLegCollection' in order_status:
                            logger.warning(f"   orderLegCollection exists but is empty or doesn't have fill price")
                        # Log the full order status for debugging (truncated)
                        logger.debug(f"   Order status sample: {str(order_status)[:500]}")
            except Exception as e:
                logger.debug(f"Could not get exit price from order {order_id} for {ticker}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
        
        # Fallback 1: get current quote
        if exit_price is None and self.market_data_client:
            try:
                quote = self.market_data_client.get_quote(ticker)
                if quote:
                    exit_price = quote.get('lastPrice') or quote.get('last')
            except Exception as e:
                logger.debug(f"Could not get quote for {ticker}: {e}")
        
        # Fallback 2: get entry price from database as last resort
        if exit_price is None and self.db_manager and self.db_manager.is_available():
            try:
                cursor = self.db_manager.connection.cursor()
                find_query = "SELECT entry_price FROM trades WHERE ticker = %s AND is_closed = FALSE ORDER BY time_placed DESC LIMIT 1"
                cursor.execute(find_query, (ticker.upper(),))
                trade = cursor.fetchone()
                cursor.close()
                if trade and trade[0]:
                    exit_price = float(trade[0])
                    logger.warning(f"⚠️  Using entry price as fallback exit price for {ticker} (could not get actual exit price)")
            except Exception as e:
                logger.debug(f"Could not get entry price from database for {ticker}: {e}")
        
        # CRITICAL: Always update trade in database, even if exit_price is None
        # This ensures the trade is marked as closed in all scenarios
        if self.db_manager and self.db_manager.is_available():
            try:
                from datetime import datetime
                import pytz
                
                # If we still don't have an exit price, use 0.0 as absolute last resort
                # This ensures the trade is marked as closed, even if we can't get the price
                if exit_price is None:
                    exit_price = 0.0
                    logger.error(f"❌ CRITICAL: Could not get exit price for {ticker} - using 0.0 as fallback. Trade will be marked as closed but P&L may be incorrect.")
                
                self.db_manager.update_trade_on_close(
                    ticker,
                    exit_price,
                    datetime.now(pytz.UTC)
                )
                logger.info(f"✓ Updated trade {ticker} in database (exit price: ${exit_price:.2f})")
            except Exception as e:
                logger.error(f"❌ CRITICAL: Could not update trade in database for {ticker}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            logger.warning(f"⚠️  Database not available - could not update trade {ticker} in database")
        
        # Remove from tracker
        self.trade_tracker.remove_trade(ticker)
    
    def _check_and_update_stop_losses(self) -> int:
        """
        Check for stop loss orders that have been filled (triggered) and update database.
        This should be called after closing positions that no longer meet criteria
        and before placing new orders.
        
        Returns:
            int: Number of stop losses that were triggered and updated
        """
        if not self.order_manager or not self.account_client:
            return 0
        
        triggered_count = 0
        
        try:
            # Get current positions to check which ones still exist
            current_positions = self.account_client.get_positions() or []
            current_position_tickers = {
                pos.get('instrument', {}).get('symbol', '').upper()
                for pos in current_positions
            }
            
            # Get all tracked stop loss order IDs
            tracked_trades = self.trade_tracker.trades.copy()  # Copy to avoid modification during iteration
            stop_loss_order_ids = {}
            
            for ticker, trade_info in tracked_trades.items():
                stop_loss_order_id = trade_info.get('stop_loss_order_id')
                if stop_loss_order_id:
                    stop_loss_order_ids[stop_loss_order_id] = ticker
            
            if not stop_loss_order_ids:
                return 0
            
            logger.info(f"Checking {len(stop_loss_order_ids)} tracked stop loss orders for fills...")
            
            # Check each tracked stop loss order
            for order_id, ticker in stop_loss_order_ids.items():
                try:
                    # First check if position still exists
                    # If position doesn't exist but we're tracking it, stop loss likely filled
                    if ticker not in current_position_tickers:
                        logger.warning(f"⚠️  Stop loss likely triggered for {ticker} (position closed, checking order status...)")
                        # Verify by checking order status
                        try:
                            order_status = self.order_manager.get_order_status(order_id)
                            status = order_status.get('status', '').upper()
                            order_type = order_status.get('orderType', '').upper()
                            
                            if order_type == 'STOP' and status == 'FILLED':
                                logger.warning(f"⚠️  Stop loss confirmed triggered for {ticker} (Order ID: {order_id})")
                                self._close_trade_with_db_update(ticker, order_id)
                                triggered_count += 1
                            else:
                                # Position closed but stop loss not filled - might have been manually closed
                                logger.debug(f"Position {ticker} closed but stop loss status is {status}")
                        except Exception as e:
                            # Can't get order status, but position is closed - assume stop loss filled
                            logger.warning(f"⚠️  Stop loss likely triggered for {ticker} (position closed, order status unavailable: {e})")
                            self._close_trade_with_db_update(ticker, order_id)
                            triggered_count += 1
                        continue
                    
                    # Position still exists, check order status
                    order_status = self.order_manager.get_order_status(order_id)
                    status = order_status.get('status', '').upper()
                    order_type = order_status.get('orderType', '').upper()
                    
                    # Only process STOP orders
                    if order_type != 'STOP':
                        continue
                    
                    if status == 'FILLED':
                        logger.warning(f"⚠️  Stop loss triggered for {ticker} (Order ID: {order_id})")
                        # Update database with the filled stop loss order
                        self._close_trade_with_db_update(ticker, order_id)
                        triggered_count += 1
                        
                    elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                        # Stop loss was canceled/rejected/expired - log but don't update
                        logger.debug(f"Stop loss order for {ticker} was {status} (Order ID: {order_id})")
                        # Don't remove from tracker - position still exists, just stop loss was canceled
                        
                except Exception as e:
                    logger.debug(f"Error checking stop loss order {order_id} for {ticker}: {e}")
                    # If we can't get order status, check if position still exists
                    if ticker not in current_position_tickers:
                        # Position doesn't exist, stop loss likely filled
                        logger.warning(f"⚠️  Stop loss likely triggered for {ticker} (position closed, order check failed)")
                        self._close_trade_with_db_update(ticker, order_id)
                        triggered_count += 1
            
            if triggered_count > 0:
                logger.info(f"✓ Updated {triggered_count} trade(s) in database due to stop loss triggers")
            
        except Exception as e:
            logger.error(f"Error checking stop losses: {e}")
            import traceback
            traceback.print_exc()
        
        return triggered_count
    
    def _update_trailing_stop_losses(self) -> int:
        """
        Update stop losses for positions that are up 1% or more from entry.
        Moves stop loss to lock in gains by placing it at current price - stop loss percent.
        Only updates again if price has moved up another 1% from the last update price.
        
        Returns:
            int: Number of stop losses that were updated
        """
        if not self.order_manager or not self.account_client or not self.market_data_client:
            return 0
        
        if not self.db_manager or not self.db_manager.is_available():
            return 0
        
        updated_count = 0
        TRAILING_STOP_TRIGGER_PERCENT = 1.0  # Trigger when position is up 1%
        
        try:
            from constants.parameters import STOP_LOSS_PERCENT
            
            # Get all current positions
            positions = self.account_client.get_positions()
            if not positions:
                return 0
            
            logger.debug(f"Checking {len(positions)} positions for trailing stop loss updates...")
            
            # Collect all tickers for batch quote fetch
            position_info = []
            tickers_to_check = []
            
            for pos in positions:
                try:
                    instrument = pos.get('instrument', {})
                    ticker = instrument.get('symbol', '').upper()
                    if not ticker:
                        continue
                    
                    # Get position details
                    long_qty = float(pos.get('longQuantity', 0))
                    short_qty = float(pos.get('shortQuantity', 0))
                    
                    if long_qty <= 0 and short_qty <= 0:
                        continue
                    
                    # Determine direction and quantity
                    if long_qty > 0:
                        direction = 'LONG'
                        quantity = int(long_qty)
                        stop_instruction = 'SELL'
                    else:
                        direction = 'SHORT'
                        quantity = int(short_qty)
                        stop_instruction = 'BUY_TO_COVER'
                    
                    # Get entry price from database
                    cursor = self.db_manager.connection.cursor()
                    find_query = """
                        SELECT entry_price, action 
                        FROM trades 
                        WHERE ticker = %s AND is_closed = FALSE 
                        ORDER BY time_placed DESC 
                        LIMIT 1
                    """
                    cursor.execute(find_query, (ticker,))
                    trade = cursor.fetchone()
                    cursor.close()
                    
                    if not trade or not trade[0]:
                        # Trade not in database - skip silently
                        continue
                    
                    entry_price = float(trade[0])
                    db_action = trade[1].upper() if trade[1] else direction
                    
                    # Verify direction matches (safety check)
                    if db_action != direction:
                        logger.debug(f"Direction mismatch for {ticker}: DB={db_action}, Position={direction}")
                        continue
                    
                    # Store position info for batch processing
                    position_info.append({
                        'ticker': ticker,
                        'direction': direction,
                        'quantity': quantity,
                        'stop_instruction': stop_instruction,
                        'entry_price': entry_price
                    })
                    tickers_to_check.append(ticker)
                    
                except Exception as e:
                    logger.debug(f"Error processing position for trailing stop: {e}")
                    continue
            
            if not tickers_to_check:
                return 0
            
            # Batch fetch quotes for all positions at once (much faster)
            batch_quotes = self.market_data_client.get_quotes_batch(tickers_to_check)
            
            # Process each position with its quote data
            for pos_info in position_info:
                try:
                    ticker = pos_info['ticker']
                    direction = pos_info['direction']
                    quantity = pos_info['quantity']
                    stop_instruction = pos_info['stop_instruction']
                    entry_price = pos_info['entry_price']
                    
                    # Get current price from batch quotes
                    quote_data = batch_quotes.get(ticker) if batch_quotes else None
                    if not quote_data:
                        logger.debug(f"Could not get quote for {ticker} from batch")
                        continue
                    
                    current_price = (
                        quote_data.get('quote', {}).get('lastPrice') or
                        quote_data.get('regular', {}).get('regularMarketLastPrice') or
                        quote_data.get('lastPrice')
                    )
                    
                    if not current_price:
                        logger.debug(f"Could not get current price for {ticker}")
                        continue
                    
                    current_price = float(current_price)
                    
                    # Get the last price at which trailing stop was updated (if any)
                    last_update_price = self.trade_tracker.get_last_trailing_stop_price(ticker)
                    
                    # Determine the reference price for calculating gain
                    # If we've updated before, use last update price; otherwise use entry price
                    if last_update_price is not None:
                        reference_price = last_update_price
                        logger.debug(f"{ticker}: Using last update price ${reference_price:.2f} as reference")
                    else:
                        reference_price = entry_price
                        logger.debug(f"{ticker}: Using entry price ${reference_price:.2f} as reference (first trailing stop check)")
                    
                    # Calculate gain percentage from reference price
                    if direction == 'LONG':
                        gain_percent = ((current_price - reference_price) / reference_price) * 100
                    else:  # SHORT
                        gain_percent = ((reference_price - current_price) / reference_price) * 100
                    
                    # Only update if position is up 1% or more from reference price
                    if gain_percent < TRAILING_STOP_TRIGGER_PERCENT:
                        continue  # Not up enough yet
                    
                    # Get existing stop loss order ID
                    existing_stop_loss_id = self.trade_tracker.get_stop_loss_order_id(ticker)
                    
                    if not existing_stop_loss_id:
                        logger.debug(f"No stop loss order tracked for {ticker}, skipping trailing stop update")
                        continue
                    
                    # Calculate new stop loss price based on current price
                    # New stop = current price - stop loss percent (to lock in gains)
                    if direction == 'LONG':
                        # For LONG: stop loss is below current price
                        new_stop_price = current_price * (1 - STOP_LOSS_PERCENT / 100)
                        # Ensure we don't go below entry price (lock in at least break-even)
                        if new_stop_price < entry_price:
                            new_stop_price = entry_price
                    else:  # SHORT
                        # For SHORT: stop loss is above current price
                        new_stop_price = current_price * (1 + STOP_LOSS_PERCENT / 100)
                        # Ensure we don't go above entry price (lock in at least break-even)
                        if new_stop_price > entry_price:
                            new_stop_price = entry_price
                    
                    logger.info(f"🔼 {ticker} is up {gain_percent:.2f}% from {'last update' if last_update_price else 'entry'} (Ref: ${reference_price:.2f}, Current: ${current_price:.2f})")
                    logger.info(f"   Updating stop loss from entry-based to current-price-based: ${new_stop_price:.2f}")
                    
                    # Cancel existing stop loss order
                    cancel_result = self.order_manager.cancel_order(existing_stop_loss_id)
                    if not cancel_result.get('success'):
                        # Check if order was already filled or doesn't exist
                        error_msg = cancel_result.get('error', '').upper()
                        if 'FILLED' in error_msg or 'NOT FOUND' in error_msg or '404' in error_msg:
                            logger.debug(f"Stop loss order for {ticker} already filled or doesn't exist, skipping update")
                            continue
                        else:
                            logger.warning(f"Failed to cancel stop loss for {ticker}: {cancel_result.get('error')}")
                            continue
                    
                    # Small delay to ensure cancellation is processed
                    import time
                    time.sleep(0.5)
                    
                    # Place new stop loss order at current price - stop loss percent
                    stop_loss_result = self.order_manager.create_stop_loss_order(
                        ticker,
                        stop_instruction,
                        quantity,
                        current_price,  # Use current price as the base
                        STOP_LOSS_PERCENT
                    )
                    
                    if stop_loss_result.get('orderId') or stop_loss_result.get('success'):
                        new_stop_loss_id = stop_loss_result.get('orderId', stop_loss_result.get('order_id', 'unknown'))
                        self.trade_tracker.set_stop_loss_order_id(ticker, new_stop_loss_id)
                        # Track the current price as the last update price
                        self.trade_tracker.set_last_trailing_stop_price(ticker, current_price)
                        logger.info(f"✓ Updated trailing stop loss for {ticker} (New Order ID: {new_stop_loss_id}, Stop: ${new_stop_price:.2f})")
                        updated_count += 1
                    else:
                        logger.warning(f"Failed to place new stop loss for {ticker}: {stop_loss_result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    logger.debug(f"Error updating trailing stop loss for {pos.get('instrument', {}).get('symbol', 'unknown')}: {e}")
                    continue
            
            if updated_count > 0:
                logger.info(f"Updated {updated_count} trailing stop loss(es) to lock in gains")
            
            return updated_count
            
        except Exception as e:
            logger.error(f"Error in trailing stop loss update: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return 0
    
    def get_tickers_from_most(self) -> List[str]:
        """
        Get tickers from MOST command.
        
        Returns:
            list: List of ticker symbols
        """
        cmd = None
        try:
            logger.info(f"Getting tickers from MOST ({MOST_TAB}, limit={MOST_LIMIT})")
            # MOST command takes tab and limit in constructor
            cmd = MOSTCommand(self.controller, tab=MOST_TAB, limit=MOST_LIMIT)
            result = cmd.execute()
            
            if not result['success']:
                logger.error(f"Failed to execute MOST command: {result.get('error')}")
                return []
            
            # Extract DataFrame from command
            if hasattr(cmd, 'df') and cmd.df is not None:
                logger.debug(f"MOST DataFrame shape: {cmd.df.shape}")
                logger.debug(f"MOST DataFrame columns: {cmd.df.columns.tolist()}")
                
                # MOST command uses 'Ticker' column (capital T)
                # Try both 'Ticker' and 'symbol' for compatibility
                if 'Ticker' in cmd.df.columns:
                    # Extract tickers, strip whitespace, filter out empty/None values
                    tickers = [str(t).strip().upper() for t in cmd.df['Ticker'].tolist() if t and str(t).strip()]
                    logger.debug(f"Extracted {len(tickers)} tickers from 'Ticker' column")
                    # Show first few tickers for debugging
                    if tickers:
                        logger.debug(f"First 5 tickers: {tickers[:5]}")
                elif 'symbol' in cmd.df.columns:
                    tickers = [str(t).strip().upper() for t in cmd.df['symbol'].tolist() if t and str(t).strip()]
                    logger.debug(f"Extracted {len(tickers)} tickers from 'symbol' column")
                else:
                    logger.warning(f"MOST DataFrame columns: {cmd.df.columns.tolist()}")
                    logger.error("MOST DataFrame missing 'Ticker' or 'symbol' column")
                    # Debug: show first row to understand structure
                    if len(cmd.df) > 0:
                        logger.debug(f"First row sample: {cmd.df.iloc[0].to_dict()}")
                    return []
                
                if not tickers:
                    logger.error(f"No tickers extracted! DataFrame has {len(cmd.df)} rows but ticker list is empty")
                    # Debug: show what's actually in the Ticker column
                    if 'Ticker' in cmd.df.columns:
                        sample_values = cmd.df['Ticker'].head(10).tolist()
                        logger.error(f"Sample Ticker values: {sample_values}")
                    if len(cmd.df) > 0:
                        logger.debug(f"Sample row: {cmd.df.iloc[0].to_dict()}")
                    return []
                
                # Filter out blacklisted tickers
                filtered_tickers, blacklisted = filter_blacklisted_tickers(tickers)
                
                if blacklisted:
                    logger.info(f"Filtered out {len(blacklisted)} blacklisted tickers")
                
                logger.info(f"Retrieved {len(filtered_tickers)} tickers from MOST (from {len(tickers)} total)")
                return filtered_tickers
            else:
                logger.error("MOST command did not return DataFrame")
                return []
                
        except Exception as e:
            logger.error(f"Error getting tickers from MOST: {e}")
            return []
        finally:
            # Always close the MOST window after extracting data
            if cmd and hasattr(cmd, 'close'):
                try:
                    cmd.close()
                    logger.debug("Closed MOST window")
                except Exception as e:
                    logger.debug(f"Error closing MOST window: {e}")
    
    def get_open_positions_tickers(self) -> List[str]:
        """
        Get tickers from currently open positions.
        
        Returns:
            list: List of ticker symbols with open positions
        """
        try:
            positions = self.account_client.get_positions()
            if positions is None:
                logger.warning("Could not retrieve positions")
                return []
            
            tickers = []
            for position in positions:
                symbol = position.get('instrument', {}).get('symbol', position.get('symbol', ''))
                if symbol:
                    tickers.append(symbol.upper())
            
            logger.info(f"Found {len(tickers)} open positions")
            return tickers
            
        except Exception as e:
            logger.error(f"Error getting open positions: {e}")
            return []
    
    def get_position_details(self) -> Dict[str, Dict]:
        """
        Get detailed position information including direction.
        
        Returns:
            dict: {ticker: {'direction': 'LONG'|'SHORT', 'quantity': int, 'position': dict}}
        """
        try:
            positions = self.account_client.get_positions()
            if positions is None:
                return {}
            
            position_details = {}
            for position in positions:
                symbol = position.get('instrument', {}).get('symbol', position.get('symbol', ''))
                if not symbol:
                    continue
                
                symbol = symbol.upper()
                long_qty = position.get('longQuantity', 0)
                short_qty = position.get('shortQuantity', 0)
                
                if long_qty > 0:
                    position_details[symbol] = {
                        'direction': 'LONG',
                        'quantity': int(long_qty),
                        'position': position
                    }
                elif short_qty > 0:
                    position_details[symbol] = {
                        'direction': 'SHORT',
                        'quantity': int(short_qty),
                        'position': position
                    }
            
            return position_details
            
        except Exception as e:
            logger.error(f"Error getting position details: {e}")
            return {}
    
    def run_prt_analysis(self, tickers: List[str]) -> Optional[Dict]:
        """
        Run PRT analysis on a list of tickers.
        
        Args:
            tickers: List of ticker symbols (max PRT_MAX_TICKERS)
        
        Returns:
            dict: PRT results (ticker -> PRT data) or None if error
        """
        if not tickers:
            logger.warning("No tickers provided for PRT analysis")
            return None
        
        # Limit to PRT_MAX_TICKERS
        if len(tickers) > PRT_MAX_TICKERS:
            logger.warning(f"Limiting tickers from {len(tickers)} to {PRT_MAX_TICKERS}")
            tickers = tickers[:PRT_MAX_TICKERS]
        
        try:
            logger.info(f"Running PRT analysis on {len(tickers)} tickers")
            # PRT command takes tickers in constructor
            cmd = PRTCommand(self.controller, tickers=tickers)
            result = cmd.execute()
            
            if not result['success']:
                logger.error(f"Failed to execute PRT command: {result.get('error')}")
                return None
            
            # Extract PRT data from DataFrame
            if hasattr(cmd, 'df') and cmd.df is not None:
                # Convert DataFrame to dict format (ticker -> PRT data)
                # PRT command uses 'symbol' column (lowercase)
                prt_data = {}
                for _, row in cmd.df.iterrows():
                    # Try both 'symbol' and 'Ticker' for compatibility
                    ticker = row.get('symbol', row.get('Ticker', '')).upper()
                    if ticker:
                        prt_data[ticker] = {
                            'edge': row.get('edge'),
                            'prob_up': row.get('prob_up'),
                            'mean': row.get('mean'),
                            'p10': row.get('p10'),
                            'p90': row.get('p90'),
                            'dist1': row.get('dist1'),
                            'n': row.get('n'),
                            'timestamp': row.get('timestamp')
                        }
                
                logger.info(f"PRT analysis completed for {len(prt_data)} tickers")
                return prt_data
            else:
                logger.error("PRT command did not return DataFrame")
                return None
                
        except Exception as e:
            logger.error(f"Error running PRT analysis: {e}")
            return None
        finally:
            # Delete the CSV file after use to avoid cluttering the Downloads folder
            if cmd and hasattr(cmd, 'csv_file_path') and cmd.csv_file_path:
                try:
                    import os
                    if os.path.exists(cmd.csv_file_path):
                        os.remove(cmd.csv_file_path)
                        logger.debug(f"Deleted PRT CSV file: {cmd.csv_file_path}")
                except Exception as e:
                    logger.debug(f"Could not delete PRT CSV file {cmd.csv_file_path}: {e}")
            
            # Always close the PRT window after extracting data
            if cmd and hasattr(cmd, 'close'):
                try:
                    cmd.close()
                    logger.debug("Closed PRT window")
                except Exception as e:
                    logger.debug(f"Error closing PRT window: {e}")
    
    def filter_trades_by_prob_up(self, prt_data: Dict) -> Tuple[List[Dict], List[Dict]]:
        """
        Filter PRT data by prob_up thresholds.
        
        Args:
            prt_data: PRT analysis results (dict of ticker -> PRT data)
        
        Returns:
            tuple: (long_candidates, short_candidates)
        """
        long_candidates = []
        short_candidates = []
        
        for ticker, data in prt_data.items():
            prob_up = data.get('prob_up')
            edge = data.get('edge', 0)
            
            if prob_up is None:
                continue
            
            # Check edge threshold
            if abs(edge) < PROB_UP_EDGE_THRESHOLD:
                continue
            
            # Long candidates: prob_up >= PROB_UP_MIN_LONG
            if prob_up >= PROB_UP_MIN_LONG:
                long_candidates.append({
                    'ticker': ticker,
                    'prob_up': prob_up,
                    'edge': edge,
                    'data': data
                })
            # Short candidates: prob_up <= PROB_UP_MIN_SHORT
            elif prob_up <= PROB_UP_MIN_SHORT:
                short_candidates.append({
                    'ticker': ticker,
                    'prob_up': prob_up,
                    'edge': edge,
                    'data': data
                })
        
        # Sort by edge (absolute value for shorts)
        long_candidates.sort(key=lambda x: x['edge'], reverse=True)
        short_candidates.sort(key=lambda x: abs(x['edge']), reverse=True)
        
        # If DO_OPPOSITE is enabled, swap long and short candidates
        if DO_OPPOSITE:
            logger.info("DO_OPPOSITE enabled: Inverting trading directions")
            # Swap the lists and invert the direction in each candidate
            for candidate in long_candidates:
                candidate['original_direction'] = 'LONG'
            for candidate in short_candidates:
                candidate['original_direction'] = 'SHORT'
            
            # Swap the lists
            long_candidates, short_candidates = short_candidates, long_candidates
            
            logger.info(f"After inversion: {len(long_candidates)} long candidates (originally short), {len(short_candidates)} short candidates (originally long)")
        else:
            logger.info(f"Found {len(long_candidates)} long candidates, {len(short_candidates)} short candidates")
        
        return long_candidates, short_candidates
    
    def should_close_position(self, ticker: str, current_prt_data: Dict) -> bool:
        """
        Determine if a position should be closed based on current PRT data.
        
        Args:
            ticker: Stock ticker symbol
            current_prt_data: Current PRT analysis results
        
        Returns:
            bool: True if position should be closed
        """
        if ticker not in current_prt_data:
            logger.debug(f"{ticker} not in current PRT data, keeping position")
            return False
        
        prt_data = current_prt_data[ticker]
        prob_up = prt_data.get('prob_up')
        
        if prob_up is None:
            return False
        
        # Get position info to determine if it's long or short
        positions = self.account_client.get_positions()
        if positions:
            for position in positions:
                if position.get('symbol', '').upper() == ticker.upper():
                    long_qty = position.get('longQuantity', 0)
                    short_qty = position.get('shortQuantity', 0)
                    
                    # Long position: close if prob_up < threshold
                    if long_qty > 0:
                        if prob_up < PROB_UP_MIN_LONG:
                            logger.info(f"Closing long {ticker}: prob_up={prob_up:.3f} < {PROB_UP_MIN_LONG}")
                            return True
                    
                    # Short position: close if prob_up > threshold
                    elif short_qty > 0:
                        if prob_up > PROB_UP_MIN_SHORT:
                            logger.info(f"Closing short {ticker}: prob_up={prob_up:.3f} > {PROB_UP_MIN_SHORT}")
                            return True
        
        return False
    
    def execute_cycle(self) -> Dict:
        """
        Execute one iteration of the continuous rolling strategy.
        
        Rolling Strategy Logic (Continuous Cycle):
        - First iteration: MOST tickers only → PRT → Open positions
        - Subsequent iterations: (Active positions from previous iteration) + MOST → PRT → Maintain/close/open positions
        
        This is a continuous rolling process where:
        1. Active positions from the current iteration feed into the next iteration's PRT analysis
        2. Each iteration combines active positions with fresh MOST tickers
        3. PRT is run on the combined list
        4. Positions are maintained/closed/opened based on PRT results
        5. The cycle repeats with the new active positions
        
        Returns:
            dict: Results of the iteration
        """
        logger.info("=" * 60)
        logger.info("Rolling Strategy Iteration")
        logger.info("=" * 60)
        
        results = {
            'success': False,
            'tickers_from_most': 0,
            'active_positions': 0,
            'prt_tickers': 0,
            'trades_opened': 0,
            'trades_closed': 0,
            'errors': []
        }
        
        try:
            # Step 1: Get fresh tickers from MOST
            most_tickers = self.get_tickers_from_most()
            results['tickers_from_most'] = len(most_tickers)
            
            if not most_tickers:
                logger.warning("No tickers from MOST - skipping this iteration")
                results['errors'].append("No tickers from MOST")
                return results
            
            # Step 2: Get currently active positions (from previous iteration or initial state)
            # These positions will feed into the next iteration's PRT analysis
            active_positions = self.get_open_positions_tickers()
            results['active_positions'] = len(active_positions)
            
            # Step 3: Combine tickers for PRT analysis (Rolling Logic)
            # First iteration: active_positions is empty, so only MOST tickers go to PRT
            # Subsequent iterations: active_positions (from previous iteration) + new MOST tickers
            all_tickers = list(set(active_positions + most_tickers))
            
            # Limit to PRT_MAX_TICKERS, prioritizing active positions
            # Active positions MUST be included in PRT to maintain the rolling cycle
            if len(all_tickers) > PRT_MAX_TICKERS:
                # Always include all active positions (they need PRT analysis for next iteration)
                # Then fill remaining slots with new MOST tickers
                remaining_slots = PRT_MAX_TICKERS - len(active_positions)
                if remaining_slots > 0:
                    new_tickers = [t for t in most_tickers if t not in active_positions][:remaining_slots]
                    prt_tickers = active_positions + new_tickers
                else:
                    # If we have more active positions than PRT_MAX_TICKERS, prioritize them
                    prt_tickers = active_positions[:PRT_MAX_TICKERS]
                    logger.warning(f"Too many active positions ({len(active_positions)}), limiting to {PRT_MAX_TICKERS} for PRT")
            else:
                prt_tickers = all_tickers
            
            results['prt_tickers'] = len(prt_tickers)
            logger.info(f"PRT input: {len(active_positions)} active positions + {len(prt_tickers) - len(active_positions)} new from MOST = {len(prt_tickers)} total")
            
            # Step 4: Run PRT analysis on combined ticker list
            # This PRT result will be used to maintain positions for the next iteration
            prt_data = self.run_prt_analysis(prt_tickers)
            if not prt_data:
                results['errors'].append("Failed to get PRT data")
                return results
            
            # Step 5: Get current position details (direction and quantity)
            position_details = self.get_position_details()
            
            # Step 6: Filter by prob_up thresholds to find trade candidates
            long_candidates, short_candidates = self.filter_trades_by_prob_up(prt_data)
            
            # Step 7: Check each active position against PRT data
            # - If PRT direction matches position direction: keep position (log it)
            # - If PRT direction is opposite: close position
            positions_to_close = []
            positions_to_keep = []
            
            for ticker in active_positions:
                if ticker not in prt_data:
                    # No PRT data - keep position for now
                    positions_to_keep.append(ticker)
                    continue
                
                pos_info = position_details.get(ticker, {})
                pos_direction = pos_info.get('direction', '')
                prt_data_ticker = prt_data[ticker]
                prob_up = prt_data_ticker.get('prob_up')
                
                if prob_up is None:
                    positions_to_keep.append(ticker)
                    continue
                
                # Determine PRT direction (above 50% = long, below 50% = short)
                prt_direction = 'LONG' if prob_up > 0.5 else 'SHORT'
                
                # If DO_OPPOSITE is enabled, invert the decision logic
                if DO_OPPOSITE:
                    # Inverted logic: if directions match, close (opposite of normal)
                    if pos_direction == prt_direction:
                        # Direction matches - close position (inverted)
                        positions_to_close.append(ticker)
                        logger.info(f"Closing {pos_direction} {ticker}: DO_OPPOSITE enabled, PRT direction matches (prob_up={prob_up:.3f})")
                    else:
                        # Direction opposite - keep position (inverted)
                        positions_to_keep.append(ticker)
                        logger.debug(f"Keeping {pos_direction} {ticker}: DO_OPPOSITE enabled, PRT direction is {prt_direction} (prob_up={prob_up:.3f})")
                else:
                    # Normal logic: if directions match, keep
                    if pos_direction == prt_direction:
                        # Direction matches - keep position
                        positions_to_keep.append(ticker)
                        logger.debug(f"Keeping {pos_direction} {ticker}: PRT direction matches (prob_up={prob_up:.3f})")
                    else:
                        # Direction opposite - close position
                        positions_to_close.append(ticker)
                        logger.info(f"Closing {pos_direction} {ticker}: PRT direction is {prt_direction} (prob_up={prob_up:.3f})")
            
            results['trades_closed'] = len(positions_to_close)
            
            # Step 8: Determine new positions to open (not already in active positions)
            # Filter out any tickers we already have positions in to avoid boxed positions
            new_long_candidates = [
                c for c in long_candidates 
                if c['ticker'] not in active_positions
            ]
            new_short_candidates = [
                c for c in short_candidates 
                if c['ticker'] not in active_positions
            ]
            
            results['trades_opened'] = len(new_long_candidates) + len(new_short_candidates)
            
            # Step 8: Log summary
            logger.info(f"Active positions: {len(active_positions)}")
            logger.info(f"Positions to keep (PRT direction matches): {len(positions_to_keep)} {positions_to_keep[:5] if positions_to_keep else ''}")
            logger.info(f"Positions to close (PRT direction opposite): {len(positions_to_close)} {positions_to_close[:5] if positions_to_close else ''}")
            logger.info(f"New long candidates: {len(new_long_candidates)} {[c['ticker'] for c in new_long_candidates[:5]]}")
            logger.info(f"New short candidates: {len(new_short_candidates)} {[c['ticker'] for c in new_short_candidates[:5]]}")
            
            # Step 9: Close positions that no longer meet criteria (use limit orders first)
            if positions_to_close and self.order_manager and self.trade_executor:
                logger.info(f"Closing {len(positions_to_close)} position(s) that no longer meet criteria...")
                close_orders = []
                
                for ticker in positions_to_close:
                    try:
                        pos_info = position_details.get(ticker, {})
                        direction = pos_info.get('direction', '')
                        quantity = pos_info.get('quantity', 0)
                        
                        if not direction or quantity <= 0:
                            logger.warning(f"Invalid position info for {ticker}, skipping close")
                            continue
                        
                        # Cancel stop loss order first if it exists
                        stop_loss_order_id = self.trade_tracker.get_stop_loss_order_id(ticker)
                        if stop_loss_order_id:
                            logger.info(f"Canceling stop loss order for {ticker} (Order ID: {stop_loss_order_id})")
                            cancel_result = self.order_manager.cancel_order(stop_loss_order_id)
                            if cancel_result.get('success'):
                                logger.info(f"✓ Stop loss order canceled for {ticker}")
                            else:
                                # Check if order was already filled or doesn't exist
                                if cancel_result.get('error'):
                                    error_msg = cancel_result.get('error', '').upper()
                                    if 'FILLED' in error_msg or 'NOT FOUND' in error_msg or '404' in error_msg:
                                        logger.debug(f"Stop loss order for {ticker} already filled or doesn't exist")
                                    else:
                                        logger.warning(f"Failed to cancel stop loss order for {ticker}: {cancel_result.get('error')}")
                        
                        # Get limit price for closing
                        if direction == 'LONG':
                            limit_price = self.trade_executor.get_limit_price(ticker, 'LONG')
                            instruction = 'SELL'
                        else:  # SHORT
                            limit_price = self.trade_executor.get_limit_price(ticker, 'SHORT')
                            instruction = 'BUY_TO_COVER'
                        
                        if limit_price is None:
                            logger.warning(f"Could not get limit price for {ticker}, using market order")
                            result = self.order_manager.create_market_order(ticker, instruction, quantity)
                        else:
                            logger.info(f"Closing {direction} {ticker}: {quantity} shares @ ${limit_price:.2f} limit")
                            result = self.order_manager.create_limit_order(ticker, instruction, quantity, limit_price)
                        
                        if 'orderId' in result or 'success' in result:
                            order_id = result.get('orderId', result.get('order_id', 'unknown'))
                            close_orders.append({
                                'ticker': ticker,
                                'direction': direction,
                                'quantity': quantity,
                                'order_id': order_id,
                                'instruction': instruction,
                                'limit_price': limit_price
                            })
                            logger.info(f"✓ Placed close order for {direction} {ticker}: {quantity} shares (Order ID: {order_id})")
                        else:
                            logger.error(f"✗ Failed to place close order for {ticker}: {result}")
                            
                    except Exception as e:
                        logger.error(f"Error closing position {ticker}: {e}")
                
                # Check if limit orders filled, fall back to market if needed
                if close_orders:
                    import time
                    time.sleep(2)  # Wait a moment for orders to process
                    
                    for close_order in close_orders:
                        order_id = close_order['order_id']
                        ticker = close_order['ticker']
                        
                        # Check order status
                        order_status = self.order_manager.get_order_status(order_id)
                        status = order_status.get('status', '').upper()
                        
                        if status == 'FILLED':
                            logger.info(f"✓ Close order filled for {ticker}")
                            self._close_trade_with_db_update(ticker, order_id)
                        elif status in ['REJECTED', 'CANCELED', 'EXPIRED']:
                            logger.warning(f"Close order {status} for {ticker}, using market order")
                            # Fall back to market order
                            result = self.order_manager.create_market_order(
                                ticker, 
                                close_order['instruction'], 
                                close_order['quantity']
                            )
                            if 'orderId' in result or 'success' in result:
                                logger.info(f"✓ Market order placed to close {ticker}")
                                close_order_id = result.get('orderId', result.get('order_id'))
                                # Wait a moment for market order to fill, then update
                                import time
                                time.sleep(1)
                                self._close_trade_with_db_update(ticker, close_order_id)
                        elif status in ['WORKING', 'PENDING_ACTIVATION', 'QUEUED', 'ACCEPTED']:
                            # Still working, wait a bit more then check again
                            time.sleep(3)
                            order_status = self.order_manager.get_order_status(order_id)
                            status = order_status.get('status', '').upper()
                            
                            if status == 'FILLED':
                                logger.info(f"✓ Close order filled for {ticker} (after wait)")
                                self._close_trade_with_db_update(ticker, order_id)
                            else:
                                # Cancel and use market order
                                logger.warning(f"Close order still {status} for {ticker}, canceling and using market order")
                                self.order_manager.cancel_order(order_id)
                                result = self.order_manager.create_market_order(
                                    ticker, 
                                    close_order['instruction'], 
                                    close_order['quantity']
                                )
                                if 'orderId' in result or 'success' in result:
                                    logger.info(f"✓ Market order placed to close {ticker}")
                                    close_order_id = result.get('orderId', result.get('order_id'))
                                    # Wait a moment for market order to fill, then update
                                    time.sleep(1)
                                    self._close_trade_with_db_update(ticker, close_order_id)
            
            # Step 9.5: Check for stop losses that were triggered
            # This runs after closing positions that no longer meet criteria
            # and before placing new orders
            logger.info("Checking for triggered stop loss orders...")
            triggered_stops = self._check_and_update_stop_losses()
            if triggered_stops > 0:
                logger.info(f"Found and updated {triggered_stops} stop loss trigger(s)")
            
            # Step 10: Size and execute new trades
            if (new_long_candidates or new_short_candidates) and self.position_sizer and self.trade_executor:
                # Check actual current position count from account (more accurate than positions_to_keep)
                # This accounts for positions that may have been closed in previous cycles
                actual_positions = self.get_open_positions_tickers()
                current_position_count = len(actual_positions)
                available_slots = MAX_POSITIONS - current_position_count
                
                if available_slots <= 0:
                    logger.warning(f"Maximum positions ({MAX_POSITIONS}) reached. Current: {current_position_count}. Skipping new position opens.")
                else:
                    logger.info(f"Position limit: {current_position_count}/{MAX_POSITIONS} positions. Can open up to {available_slots} new position(s).")
                    
                    # Prepare trade candidates for sizing
                    trade_candidates = []
                    for candidate in new_long_candidates:
                        trade_candidates.append({
                            'ticker': candidate['ticker'],
                            'direction': 'LONG',
                            'prob_up': candidate.get('prob_up'),
                            'edge': candidate.get('edge')
                        })
                    for candidate in new_short_candidates:
                        trade_candidates.append({
                            'ticker': candidate['ticker'],
                            'direction': 'SHORT',
                            'prob_up': candidate.get('prob_up'),
                            'edge': candidate.get('edge')
                        })
                    
                    # Limit trade candidates to available position slots
                    if len(trade_candidates) > available_slots:
                        # Sort by edge (absolute value) to prioritize best candidates
                        trade_candidates.sort(key=lambda x: abs(x.get('edge', 0)), reverse=True)
                        original_count = len(trade_candidates)
                        trade_candidates = trade_candidates[:available_slots]
                        logger.info(f"Limiting new positions from {original_count} to {available_slots} (max positions: {MAX_POSITIONS})")
                    
                    if trade_candidates:
                        logger.info(f"Sizing {len(trade_candidates)} trade candidate(s)...")
                        # Size the trades (pass current position count for equal allocation)
                        sized_trades = self.position_sizer.size_trades(trade_candidates, current_position_count=current_position_count)
                        
                        if sized_trades:
                            logger.info(f"Executing {len(sized_trades)} trade(s)...")
                            
                            # Define callback to place stop loss immediately when trade fills
                            def on_trade_fill(ticker: str, direction: str, shares: int, entry_price: float, order_id: str):
                                """Place stop loss order immediately when a trade fills."""
                                ticker_upper = ticker.upper()
                                direction_upper = direction.upper()
                                
                                # Track the trade immediately
                                self.trade_tracker.add_trade(ticker_upper)
                                if SHOW_ORDER_OUTPUT:
                                    logger.debug(f"Tracking new trade: {ticker_upper} ({direction_upper}, {shares} shares)")
                                
                                # Place stop loss order IMMEDIATELY (critical for risk management)
                                if entry_price > 0:
                                    if direction_upper == 'LONG':
                                        stop_instruction = 'SELL'
                                    else:  # SHORT
                                        stop_instruction = 'BUY_TO_COVER'
                                    
                                    stop_loss_result = self.order_manager.create_stop_loss_order(
                                        ticker_upper,
                                        stop_instruction,
                                        shares,
                                        entry_price,
                                        STOP_LOSS_PERCENT
                                    )
                                    
                                    if stop_loss_result.get('orderId') or stop_loss_result.get('success'):
                                        stop_loss_order_id = stop_loss_result.get('orderId', stop_loss_result.get('order_id', 'unknown'))
                                        self.trade_tracker.set_stop_loss_order_id(ticker_upper, stop_loss_order_id)
                                        logger.info(f"✓ Stop loss placed IMMEDIATELY for {ticker_upper} (Order ID: {stop_loss_order_id}, {STOP_LOSS_PERCENT}% loss)")
                                    else:
                                        logger.warning(f"Failed to place stop loss order for {ticker_upper}: {stop_loss_result.get('error', 'Unknown error')}")
                            
                            # Execute the trades with callback for immediate stop loss placement
                            execution_results = self.trade_executor.execute_trades(sized_trades, on_fill_callback=on_trade_fill)
                            
                            # Collect trades for bulk database insert (non-critical, done after execution)
                            successful_trades = 0
                            trades_to_insert = []
                            
                            for result in execution_results:
                                if result.get('success') and result.get('filled'):
                                    successful_trades += 1
                                    ticker = result.get('ticker', '').upper()
                                    direction = result.get('direction', '').upper()
                                    shares = result.get('shares', 0)
                                    entry_price = result.get('price', 0)
                                    order_id = result.get('order_id', 'unknown')
                                    
                                    # Collect trade data for bulk insert
                                    if self.db_manager and self.db_manager.is_available() and entry_price > 0:
                                        from datetime import datetime
                                        import pytz
                                        trade_data = {
                                            'ticker': ticker,
                                            'action': direction,
                                            'quantity': shares,
                                            'entry_price': entry_price,
                                            'exit_price': None,
                                            'profit_loss': None,
                                            'profit_loss_percent': None,
                                            'time_placed': datetime.now(pytz.UTC),
                                            'close_time': None,
                                            'order_id': str(order_id),
                                            'is_closed': False
                                        }
                                        trades_to_insert.append(trade_data)
                            
                            # Bulk insert all trades to database (faster than sequential)
                            if trades_to_insert:
                                try:
                                    trade_db_ids = self.db_manager.bulk_insert_trades(trades_to_insert)
                                    successful_db_inserts = sum(1 for tid in trade_db_ids if tid is not None)
                                    logger.info(f"Bulk inserted {successful_db_inserts}/{len(trades_to_insert)} trades to database")
                                    if SHOW_ORDER_OUTPUT:
                                        for i, trade_data in enumerate(trades_to_insert):
                                            if trade_db_ids[i]:
                                                logger.debug(f"Trade inserted to database: {trade_data['ticker']} (DB ID: {trade_db_ids[i]})")
                                except Exception as e:
                                    logger.error(f"Error bulk inserting trades: {e}")
                                    # Fallback to individual inserts if bulk fails
                                    for trade_data in trades_to_insert:
                                        try:
                                            trade_db_id = self.db_manager.insert_trade(trade_data)
                                            if trade_db_id:
                                                logger.debug(f"Trade inserted to database: {trade_data['ticker']} (DB ID: {trade_db_id})")
                                        except Exception as e2:
                                            logger.error(f"Failed to insert trade for {trade_data['ticker']}: {e2}")
                            
                            logger.info(f"Successfully executed {successful_trades}/{len(sized_trades)} trade(s)")
                            results['trades_opened'] = successful_trades
                        else:
                            logger.warning("No trades could be sized (insufficient buying power or invalid prices)")
            elif not self.order_manager:
                logger.warning("OrderManager not available - skipping trade execution")
            
            results['success'] = True
            logger.info("Rolling strategy iteration completed - active positions will feed into next iteration")
            
        except Exception as e:
            logger.error(f"Error in rolling strategy iteration: {e}")
            import traceback
            traceback.print_exc()
            results['errors'].append(str(e))
        
        return results

