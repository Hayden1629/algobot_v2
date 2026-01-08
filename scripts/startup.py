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
import pytz
import os

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.init import init_database, database_exists
from schwab.tokens.storage import token_file_exists, get_token_file_path
from schwab.tokens.acquisition import acquire_tokens
from constants.parameters import (
    GODEL_USERNAME,
    GODEL_PASSWORD,
    MARKET_OPEN_DELAY_MINUTES,
    MARKET_CLOSE_BUFFER_MINUTES,
    MAX_HOLD_TIME_MINUTES,
    ACCOUNT_SIZE_CHECK_INTERVAL_MINUTES,
    PRT_RECHECK_INTERVAL_SECONDS
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
    reason: str = "market close"
) -> None:
    """
    Close all positions before market close (emergency use).
    Follows RULES.md: Must close positions within 5 minutes of market close.
    Cancels all outstanding orders (including stop losses) before closing positions.
    
    Args:
        order_manager: Order manager instance
        account_client: Account client instance
        reason: Reason for closing positions
    """
    logger.error("=" * 60)
    logger.error(f"EMERGENCY: Closing all positions - {reason}")
    logger.error("=" * 60)
    
    # CRITICAL STEP 1: Cancel ALL outstanding orders FIRST (including stop losses)
    # This MUST happen before attempting to close positions
    logger.error("STEP 1: CANCELING ALL OUTSTANDING ORDERS (INCLUDING STOP LOSSES)")
    logger.error("=" * 60)
    
    canceled_count = 0
    failed_count = 0
    
    try:
        logger.error("Calling get_all_open_orders()...")
        open_orders = account_client.get_all_open_orders()
        logger.error(f"API returned: {len(open_orders) if open_orders else 0} order(s)")
        
        if not open_orders:
            logger.error("WARNING: get_all_open_orders() returned empty list - this may be incorrect!")
            logger.error("Attempting to proceed with position closure anyway...")
        elif len(open_orders) > 0:
            logger.error(f"FOUND {len(open_orders)} OUTSTANDING ORDER(S) - CANCELING ALL NOW")
            
            for idx, order in enumerate(open_orders, 1):
                order_id = order.get('orderId') or order.get('order_id')
                order_status = order.get('status', 'UNKNOWN')
                symbol = order.get('orderLegCollection', [{}])[0].get('instrument', {}).get('symbol', 'UNKNOWN')
                
                logger.error(f"[{idx}/{len(open_orders)}] CANCELING: Order {order_id} for {symbol} (status: {order_status})")
                
                if not order_id:
                    logger.error(f"  ✗ SKIPPED: Order missing orderId - {order}")
                    failed_count += 1
                    continue
                
                try:
                    cancel_result = order_manager.cancel_order(str(order_id))
                    if cancel_result and cancel_result.get('success'):
                        canceled_count += 1
                        logger.error(f"  ✓ SUCCESS: Canceled order {order_id}")
                    else:
                        error = cancel_result.get('error', 'Unknown error') if cancel_result else 'No response'
                        error_upper = str(error).upper()
                        
                        if any(term in error_upper for term in ['FILLED', 'NOT FOUND', '404', 'CANNOT BE CANCELED', 'ALREADY EXECUTED', 'ALREADY FILLED']):
                            logger.error(f"  → Order {order_id} already filled/executed (OK to skip)")
                        else:
                            failed_count += 1
                            logger.error(f"  ✗ FAILED: Could not cancel order {order_id}: {error}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"  ✗ EXCEPTION canceling order {order_id}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            logger.error(f"ORDER CANCELLATION SUMMARY: {canceled_count} canceled, {failed_count} failed")
            
            # CRITICAL: Wait to ensure cancellations are processed
            if canceled_count > 0:
                logger.error(f"Waiting 3 seconds for {canceled_count} cancellation(s) to process...")
                time.sleep(3)
            elif len(open_orders) > 0:
                logger.error("No orders were successfully canceled - waiting 2 seconds anyway...")
                time.sleep(2)
            else:
                time.sleep(1)
        else:
            logger.error("No outstanding orders found")
    except Exception as e:
        logger.error(f"CRITICAL EXCEPTION in order cancellation: {e}")
        import traceback
        logger.error(traceback.format_exc())
        logger.error("Continuing with position closure despite error...")
        time.sleep(2)  # Wait anyway
    
    logger.error("=" * 60)
    logger.error("STEP 2: NOW CLOSING ALL POSITIONS")
    logger.error("=" * 60)
    
    # Step 2: Close all positions
    positions = account_client.get_positions()
    if not positions:
        logger.info("No positions to close")
        return
    
    logger.info(f"Closing {len(positions)} position(s)...")
    
    for pos in positions:
        symbol = pos.get('instrument', {}).get('symbol')
        long_qty = pos.get('longQuantity', 0)
        short_qty = pos.get('shortQuantity', 0)
        
        if not symbol:
            continue
        
        if long_qty > 0:
            order_manager.create_market_order(symbol, "SELL", int(long_qty))
            logger.info(f"Closed long position: {symbol} {long_qty} shares")
        
        if short_qty > 0:
            order_manager.create_market_order(symbol, "BUY_TO_COVER", int(short_qty))
            logger.info(f"Closed short position: {symbol} {short_qty} shares")


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
            # Check if market is open
            is_open, message = market_data_client.is_market_open(delay_minutes=MARKET_OPEN_DELAY_MINUTES)
            
            if is_open:
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
    
    # Log initial account size
    logger.info("Logging initial account size...")
    account_monitor.log_account_size()
    
    try:
        while True:
            # Check if market is still open
            is_open, message = market_data_client.is_market_open(delay_minutes=0)
            if not is_open:
                logger.warning(f"Market no longer open: {message}")
                break
            
            # Check if market is about to close (within buffer time)
            # Follows RULES.md: Must close positions within 5 minutes of market close
            eastern = pytz.timezone('US/Eastern')
            now_eastern = datetime.now(eastern)
            current_time = now_eastern.time()
            
            # Market closes at 16:00 ET (4:00 PM)
            # Calculate buffer time (e.g., if buffer is 5 minutes, close at 15:55)
            buffer_hour = 15
            buffer_minute = 60 - MARKET_CLOSE_BUFFER_MINUTES
            buffer_time = datetime.strptime(f"{buffer_hour:02d}:{buffer_minute:02d}", "%H:%M").time()
            
            if current_time >= buffer_time:
                logger.warning(f"Market closing soon (within {MARKET_CLOSE_BUFFER_MINUTES} minutes) - closing all positions")
                close_all_positions_before_market_close(order_manager, account_client, reason="market close")
                break
            
            # Check for expired trades (exceeding max hold time)
            expired_trades = trade_tracker.get_expired_trades()
            if expired_trades:
                logger.info(f"Found {len(expired_trades)} expired trade(s) - closing positions")
                positions = account_client.get_positions()
                if positions:
                    for pos in positions:
                        symbol = pos.get('instrument', {}).get('symbol', '').upper()
                        if symbol in expired_trades:
                            long_qty = pos.get('longQuantity', 0)
                            short_qty = pos.get('shortQuantity', 0)
                            
                            if long_qty > 0:
                                order_manager.create_market_order(symbol, "SELL", int(long_qty))
                                trade_tracker.remove_trade(symbol)
                            elif short_qty > 0:
                                order_manager.create_market_order(symbol, "BUY_TO_COVER", int(short_qty))
                                trade_tracker.remove_trade(symbol)
            
            # Check and log account size periodically
            now = datetime.now()
            if now - last_account_check >= account_check_interval:
                logger.info("Checking account size...")
                account_monitor.log_account_size()
                last_account_check = now
            
            # Execute rolling strategy cycle
            logger.info("Executing rolling strategy cycle...")
            results = strategy.execute_cycle()
            
            if results['success']:
                logger.info(f"Cycle completed: {results.get('trades_opened', 0)} opened, {results.get('trades_closed', 0)} closed")
            else:
                logger.warning(f"Cycle had errors: {results.get('errors', [])}")
            
            # Wait before next cycle
            # CRITICAL: Use PRT_RECHECK_INTERVAL_SECONDS parameter (not hardcoded)
            wait_seconds = PRT_RECHECK_INTERVAL_SECONDS
            logger.warning(f"⏸️  Waiting {wait_seconds} seconds ({wait_seconds / 60:.1f} minutes) before next PRT cycle...")
            logger.warning(f"   (Parameter PRT_RECHECK_INTERVAL_SECONDS = {PRT_RECHECK_INTERVAL_SECONDS})")
            time.sleep(wait_seconds)
            
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
            close_all_positions_before_market_close(order_manager, account_client, reason="program exit")
    
    atexit.register(cleanup_on_exit)
    
    # Register signal handlers
    def signal_handler(signum, frame):
        logger.warning(f"Received signal {signum} - closing all positions and exiting...")
        if account_client and order_manager:
            close_all_positions_before_market_close(order_manager, account_client, reason="signal handler")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    MAIN_LOOP_RETRY_DELAY_SECONDS = 60
    
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
        close_all_positions_before_market_close(order_manager, account_client, reason="shutdown")
    
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

