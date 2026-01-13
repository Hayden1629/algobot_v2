"""
Startup script for algobot_v2.
Initializes the system and runs the algorithm with rolling strategy.
"""
from pathlib import Path
from loguru import logger
import sys
import time
import signal
import atexit
from datetime import datetime, timedelta
from typing import Optional
import pytz
import os

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load Railway MySQL credentials automatically (if config exists)
# This must happen before any database imports
try:
    import railway_config
    # Use print here since logger isn't configured yet
    print("✓ Railway MySQL credentials loaded from railway_config.py")
except ImportError:
    # Check if environment variables are already set
    if not (os.getenv('MYSQLHOST') or os.getenv('MYSQL_HOST')):
        print("⚠️  Railway MySQL credentials not found - database features will be disabled")
        print("   Create railway_config.py or set MYSQLHOST/MYSQL_HOST environment variables")
    else:
        print("✓ Railway MySQL credentials found in environment variables")

from database.init import init_database, database_exists
from database.db_manager import DatabaseManager
from schwab.tokens.storage import token_file_exists, get_token_file_path
from schwab.tokens.acquisition import acquire_tokens
from constants.parameters import (
    GODEL_USERNAME,
    GODEL_PASSWORD,
    MARKET_OPEN_DELAY_MINUTES,
    MARKET_CLOSE_BUFFER_MINUTES,
    MAX_HOLD_TIME_MINUTES,
    ACCOUNT_SIZE_CHECK_INTERVAL_MINUTES,
    PRT_RECHECK_INTERVAL_SECONDS,
    MAX_DRAWDOWN_PERCENT
)
from core.controller import GodelTerminalController
from schwab.account.client import AccountClient
from schwab.market_data.client import MarketDataClient
from schwab.account.orders import OrderManager
from strategy.rolling_strategy import RollingStrategy
from strategy.trade_tracker import TradeTracker
from monitoring.account_size import AccountSizeMonitor


def check_prerequisites() -> bool:
    """
    Check if all prerequisites are met.
    
    Returns:
        True if all prerequisites are met, False otherwise
    """
    logger.info("Checking prerequisites...")
    
    # Check database
    if not database_exists():
        logger.info("Database not found, initializing...")
        if not init_database():
            logger.error("Failed to initialize database")
            return False
        logger.info("✓ Database initialized")
    else:
        logger.info("✓ Database exists")
    
    # Check tokens
    token_file = get_token_file_path()
    token_file_exists_flag = token_file_exists()
    token_file_too_old = False
    
    if token_file_exists_flag:
        # Check if token file is more than 29 minutes old
        try:
            file_mtime = os.path.getmtime(token_file)
            file_age_minutes = (time.time() - file_mtime) / 60
            if file_age_minutes > 29:
                token_file_too_old = True
                logger.warning(f"Token file is {file_age_minutes:.1f} minutes old (older than 29 minutes)")
            else:
                logger.info(f"✓ Token file exists and is {file_age_minutes:.1f} minutes old")
        except Exception as e:
            logger.warning(f"Could not check token file age: {e}, treating as missing")
            token_file_too_old = True
    
    if not token_file_exists_flag or token_file_too_old:
        if token_file_too_old:
            logger.warning("Token file is too old, re-acquiring tokens...")
        else:
            logger.warning("Token file not found")
        logger.info("Starting token acquisition...")
        if not acquire_tokens():
            logger.error("Failed to acquire tokens")
            return False
        logger.info("✓ Tokens acquired")
    else:
        logger.info("✓ Token file exists and is valid")
    
    return True


def initialize_godel_controller(headless: bool = False) -> GodelTerminalController:
    """
    Initialize and connect to Godel Terminal.
    
    Args:
        headless: Whether to run browser in headless mode
    
    Returns:
        Initialized GodelTerminalController instance
    """
    logger.info("Initializing Godel Terminal controller...")
    
    controller = GodelTerminalController(headless=headless)
    controller.connect()
    controller.login(GODEL_USERNAME, GODEL_PASSWORD)
    controller.load_layout("dev")
    controller.open_terminal()
    
    logger.info("✓ Godel Terminal ready")
    return controller


def close_all_positions_before_market_close(
    order_manager: OrderManager,
    account_client: AccountClient,
    reason: str = "market close",
    db_manager: Optional[DatabaseManager] = None,
    market_data_client: Optional[MarketDataClient] = None
) -> None:
    """
    Close all positions before market close (emergency use).
    Follows RULES.md: Must close positions within 5 minutes of market close.
    
    Process:
    1. Cancel ALL outstanding orders FIRST (including stop losses)
    2. Submit ALL market orders to close positions (fast, no database work)
    3. Update database AFTER all orders are submitted
    
    Args:
        order_manager: Order manager instance
        account_client: Account client instance
        reason: Reason for closing positions
        db_manager: Optional database manager to update trades
        market_data_client: Optional market data client to get exit prices
    """
    logger.error("=" * 60)
    logger.error(f"EMERGENCY: Closing all positions - {reason}")
    logger.error("=" * 60)
    
    # ========================================================================
    # STEP 1: CANCEL ALL OUTSTANDING ORDERS FIRST
    # ========================================================================
    logger.error("STEP 1: CANCELING ALL OUTSTANDING ORDERS (INCLUDING STOP LOSSES)")
    logger.error("=" * 60)
    
    canceled_count = 0
    failed_count = 0
    
    try:
        logger.error("Calling get_all_open_orders()...")
        open_orders = account_client.get_all_open_orders()
        logger.error(f"API returned: {len(open_orders) if open_orders else 0} order(s)")
        
        if open_orders and len(open_orders) > 0:
            logger.error(f"FOUND {len(open_orders)} OUTSTANDING ORDER(S) - CANCELING ALL NOW")
            for idx, order in enumerate(open_orders, 1):
                order_id = order.get('orderId') or order.get('order_id')
                order_status = order.get('status', 'UNKNOWN')
                symbol = order.get('orderLegCollection', [{}])[0].get('instrument', {}).get('symbol', 'UNKNOWN')
                
                if not order_id:
                    logger.error(f"[{idx}/{len(open_orders)}] ✗ SKIPPED: Missing orderId for {symbol}")
                    failed_count += 1
                    continue
                
                try:
                    logger.error(f"[{idx}/{len(open_orders)}] CANCELING: Order {order_id} for {symbol} (status: {order_status})")
                    cancel_result = order_manager.cancel_order(str(order_id))
                    if cancel_result and cancel_result.get('success'):
                        canceled_count += 1
                        logger.error(f"  ✓ SUCCESS: Canceled order {order_id}")
                    else:
                        error = cancel_result.get('error', 'Unknown error') if cancel_result else 'No response'
                        error_upper = str(error).upper()
                        
                        if any(term in error_upper for term in ['FILLED', 'NOT FOUND', '404', 'CANNOT BE CANCELED', 'ALREADY EXECUTED', 'ALREADY FILLED']):
                            logger.error(f"  → Order already filled/executed (OK)")
                        else:
                            failed_count += 1
                            logger.error(f"  ✗ FAILED: {error}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"  ✗ EXCEPTION: {e}")
            
            logger.error(f"ORDER CANCELLATION SUMMARY: {canceled_count} canceled, {failed_count} failed")
            
            # Brief wait to ensure cancellations are processed
            if canceled_count > 0:
                logger.error(f"Waiting 0.3s for {canceled_count} cancellation(s) to process...")
                time.sleep(0.3)
        else:
            logger.error("WARNING: get_all_open_orders() returned empty list - this may be incorrect!")
            logger.error("Attempting to proceed with position closure anyway...")
    except Exception as e:
        logger.error(f"CRITICAL EXCEPTION in order cancellation: {e}")
        import traceback
        logger.error(traceback.format_exc())
        logger.error("Continuing with position closure...")
    
    # ========================================================================
    # STEP 2: SUBMIT ALL MARKET ORDERS TO CLOSE POSITIONS (FAST - NO DB WORK)
    # ========================================================================
    logger.error("=" * 60)
    logger.error("STEP 2: SUBMITTING MARKET ORDERS TO CLOSE POSITIONS")
    logger.error("=" * 60)
    
    positions = account_client.get_positions()
    if not positions:
        logger.info("No positions to close")
        return
    
    logger.info(f"Submitting close orders for {len(positions)} position(s)...")
    
    # Store order info for database updates later
    close_orders = []  # List of (symbol, order_id, long_qty, short_qty)
    
    for pos in positions:
        symbol = pos.get('instrument', {}).get('symbol')
        long_qty = pos.get('longQuantity', 0) or 0
        short_qty = pos.get('shortQuantity', 0) or 0
        
        if not symbol:
            continue
        
        order_id = None
        
        # Submit market order to close position
        try:
            if long_qty > 0:
                result = order_manager.create_market_order(symbol, "SELL", int(long_qty))
                order_id = result.get('orderId') if isinstance(result, dict) else None
                logger.info(f"  ✓ Submitted SELL order for {symbol}: {long_qty} shares (Order ID: {order_id})")
            
            if short_qty > 0:
                result = order_manager.create_market_order(symbol, "BUY_TO_COVER", int(short_qty))
                order_id = result.get('orderId') if isinstance(result, dict) else None
                logger.info(f"  ✓ Submitted BUY_TO_COVER order for {symbol}: {short_qty} shares (Order ID: {order_id})")
            
            # Store for database update later
            if order_id:
                close_orders.append((symbol, order_id, long_qty, short_qty))
        except Exception as e:
            logger.error(f"  ✗ FAILED to submit close order for {symbol}: {e}")
    
    logger.info(f"Submitted {len(close_orders)} close order(s)")
    
    # ========================================================================
    # STEP 3: UPDATE DATABASE AFTER ALL ORDERS ARE SUBMITTED
    # ========================================================================
    if db_manager and db_manager.is_available() and close_orders:
        logger.error("=" * 60)
        logger.error("STEP 3: UPDATING DATABASE WITH EXIT PRICES")
        logger.error("=" * 60)
        
        # Brief wait for orders to start filling (market orders fill quickly)
        time.sleep(0.5)
        
        for symbol, order_id, long_qty, short_qty in close_orders:
            exit_price = None
            
            try:
                # Try to get exit price from order status (retry up to 5 times with increasing delays)
                for attempt in range(5):
                    try:
                        order_status = order_manager.get_order_status(order_id)
                        
                        if 'error' not in order_status:
                            status = order_status.get('status', '').upper()
                            
                            # Only try to get price if order is filled
                            if status == 'FILLED':
                                # Try orderActivityCollection first (most reliable for filled orders)
                                if 'orderActivityCollection' in order_status and order_status['orderActivityCollection']:
                                    activities = order_status['orderActivityCollection']
                                    for activity in activities:
                                        if 'executionLegs' in activity and activity['executionLegs']:
                                            for leg in activity['executionLegs']:
                                                if 'price' in leg:
                                                    exit_price = float(leg['price'])
                                                    logger.debug(f"Got exit price from orderActivityCollection for {symbol}: ${exit_price:.2f}")
                                                    break
                                        if exit_price:
                                            break
                                
                                # Try top-level averageFillPrice
                                if exit_price is None and 'averageFillPrice' in order_status:
                                    exit_price = float(order_status['averageFillPrice'])
                                    logger.debug(f"Got exit price from top-level averageFillPrice for {symbol}: ${exit_price:.2f}")
                                
                                # Try orderLegCollection
                                if exit_price is None and 'orderLegCollection' in order_status and len(order_status['orderLegCollection']) > 0:
                                    leg = order_status['orderLegCollection'][0]
                                    if 'executionDetails' in leg and leg['executionDetails']:
                                        executions = leg['executionDetails']
                                        if executions:
                                            total_price = 0
                                            total_quantity = 0
                                            for execution in executions:
                                                if 'price' in execution and 'quantity' in execution:
                                                    total_price += execution['price'] * execution['quantity']
                                                    total_quantity += execution['quantity']
                                            if total_quantity > 0:
                                                exit_price = total_price / total_quantity
                                                logger.debug(f"Got exit price from executionDetails for {symbol}: ${exit_price:.2f}")
                                    
                                    if exit_price is None:
                                        if 'averageFillPrice' in leg:
                                            exit_price = float(leg['averageFillPrice'])
                                        elif 'price' in leg:
                                            exit_price = float(leg['price'])
                                
                                if exit_price:
                                    break
                            elif status in ['WORKING', 'PENDING']:
                                # Order not filled yet, wait longer
                                logger.debug(f"Order {order_id} for {symbol} still {status}, waiting...")
                            else:
                                # Order in unexpected state
                                logger.debug(f"Order {order_id} for {symbol} in state: {status}")
                    except Exception as e:
                        logger.debug(f"Attempt {attempt + 1}/5 failed to get exit price for {symbol}: {e}")
                    
                    if exit_price:
                        break
                    
                    if attempt < 4:  # Don't sleep on last attempt
                        # Increasing delay: 0.5s, 1s, 1.5s, 2s
                        sleep_time = 0.5 * (attempt + 1)
                        time.sleep(sleep_time)
                
                # Fallback: get current quote
                if exit_price is None and market_data_client:
                    try:
                        quote = market_data_client.get_quote(symbol)
                        if quote and isinstance(quote, (int, float)):
                            exit_price = float(quote)
                        elif quote and isinstance(quote, dict):
                            exit_price = quote.get('lastPrice') or quote.get('last')
                            if exit_price:
                                exit_price = float(exit_price)
                    except Exception as e:
                        logger.debug(f"Could not get quote for {symbol}: {e}")
                
                # Fallback: use 0.0 (trade will be marked closed but P&L may be incorrect)
                if exit_price is None:
                    exit_price = 0.0
                    logger.error(f"❌ Could not get exit price for {symbol} - using 0.0 as fallback")
                
                # Update database
                update_success = db_manager.update_trade_on_close(
                    symbol,
                    exit_price,
                    datetime.now(pytz.UTC)
                )
                
                if update_success:
                    logger.info(f"✓ Updated {symbol} in database (exit price: ${exit_price:.2f})")
                else:
                    logger.warning(f"⚠️  Could not update {symbol} in database - no open trade found (exit price: ${exit_price:.2f})")
                    # Trade may have been closed already or never logged - this is a data integrity issue
                
            except Exception as e:
                logger.error(f"❌ Failed to update {symbol} in database: {e}")
                import traceback
                logger.error(traceback.format_exc())


def verify_stop_losses_for_all_positions(
    account_client: AccountClient,
    order_manager: OrderManager,
    trade_tracker: TradeTracker
) -> None:
    """
    Verify that all active positions have outstanding stop loss orders.
    If a position is missing a stop loss, attempt to place one.
    
    Args:
        account_client: Account client instance
        order_manager: Order manager instance
        trade_tracker: Trade tracker instance
    """
    try:
        logger.info("=" * 60)
        logger.info("Verifying stop loss orders for all positions...")
        
        # Get all positions
        positions = account_client.get_positions()
        if not positions:
            logger.info("No positions to verify")
            return
        
        # Get all open orders to check for stop loss orders
        open_orders = account_client.get_all_open_orders()
        
        # Create a map of ticker -> stop loss order info
        stop_loss_orders_by_ticker = {}
        for order in open_orders:
            order_type = order.get('orderType', '').upper()
            if order_type == 'STOP':
                # Extract ticker from order
                order_legs = order.get('orderLegCollection', [])
                if order_legs:
                    instrument = order_legs[0].get('instrument', {})
                    ticker = instrument.get('symbol', '').upper()
                    if ticker:
                        stop_loss_orders_by_ticker[ticker] = {
                            'order_id': order.get('orderId'),
                            'status': order.get('status', 'UNKNOWN')
                        }
        
        # Check each position
        missing_stops = []
        positions_with_stops = []
        
        for pos in positions:
            symbol = pos.get('instrument', {}).get('symbol', '').upper()
            if not symbol:
                continue
            
            long_qty = pos.get('longQuantity', 0) or 0
            short_qty = pos.get('shortQuantity', 0) or 0
            
            if long_qty == 0 and short_qty == 0:
                continue  # Skip flat positions
            
            # Check if position has a stop loss order
            has_stop_loss = symbol in stop_loss_orders_by_ticker
            
            if has_stop_loss:
                stop_info = stop_loss_orders_by_ticker[symbol]
                logger.info(f"✓ {symbol}: Has stop loss order (ID: {stop_info['order_id']}, Status: {stop_info['status']})")
                positions_with_stops.append(symbol)
            else:
                logger.warning(f"✗ {symbol}: MISSING stop loss order!")
                missing_stops.append({
                    'ticker': symbol,
                    'long_qty': long_qty,
                    'short_qty': short_qty
                })
        
        logger.info(f"Stop loss verification: {len(positions_with_stops)} with stops, {len(missing_stops)} missing")
        
        # Attempt to place missing stop loss orders
        if missing_stops:
            logger.warning(f"Attempting to place stop loss orders for {len(missing_stops)} position(s)...")
            
            for missing in missing_stops:
                ticker = missing['ticker']
                long_qty = missing['long_qty']
                short_qty = missing['short_qty']
                
                # Get current price for the position
                market_data_client = MarketDataClient()
                quote_data = market_data_client.get_quote_full(ticker)
                
                if not quote_data:
                    logger.error(f"Could not get quote for {ticker} to place stop loss")
                    continue
                
                # Extract price
                last_price = (
                    quote_data.get('quote', {}).get('lastPrice') or
                    quote_data.get('regular', {}).get('regularMarketLastPrice') or
                    quote_data.get('lastPrice')
                )
                
                if not last_price:
                    logger.error(f"Could not get price for {ticker} to place stop loss")
                    continue
                
                entry_price = float(last_price)
                
                # Determine direction and quantity
                if long_qty > 0:
                    direction = 'LONG'
                    quantity = int(long_qty)
                    stop_instruction = 'SELL'
                elif short_qty > 0:
                    direction = 'SHORT'
                    quantity = int(short_qty)
                    stop_instruction = 'BUY_TO_COVER'
                else:
                    continue
                
                # Place stop loss order
                from constants.parameters import STOP_LOSS_PERCENT
                logger.warning(f"Placing stop loss for {ticker} ({direction}, {quantity} shares @ ${entry_price:.2f})")
                stop_loss_result = order_manager.create_stop_loss_order(
                    ticker,
                    stop_instruction,
                    quantity,
                    entry_price,
                    STOP_LOSS_PERCENT
                )
                
                if stop_loss_result.get('orderId') or stop_loss_result.get('success'):
                    stop_loss_order_id = stop_loss_result.get('orderId', stop_loss_result.get('order_id', 'unknown'))
                    trade_tracker.set_stop_loss_order_id(ticker, stop_loss_order_id)
                    logger.info(f"✓ Placed stop loss order for {ticker} (Order ID: {stop_loss_order_id})")
                else:
                    logger.error(f"✗ Failed to place stop loss for {ticker}: {stop_loss_result.get('error', 'Unknown error')}")
        
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error verifying stop losses: {e}")
        import traceback
        traceback.print_exc()


def is_market_about_to_close(buffer_minutes: int = MARKET_CLOSE_BUFFER_MINUTES) -> bool:
    """
    Check if market is about to close within the buffer time.
    
    Args:
        buffer_minutes: Minutes before market close to consider "about to close"
    
    Returns:
        bool: True if market is about to close, False otherwise
    """
    eastern = pytz.timezone('US/Eastern')
    now_eastern = datetime.now(eastern)
    current_time = now_eastern.time()
    
    # Market closes at 16:00 ET (4:00 PM)
    # Calculate buffer time (e.g., if buffer is 5 minutes, close at 15:55)
    buffer_hour = 15
    buffer_minute = 60 - buffer_minutes
    buffer_time = datetime.strptime(f"{buffer_hour:02d}:{buffer_minute:02d}", "%H:%M").time()
    
    return current_time >= buffer_time


def supervisor_loop(account_client: AccountClient, market_data_client: MarketDataClient) -> str:
    """
    Supervisor loop that runs when market is closed.
    Checks market status and refreshes tokens.
    
    Args:
        account_client: Account client instance
        market_data_client: Market data client instance
    
    Returns:
        'trade' if market is ready for trading, 'closed' if market is closed
    """
    logger.info("=" * 60)
    logger.info("=== SUPERVISOR MODE (Market Closed) ===")
    logger.info("=" * 60)
    
    SUPERVISOR_CHECK_INTERVAL_MINUTES = 15
    
    while True:
        try:
            # Check if market is about to close - if so, don't enter trading mode
            if is_market_about_to_close():
                logger.info(f"Market closing soon (within {MARKET_CLOSE_BUFFER_MINUTES} minutes) - staying in supervisor mode")
                logger.info(f"Waiting {SUPERVISOR_CHECK_INTERVAL_MINUTES} minutes before next check...")
                time.sleep(SUPERVISOR_CHECK_INTERVAL_MINUTES * 60)
                continue
            
            # Check if market is open
            is_open, message = market_data_client.is_market_open(delay_minutes=MARKET_OPEN_DELAY_MINUTES)
            
            if is_open:
                # Double-check that market is not about to close before transitioning
                if is_market_about_to_close():
                    logger.info(f"Market is open but closing soon (within {MARKET_CLOSE_BUFFER_MINUTES} minutes) - staying in supervisor mode")
                    logger.info(f"Waiting {SUPERVISOR_CHECK_INTERVAL_MINUTES} minutes before next check...")
                    time.sleep(SUPERVISOR_CHECK_INTERVAL_MINUTES * 60)
                    continue
                
                logger.info(f"✓ {message}")
                logger.info("Market is ready for trading - transitioning to trading mode")
                return 'trade'
            else:
                logger.info(f"Market status: {message}")
                logger.info(f"Waiting {SUPERVISOR_CHECK_INTERVAL_MINUTES} minutes before next check...")
                time.sleep(SUPERVISOR_CHECK_INTERVAL_MINUTES * 60)
                
        except Exception as e:
            logger.error(f"Error in supervisor loop: {e}")
            logger.info(f"Waiting {SUPERVISOR_CHECK_INTERVAL_MINUTES} minutes before retrying...")
            time.sleep(SUPERVISOR_CHECK_INTERVAL_MINUTES * 60)


def trading_loop(
    controller: GodelTerminalController,
    account_client: AccountClient,
    market_data_client: MarketDataClient,
    order_manager: OrderManager,
    strategy: RollingStrategy,
    trade_tracker: TradeTracker
) -> None:
    """
    Main trading loop that runs when market is open.
    Executes rolling strategy and monitors positions.
    
    Args:
        controller: Godel Terminal controller
        account_client: Account client instance
        market_data_client: Market data client instance
        order_manager: Order manager instance
        strategy: Rolling strategy instance
        trade_tracker: Trade tracker instance
    """
    logger.info("=" * 60)
    logger.info("=== TRADING MODE ===")
    logger.info("=" * 60)
    logger.info(f"Market open delay: {MARKET_OPEN_DELAY_MINUTES} minutes")
    logger.info(f"Market close buffer: {MARKET_CLOSE_BUFFER_MINUTES} minutes")
    logger.info(f"Max hold time: {MAX_HOLD_TIME_MINUTES} minutes")
    logger.info(f"PRT recheck interval: {PRT_RECHECK_INTERVAL_SECONDS} seconds ({PRT_RECHECK_INTERVAL_SECONDS / 60:.1f} minutes)")
    logger.info("=" * 60)
    
    cycle_interval_seconds = PRT_RECHECK_INTERVAL_SECONDS
    logger.info(f"Cycle interval set to: {cycle_interval_seconds} seconds")
    
    # Initialize account size monitor
    account_monitor = AccountSizeMonitor(account_client)
    last_account_check = datetime.now()
    account_check_interval = timedelta(minutes=ACCOUNT_SIZE_CHECK_INTERVAL_MINUTES)
    
    # Get initial account value for drawdown monitoring
    logger.info("Getting initial account value for drawdown monitoring...")
    initial_metrics = account_monitor.get_account_metrics()
    initial_account_value = initial_metrics.get('account_value')
    
    if initial_account_value is None or initial_account_value == '':
        logger.error("⚠️  Could not retrieve initial account value - drawdown monitoring disabled")
        initial_account_value = None
    else:
        try:
            initial_account_value = float(initial_account_value)
            logger.info(f"✅ Initial account value: ${initial_account_value:,.2f}")
            logger.info(f"🛡️  Drawdown safeguard active: Will shutdown if account drops {MAX_DRAWDOWN_PERCENT}% (${initial_account_value * MAX_DRAWDOWN_PERCENT / 100:,.2f})")
        except (ValueError, TypeError):
            logger.error("⚠️  Invalid initial account value - drawdown monitoring disabled")
            initial_account_value = None
    
    # Log initial account size (only if not about to close)
    if not is_market_about_to_close():
        logger.info("Logging initial account size...")
        account_monitor.log_account_size()
    else:
        logger.info("Skipping initial account size log - market closing soon")
    
    try:
        while True:
            # Check if market is still open
            is_open, message = market_data_client.is_market_open(delay_minutes=0)
            if not is_open:
                logger.warning(f"Market no longer open: {message}")
                break
            
            # Check if market is about to close (within buffer time)
            # Follows RULES.md: Must close positions within 5 minutes of market close
            if is_market_about_to_close():
                logger.warning(f"Market closing soon (within {MARKET_CLOSE_BUFFER_MINUTES} minutes) - closing all positions")
                # Pass db_manager and market_data_client from strategy if available
                db_mgr = strategy.db_manager if strategy and hasattr(strategy, 'db_manager') else None
                close_all_positions_before_market_close(
                    order_manager, account_client, reason="market close",
                    db_manager=db_mgr, market_data_client=market_data_client
                )
                break
            
            # Check for expired trades (exceeding max hold time)
            expired_trades = trade_tracker.get_expired_trades()
            if expired_trades:
                logger.info(f"Found {len(expired_trades)} expired trade(s) - closing positions")
                positions = account_client.get_positions()
                if positions:
                    # Get db_manager from strategy if available
                    db_mgr = strategy.db_manager if strategy and hasattr(strategy, 'db_manager') else None
                    for pos in positions:
                        symbol = pos.get('instrument', {}).get('symbol', '').upper()
                        if symbol in expired_trades:
                            long_qty = pos.get('longQuantity', 0)
                            short_qty = pos.get('shortQuantity', 0)
                            
                            # Get exit price before closing (for database update)
                            exit_price = None
                            if db_mgr and market_data_client and db_mgr.is_available():
                                try:
                                    quote = market_data_client.get_quote(symbol)
                                    if quote:
                                        exit_price = quote.get('lastPrice') or quote.get('last')
                                except Exception as e:
                                    logger.debug(f"Could not get quote for {symbol}: {e}")
                            
                            order_id = None
                            if long_qty > 0:
                                result = order_manager.create_market_order(symbol, "SELL", int(long_qty))
                                order_id = result.get('orderId') if isinstance(result, dict) else None
                                trade_tracker.remove_trade(symbol)
                            elif short_qty > 0:
                                result = order_manager.create_market_order(symbol, "BUY_TO_COVER", int(short_qty))
                                order_id = result.get('orderId') if isinstance(result, dict) else None
                                trade_tracker.remove_trade(symbol)
                            
                            # CRITICAL: Always update trade in database, even if exit price retrieval fails
                            if db_mgr and db_mgr.is_available():
                                try:
                                    # Try to get exit price from order if available (more accurate than quote)
                                    if order_id:
                                        try:
                                            order_status = order_manager.get_order_status(order_id)
                                            
                                            # Check for error in response
                                            if 'error' not in order_status:
                                                # Try top-level averageFillPrice first
                                                if 'averageFillPrice' in order_status:
                                                    exit_price = float(order_status['averageFillPrice'])
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
                                                    # Fallback to other leg fields
                                                    if exit_price is None:
                                                        if 'averageFillPrice' in leg:
                                                            exit_price = float(leg['averageFillPrice'])
                                                        elif 'averagePrice' in leg:
                                                            exit_price = float(leg['averagePrice'])
                                                        elif 'filledPrice' in leg:
                                                            exit_price = float(leg['filledPrice'])
                                                        elif 'price' in leg:
                                                            exit_price = float(leg['price'])
                                                # Try top-level price
                                                elif 'price' in order_status:
                                                    exit_price = float(order_status['price'])
                                        except Exception as e:
                                            logger.debug(f"Could not get exit price from order {order_id} for {symbol}: {e}")
                                    
                                    # Fallback: get current quote if we still don't have exit price
                                    if exit_price is None and market_data_client:
                                        try:
                                            quote = market_data_client.get_quote(symbol)
                                            if quote:
                                                exit_price = quote.get('lastPrice') or quote.get('last')
                                        except Exception as e:
                                            logger.debug(f"Could not get quote for {symbol}: {e}")
                                    
                                    # Fallback: get entry price from database as last resort
                                    if exit_price is None:
                                        try:
                                            cursor = db_mgr.connection.cursor()
                                            find_query = "SELECT entry_price FROM trades WHERE ticker = %s AND is_closed = FALSE ORDER BY time_placed DESC LIMIT 1"
                                            cursor.execute(find_query, (symbol.upper(),))
                                            trade = cursor.fetchone()
                                            cursor.close()
                                            if trade and trade[0]:
                                                exit_price = float(trade[0])
                                                logger.warning(f"⚠️  Using entry price as fallback exit price for {symbol} (could not get actual exit price)")
                                        except Exception as e:
                                            logger.debug(f"Could not get entry price from database for {symbol}: {e}")
                                    
                                    # If we still don't have an exit price, use 0.0 as absolute last resort
                                    if exit_price is None:
                                        exit_price = 0.0
                                        logger.error(f"❌ CRITICAL: Could not get exit price for {symbol} - using 0.0 as fallback. Trade will be marked as closed but P&L may be incorrect.")
                                    
                                    db_mgr.update_trade_on_close(
                                        symbol,
                                        exit_price,
                                        datetime.now(pytz.UTC)
                                    )
                                    logger.info(f"✓ Updated expired trade {symbol} in database (exit price: ${exit_price:.2f})")
                                except Exception as e:
                                    logger.error(f"❌ CRITICAL: Could not update expired trade {symbol} in database: {e}")
                                    import traceback
                                    logger.error(traceback.format_exc())
                            elif db_mgr:
                                logger.warning(f"⚠️  Database not available - could not update expired trade {symbol} in database")
            
            # Check and log account size periodically
            now = datetime.now()
            if now - last_account_check >= account_check_interval:
                logger.info("Checking account size...")
                account_monitor.log_account_size()
                
                # Check for drawdown if initial value was recorded
                if initial_account_value is not None:
                    current_metrics = account_monitor.get_account_metrics()
                    current_account_value = current_metrics.get('account_value')
                    
                    if current_account_value is not None and current_account_value != '':
                        try:
                            current_account_value = float(current_account_value)
                            drawdown = initial_account_value - current_account_value
                            drawdown_percent = (drawdown / initial_account_value) * 100
                            
                            if drawdown_percent >= MAX_DRAWDOWN_PERCENT:
                                logger.critical("=" * 60)
                                logger.critical("🚨 EMERGENCY SHUTDOWN TRIGGERED 🚨")
                                logger.critical("=" * 60)
                                logger.critical(f"Account drawdown exceeded threshold!")
                                logger.critical(f"Initial value: ${initial_account_value:,.2f}")
                                logger.critical(f"Current value: ${current_account_value:,.2f}")
                                logger.critical(f"Drawdown: ${drawdown:,.2f} ({drawdown_percent:.2f}%)")
                                logger.critical(f"Threshold: {MAX_DRAWDOWN_PERCENT}%")
                                logger.critical("=" * 60)
                                logger.critical("Closing all positions and shutting down...")
                                db_mgr = strategy.db_manager if strategy and hasattr(strategy, 'db_manager') else None
                                close_all_positions_before_market_close(
                                    order_manager, account_client, reason="drawdown safeguard",
                                    db_manager=db_mgr, market_data_client=market_data_client
                                )
                                raise SystemExit("Emergency shutdown due to drawdown threshold exceeded")
                            elif drawdown_percent > 0:
                                logger.warning(f"⚠️  Account drawdown: ${drawdown:,.2f} ({drawdown_percent:.2f}%) - Threshold: {MAX_DRAWDOWN_PERCENT}%")
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Could not parse account value for drawdown check: {e}")
                
                last_account_check = now
            
            # Execute rolling strategy cycle
            logger.info("Executing rolling strategy cycle...")
            results = strategy.execute_cycle()
            
            if results['success']:
                logger.info(f"Cycle completed: {results.get('trades_opened', 0)} opened, {results.get('trades_closed', 0)} closed")
            else:
                logger.warning(f"Cycle had errors: {results.get('errors', [])}")
            
            # Verify all positions have stop loss orders before waiting
            verify_stop_losses_for_all_positions(account_client, order_manager, trade_tracker)
            
            # Wait before next cycle with periodic checks
            # CRITICAL: Use PRT_RECHECK_INTERVAL_SECONDS parameter (not hardcoded)
            # Use timer-based approach: calculate end time and check against it
            # This ensures we wait the full duration regardless of API call delays
            wait_seconds = PRT_RECHECK_INTERVAL_SECONDS
            wait_start_time = datetime.now()
            wait_end_time = wait_start_time + timedelta(seconds=wait_seconds)
            
            logger.warning(f"⏸️  Waiting {wait_seconds} seconds ({wait_seconds / 60:.1f} minutes) before next PRT cycle...")
            logger.warning(f"   (Parameter PRT_RECHECK_INTERVAL_SECONDS = {PRT_RECHECK_INTERVAL_SECONDS})")
            logger.warning(f"   Wait started at {wait_start_time.strftime('%H:%M:%S')}, will end at {wait_end_time.strftime('%H:%M:%S')}")
            
            # Check interval for monitoring (smaller chunks for more responsive checks)
            check_interval = 30  # Check every 30 seconds
            
            while datetime.now() < wait_end_time:
                # Calculate remaining time
                remaining = (wait_end_time - datetime.now()).total_seconds()
                
                if remaining <= 0:
                    break
                
                # Sleep for check_interval or remaining time, whichever is smaller
                sleep_time = min(check_interval, remaining)
                time.sleep(sleep_time)
                
                # Check market status during wait
                is_open, message = market_data_client.is_market_open(delay_minutes=0)
                if not is_open:
                    logger.warning(f"Market closed during wait: {message}")
                    break
                
                # Check if market is about to close
                if is_market_about_to_close():
                    logger.warning(f"Market closing soon (within {MARKET_CLOSE_BUFFER_MINUTES} minutes) - closing all positions")
                    db_mgr = strategy.db_manager if strategy and hasattr(strategy, 'db_manager') else None
                    close_all_positions_before_market_close(
                        order_manager, account_client, reason="market close",
                        db_manager=db_mgr, market_data_client=market_data_client
                    )
                    break
                
                # Check and update trailing stop losses periodically during wait
                # Update stop losses for positions that are up 1%+ to lock in gains
                # Only updates again if price has moved up another 1% from last update
                if strategy and hasattr(strategy, '_update_trailing_stop_losses'):
                    try:
                        updated = strategy._update_trailing_stop_losses()
                        if updated > 0:
                            logger.info(f"Trailing stop losses updated: {updated} position(s)")
                    except Exception as e:
                        logger.debug(f"Error updating trailing stop losses: {e}")
                
                # Check and log account size periodically during wait
                now = datetime.now()
                if now - last_account_check >= account_check_interval:
                    logger.info("Checking account size during wait...")
                    account_monitor.log_account_size()
                    
                    # Check for drawdown if initial value was recorded
                    if initial_account_value is not None:
                        current_metrics = account_monitor.get_account_metrics()
                        current_account_value = current_metrics.get('account_value')
                        
                        if current_account_value is not None and current_account_value != '':
                            try:
                                current_account_value = float(current_account_value)
                                drawdown = initial_account_value - current_account_value
                                drawdown_percent = (drawdown / initial_account_value) * 100
                                
                                if drawdown_percent >= MAX_DRAWDOWN_PERCENT:
                                    logger.critical("=" * 60)
                                    logger.critical("🚨 EMERGENCY SHUTDOWN TRIGGERED 🚨")
                                    logger.critical("=" * 60)
                                    logger.critical(f"Account drawdown exceeded threshold!")
                                    logger.critical(f"Initial value: ${initial_account_value:,.2f}")
                                    logger.critical(f"Current value: ${current_account_value:,.2f}")
                                    logger.critical(f"Drawdown: ${drawdown:,.2f} ({drawdown_percent:.2f}%)")
                                    logger.critical(f"Threshold: {MAX_DRAWDOWN_PERCENT}%")
                                    logger.critical("=" * 60)
                                    logger.critical("Closing all positions and shutting down...")
                                    db_mgr = strategy.db_manager if strategy and hasattr(strategy, 'db_manager') else None
                                    close_all_positions_before_market_close(
                                        order_manager, account_client, reason="drawdown safeguard",
                                        db_manager=db_mgr, market_data_client=market_data_client
                                    )
                                    raise SystemExit("Emergency shutdown due to drawdown threshold exceeded")
                                elif drawdown_percent > 0:
                                    logger.warning(f"⚠️  Account drawdown: ${drawdown:,.2f} ({drawdown_percent:.2f}%) - Threshold: {MAX_DRAWDOWN_PERCENT}%")
                            except (ValueError, TypeError) as e:
                                logger.warning(f"Could not parse account value for drawdown check: {e}")
                    
                    last_account_check = now
                
                # Log remaining wait time
                remaining = (wait_end_time - datetime.now()).total_seconds()
                if remaining > 0:
                    logger.debug(f"  {int(remaining)} seconds remaining in wait period...")
            
    except KeyboardInterrupt:
        logger.info("Trading loop interrupted by user")
        raise
    except Exception as e:
        logger.error(f"Error in trading loop: {e}")
        import traceback
        traceback.print_exc()
        raise


def main():
    """Main startup function - initializes and starts trading"""
    logger.info("=" * 60)
    logger.info("=== ALGOBOT V2 TRADING SYSTEM STARTING ===")
    logger.info("=" * 60)
    
    # Check prerequisites
    if not check_prerequisites():
        logger.error("Prerequisites check failed. Please fix issues and try again.")
        return False
    
    # Initialize Schwab API clients
    account_client = None
    market_data_client = None
    order_manager = None
    controller = None
    strategy = None  # Store strategy reference for cleanup handlers
    
    try:
        logger.info("Initializing Schwab API clients...")
        account_client = AccountClient()
        market_data_client = MarketDataClient()
        order_manager = OrderManager(account_client, market_data_client)
        logger.info("✓ Schwab API clients initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Schwab API clients: {e}")
        logger.error("Make sure tokens are acquired")
        return False
    
    # Register cleanup function
    def cleanup_on_exit():
        if account_client and order_manager:
            logger.warning("Program exiting - closing all positions...")
            # Get db_manager from strategy if available
            db_mgr = strategy.db_manager if strategy and hasattr(strategy, 'db_manager') else None
            close_all_positions_before_market_close(
                order_manager, account_client, reason="program exit",
                db_manager=db_mgr, market_data_client=market_data_client
            )
    
    atexit.register(cleanup_on_exit)
    
    # Register signal handlers
    def signal_handler(signum, frame):
        logger.warning(f"Received signal {signum} - closing all positions and exiting...")
        if account_client and order_manager:
            # Get db_manager from strategy if available
            db_mgr = strategy.db_manager if strategy and hasattr(strategy, 'db_manager') else None
            close_all_positions_before_market_close(
                order_manager, account_client, reason="signal handler",
                db_manager=db_mgr, market_data_client=market_data_client
            )
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    MAIN_LOOP_RETRY_DELAY_SECONDS = 1  # Quick retry on errors
    
    # Main program loop
    while True:
        try:
            # ============================================================
            # SUPERVISOR LOOP - Runs when market is closed or not ready
            # ============================================================
            supervisor_result = supervisor_loop(account_client, market_data_client)
            
            if supervisor_result == 'closed':
                # Market closed for the day
                logger.info("📅 Market closed for today - entering overnight mode")
                SUPERVISOR_CHECK_INTERVAL_MINUTES = 15
                logger.info(f"Will check again in {SUPERVISOR_CHECK_INTERVAL_MINUTES} minutes...")
                time.sleep(SUPERVISOR_CHECK_INTERVAL_MINUTES * 60)
                continue
            
            # ============================================================
            # TRADING LOOP - Runs when market is open and ready
            # ============================================================
            
            # Initialize Godel controller when transitioning to trading
            if controller is None:
                logger.info("🔌 Initializing Godel controller...")
                try:
                    controller = initialize_godel_controller(headless=False)
                    logger.info("✅ Godel controller initialized successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize Godel controller: {e}")
                    logger.info(f"Waiting {MAIN_LOOP_RETRY_DELAY_SECONDS} seconds before retrying...")
                    time.sleep(MAIN_LOOP_RETRY_DELAY_SECONDS)
                    continue
            
            # Initialize strategy and tracker
            trade_tracker = TradeTracker()
            strategy = RollingStrategy(controller, account_client, market_data_client, trade_tracker, order_manager)
            # Store strategy reference for cleanup handlers (needed for db_manager access)
            
            # Run the trading loop
            logger.info("=" * 60)
            logger.info("=== ENTERING TRADING MODE ===")
            logger.info("=" * 60)
            
            trading_loop(controller, account_client, market_data_client, order_manager, strategy, trade_tracker)
            
            # Trading loop exited (market closed or error)
            logger.info("📉 Trading loop exited - returning to supervisor")
            
        except KeyboardInterrupt:
            logger.info("\n🛑 Program interrupted by user - shutting down...")
            break
        except Exception as e:
            logger.error(f"❌ Error in main loop: {e}")
            import traceback
            traceback.print_exc()
            logger.info(f"Waiting {MAIN_LOOP_RETRY_DELAY_SECONDS} seconds before retrying...")
            time.sleep(MAIN_LOOP_RETRY_DELAY_SECONDS)
    
    # ============================================================
    # CLEANUP - Runs on program exit
    # ============================================================
    logger.info("=" * 60)
    logger.info("=== SHUTTING DOWN ===")
    logger.info("=" * 60)
    
    if account_client and order_manager:
        logger.warning("Closing all positions...")
        # Get db_manager from strategy if available
        db_mgr = strategy.db_manager if strategy and hasattr(strategy, 'db_manager') else None
        close_all_positions_before_market_close(
            order_manager, account_client, reason="shutdown",
            db_manager=db_mgr, market_data_client=market_data_client
        )
    
    if controller:
        try:
            logger.info("Cleaning up Godel controller...")
            controller.close_all_windows()
            controller.disconnect()
            logger.info("✅ Controller closed successfully")
        except Exception as e:
            logger.error(f"Error closing controller: {e}")
    
    logger.info("👋 Goodbye!")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

