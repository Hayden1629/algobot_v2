"""
Main algorithm loop for algobot_v2.
Boots database, gets tokens, starts the algo loop, and begins trading.

This script:
1. Initializes database
2. Checks/acquires tokens
3. Initializes Godel Terminal controller
4. Initializes Schwab API clients
5. Runs rolling strategy in a loop
6. Monitors market hours and closes positions before market close
7. Handles cleanup on exit
"""
import sys
import time
import signal
import atexit
from pathlib import Path
from loguru import logger
from datetime import datetime, timedelta
import pytz

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.init import init_database, database_exists
from schwab.tokens.storage import token_file_exists
from schwab.tokens.acquisition import acquire_tokens
from constants.parameters import (
    GODEL_USERNAME,
    GODEL_PASSWORD,
    MARKET_OPEN_DELAY_MINUTES,
    MARKET_CLOSE_BUFFER_MINUTES,
    MAX_HOLD_TIME_MINUTES
)
from core.controller import GodelTerminalController
from schwab.account.client import AccountClient
from schwab.market_data.client import MarketDataClient
from schwab.account.orders import OrderManager
from strategy.rolling_strategy import RollingStrategy
from strategy.trade_tracker import TradeTracker


# Supervisor loop constants
SUPERVISOR_CHECK_INTERVAL_MINUTES = 15  # Check market status every 15 minutes when closed
MAIN_LOOP_RETRY_DELAY_SECONDS = 60  # Wait before retrying after error


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
    if not token_file_exists():
        logger.warning("Token file not found")
        logger.info("Starting token acquisition...")
        if not acquire_tokens():
            logger.error("Failed to acquire tokens")
            return False
        logger.info("✓ Tokens acquired")
    else:
        logger.info("✓ Token file exists")
    
    return True


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


def close_all_positions_before_market_close(
    order_manager: OrderManager,
    account_client: AccountClient,
    reason: str = "market close"
) -> None:
    """
    Close all positions before market close (emergency use).
    Follows RULES.md: Must close positions within 5 minutes of market close.
    
    Args:
        order_manager: Order manager instance
        account_client: Account client instance
        reason: Reason for closing positions
    """
    logger.warning(f"Closing all positions: {reason}")
    
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
    logger.info("=" * 60)
    
    cycle_interval_seconds = 60  # Run strategy cycle every 60 seconds
    
    try:
        while True:
            # Check if market is still open
            is_open, message = market_data_client.is_market_open(delay_minutes=0)
            if not is_open:
                logger.warning(f"Market no longer open: {message}")
                break
            
            # Check if market is about to close (within buffer time)
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
            
            # Execute rolling strategy cycle
            logger.info("Executing rolling strategy cycle...")
            results = strategy.execute_cycle()
            
            if results['success']:
                logger.info(f"Cycle completed: {results.get('trades_opened', 0)} opened, {results.get('trades_closed', 0)} closed")
            else:
                logger.warning(f"Cycle had errors: {results.get('errors', [])}")
            
            # Wait before next cycle
            logger.debug(f"Waiting {cycle_interval_seconds} seconds before next cycle...")
            time.sleep(cycle_interval_seconds)
            
    except KeyboardInterrupt:
        logger.info("Trading loop interrupted by user")
        raise
    except Exception as e:
        logger.error(f"Error in trading loop: {e}")
        import traceback
        traceback.print_exc()
        raise


def main():
    """Main entry point for the trading algorithm."""
    logger.info("=" * 60)
    logger.info("=== ALGOBOT V2 TRADING SYSTEM STARTING ===")
    logger.info("=" * 60)
    
    # Check prerequisites
    if not check_prerequisites():
        logger.error("Prerequisites check failed. Please fix issues and try again.")
        return
    
    # Initialize Schwab API clients
    account_client = None
    market_data_client = None
    order_manager = None
    
    try:
        logger.info("Initializing Schwab API clients...")
        account_client = AccountClient()
        market_data_client = MarketDataClient()
        order_manager = OrderManager(account_client, market_data_client)
        logger.info("✓ Schwab API clients initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Schwab API clients: {e}")
        logger.error("Make sure tokens are acquired (run schwab.tokens.acquisition.acquire_tokens())")
        return
    
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
    
    # Controller for Godel terminal (initialized when needed)
    controller = None
    
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
                    controller = GodelTerminalController(headless=False)
                    controller.connect()
                    controller.login(GODEL_USERNAME, GODEL_PASSWORD)
                    controller.load_layout("dev")
                    controller.open_terminal()
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


if __name__ == "__main__":
    main()

