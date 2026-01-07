"""
Position sizing module for algobot_v2.
Determines position sizes based on buying power and maximum position size constraints.
"""
from typing import List, Dict, Optional
from loguru import logger
from schwab.account.client import AccountClient
from schwab.market_data.client import MarketDataClient
from constants.parameters import MAX_POSITION_SIZE_DOLLARS


class PositionSizer:
    """
    Calculates position sizes for trades based on buying power and constraints.
    """
    
    def __init__(self, account_client: AccountClient, market_data_client: MarketDataClient):
        """
        Initialize position sizer.
        
        Args:
            account_client: Schwab account client
            market_data_client: Schwab market data client
        """
        self.account_client = account_client
        self.market_data_client = market_data_client
        self.max_position_size = MAX_POSITION_SIZE_DOLLARS
        logger.info(f"PositionSizer initialized with max position size: ${self.max_position_size:.2f}")
    
    def get_buying_power(self) -> Optional[float]:
        """
        Get available buying power from Schwab account.
        
        Returns:
            float: Buying power in dollars, or None if unavailable
        """
        try:
            account_info = self.account_client.get_account_info()
            
            if not account_info:
                logger.error("Failed to retrieve account info")
                return None
            
            # Parse account structure - Schwab API can return data in different formats
            current_balances = None
            if 'securitiesAccount' in account_info:
                securities_account = account_info['securitiesAccount']
                if 'currentBalances' in securities_account:
                    current_balances = securities_account['currentBalances']
                elif 'balance' in securities_account:
                    current_balances = securities_account['balance']
            elif 'currentBalances' in account_info:
                current_balances = account_info['currentBalances']
            else:
                # Try direct access
                current_balances = account_info
            
            if not current_balances:
                logger.error("Could not find currentBalances in account info")
                return None
            
            # Try various field names for buying power
            buying_power = (
                current_balances.get('buyingPower') or
                current_balances.get('buyingPowerNonMarginableTrade') or
                current_balances.get('dayTradingBuyingPower') or
                current_balances.get('availableFunds') or
                current_balances.get('cashBalance')
            )
            
            if buying_power is not None:
                logger.info(f"Available buying power: ${buying_power:,.2f}")
                return float(buying_power)
            else:
                logger.warning("Buying power not found in account info")
                logger.debug(f"Available balance fields: {list(current_balances.keys())}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting buying power: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_current_price(self, ticker: str) -> Optional[float]:
        """
        Get current market price for a ticker.
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            float: Current price, or None if unavailable
        """
        try:
            quote_data = self.market_data_client.get_quote_full(ticker)
            if not quote_data:
                logger.warning(f"Could not get quote for {ticker}")
                return None
            
            # Try to get last price, or use bid/ask midpoint
            price = (
                quote_data.get('lastPrice') or
                quote_data.get('bidPrice') or
                quote_data.get('askPrice')
            )
            
            if price is not None:
                logger.debug(f"Current price for {ticker}: ${price:.2f}")
                return float(price)
            else:
                logger.warning(f"No price data found for {ticker}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting price for {ticker}: {e}")
            return None
    
    def calculate_position_size(self, ticker: str, price: float, buying_power: float) -> int:
        """
        Calculate position size in shares based on max position size constraint.
        
        Args:
            ticker: Stock ticker symbol
            price: Current price per share
            buying_power: Available buying power
        
        Returns:
            int: Number of shares to purchase (0 if constraints not met)
        """
        if price <= 0:
            logger.warning(f"Invalid price for {ticker}: ${price:.2f}")
            return 0
        
        if buying_power <= 0:
            logger.warning(f"Insufficient buying power: ${buying_power:.2f}")
            return 0
        
        # Calculate maximum shares based on max position size
        max_shares_by_size = int(self.max_position_size / price)
        
        # Calculate maximum shares based on buying power
        max_shares_by_buying_power = int(buying_power / price)
        
        # Use the smaller of the two constraints
        position_size = min(max_shares_by_size, max_shares_by_buying_power)
        
        if position_size <= 0:
            logger.warning(f"Cannot create position for {ticker}: price=${price:.2f}, buying_power=${buying_power:.2f}, max_size=${self.max_position_size:.2f}")
            return 0
        
        position_value = position_size * price
        logger.info(f"Position size for {ticker}: {position_size} shares @ ${price:.2f} = ${position_value:.2f}")
        
        return position_size
    
    def size_trades(self, trade_candidates: List[Dict]) -> List[Dict]:
        """
        Calculate position sizes for a list of trade candidates.
        
        Args:
            trade_candidates: List of trade candidate dicts with 'ticker' and 'direction' keys
                            Example: [{'ticker': 'AAPL', 'direction': 'LONG', 'prob_up': 0.65}, ...]
        
        Returns:
            list: List of sized trades with 'ticker', 'direction', 'shares', 'price', 'value' keys
        """
        logger.info("=" * 60)
        logger.info("Position Sizing")
        logger.info("=" * 60)
        
        # Get buying power
        buying_power = self.get_buying_power()
        if buying_power is None:
            logger.error("Cannot size trades without buying power")
            return []
        
        logger.info(f"Available buying power: ${buying_power:,.2f}")
        logger.info(f"Max position size: ${self.max_position_size:.2f}")
        
        sized_trades = []
        total_allocated = 0.0
        
        for candidate in trade_candidates:
            ticker = candidate.get('ticker', '').upper()
            direction = candidate.get('direction', '').upper()
            
            if not ticker:
                logger.warning("Trade candidate missing ticker, skipping")
                continue
            
            if direction not in ['LONG', 'SHORT']:
                logger.warning(f"Invalid direction '{direction}' for {ticker}, skipping")
                continue
            
            # Get current price
            price = self.get_current_price(ticker)
            if price is None:
                logger.warning(f"Could not get price for {ticker}, skipping")
                continue
            
            # Calculate position size
            shares = self.calculate_position_size(ticker, price, buying_power - total_allocated)
            
            if shares <= 0:
                logger.warning(f"Cannot size position for {ticker}, skipping")
                continue
            
            position_value = shares * price
            
            # Check if we have enough buying power remaining
            if total_allocated + position_value > buying_power:
                logger.warning(f"Insufficient buying power for {ticker} (${position_value:.2f} needed, ${buying_power - total_allocated:.2f} available)")
                continue
            
            sized_trade = {
                'ticker': ticker,
                'direction': direction,
                'shares': shares,
                'price': price,
                'value': position_value,
                'prob_up': candidate.get('prob_up'),
                'edge': candidate.get('edge'),
                **{k: v for k, v in candidate.items() if k not in ['ticker', 'direction', 'prob_up', 'edge']}
            }
            
            sized_trades.append(sized_trade)
            total_allocated += position_value
            
            logger.info(f"✓ Sized {direction} {ticker}: {shares} shares @ ${price:.2f} = ${position_value:.2f}")
        
        logger.info("=" * 60)
        logger.info(f"Position Sizing Complete")
        logger.info(f"Total trades sized: {len(sized_trades)}")
        logger.info(f"Total allocated: ${total_allocated:,.2f} / ${buying_power:,.2f} ({total_allocated/buying_power*100:.1f}%)")
        logger.info("=" * 60)
        
        return sized_trades

