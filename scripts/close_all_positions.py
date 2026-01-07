"""
Emergency Position Closer - Closes all open positions immediately.
Run this script if something goes wrong with the main algo.

This script:
1. Cancels all open orders (stop losses, etc.)
2. Closes all positions with market orders (emergency use only)

Follows RULES.md: Use limit orders when possible, but this is emergency use.
"""
import sys
from pathlib import Path
from loguru import logger

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from schwab.account.client import AccountClient
from schwab.account.orders import OrderManager
from schwab.market_data.client import MarketDataClient


def get_open_orders(account_client: AccountClient) -> list:
    """
    Get all open/pending orders.
    
    Args:
        account_client: Account client instance
    
    Returns:
        list: List of open orders
    """
    return account_client.get_all_open_orders()


def get_positions(account_client: AccountClient) -> list:
    """
    Get all open positions.
    
    Args:
        account_client: Account client instance
    
    Returns:
        list: List of positions
    """
    positions = account_client.get_positions()
    if positions is None:
        return []
    return positions


def close_position(order_manager: OrderManager, symbol: str, quantity: float, is_long: bool = True) -> dict:
    """
    Close a position with a market order (emergency use only).
    
    Args:
        order_manager: Order manager instance
        symbol: Stock ticker symbol
        quantity: Number of shares
        is_long: True if long position, False if short
    
    Returns:
        dict: Order result
    """
    instruction = "SELL" if is_long else "BUY_TO_COVER"
    
    result = order_manager.create_market_order(symbol, instruction, int(abs(quantity)))
    
    if 'orderId' in result or 'success' in result:
        order_id = result.get('orderId', 'unknown')
        logger.info(f"✓ Closed {symbol}: {instruction} {int(abs(quantity))} shares (Order ID: {order_id})")
        return {'success': True, 'orderId': order_id}
    else:
        logger.error(f"✗ Failed to close {symbol}: {result}")
        return result


def main():
    """Main function for emergency position closer."""
    print("\n" + "="*60)
    print("  EMERGENCY POSITION CLOSER")
    print("  This will cancel ALL orders and close ALL positions")
    print("="*60 + "\n")
    
    # Confirm before proceeding
    confirm = input("Are you sure? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return
    
    try:
        # Initialize clients
        logger.info("Initializing Schwab API clients...")
        account_client = AccountClient()
        market_data_client = MarketDataClient()
        order_manager = OrderManager(account_client, market_data_client)
        
        logger.info(f"Connected to account: {account_client.account_hash_value[:8]}...")
        
        # ===== STEP 1: Cancel all open orders =====
        logger.info("\n--- STEP 1: Cancelling all open orders ---")
        open_orders = get_open_orders(account_client)
        
        if open_orders:
            logger.info(f"Found {len(open_orders)} open order(s) to cancel")
            for order in open_orders:
                order_id = order.get('orderId')
                order_legs = order.get('orderLegCollection', [{}])
                symbol = order_legs[0].get('instrument', {}).get('symbol', 'Unknown') if order_legs else 'Unknown'
                order_type = order.get('orderType', 'Unknown')
                status = order.get('status', 'Unknown')
                
                logger.info(f"  Cancelling {order_type} order for {symbol} (ID: {order_id}, Status: {status})")
                result = order_manager.cancel_order(str(order_id))
                if 'error' in result:
                    logger.warning(f"    Could not cancel: {result.get('error')}")
        else:
            logger.info("No open orders found")
        
        # ===== STEP 2: Get and close all positions =====
        logger.info("\n--- STEP 2: Closing all positions ---")
        positions = get_positions(account_client)
        
        if not positions:
            logger.info("No open positions found. Done!")
            return
        
        logger.info(f"Found {len(positions)} position(s)")
        print("-" * 40)
        
        # Display positions
        for pos in positions:
            symbol = pos.get('instrument', {}).get('symbol', 'Unknown')
            quantity = pos.get('longQuantity', 0) - pos.get('shortQuantity', 0)
            avg_price = pos.get('averagePrice', 0)
            market_value = pos.get('marketValue', 0)
            position_type = "LONG" if quantity > 0 else "SHORT"
            print(f"  {symbol}: {abs(quantity):.0f} shares ({position_type}) @ ${avg_price:.2f} = ${market_value:.2f}")
        
        print("-" * 40)
        
        # Confirm closing positions
        confirm2 = input(f"\nClose all {len(positions)} position(s) with MARKET orders? (yes/no): ").strip().lower()
        if confirm2 != "yes":
            print("Aborted.")
            return
        
        # Close each position
        print("\nClosing positions...")
        success_count = 0
        fail_count = 0
        
        for pos in positions:
            symbol = pos.get('instrument', {}).get('symbol')
            long_qty = pos.get('longQuantity', 0)
            short_qty = pos.get('shortQuantity', 0)
            
            if not symbol:
                continue
            
            if long_qty > 0:
                result = close_position(order_manager, symbol, long_qty, is_long=True)
                if result.get('success'):
                    success_count += 1
                else:
                    fail_count += 1
                    
            if short_qty > 0:
                result = close_position(order_manager, symbol, short_qty, is_long=False)
                if result.get('success'):
                    success_count += 1
                else:
                    fail_count += 1
        
        print("\n" + "="*40)
        print(f"  COMPLETE: {success_count} closed, {fail_count} failed")
        print("="*40 + "\n")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()

