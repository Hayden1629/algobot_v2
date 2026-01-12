"""
Position sizing module for algobot_v2.
Determines position sizes based on buying power and maximum position size constraints.
"""
from typing import List, Dict, Optional, Tuple
from loguru import logger
from schwab.account.client import AccountClient
from schwab.market_data.client import MarketDataClient
from constants.parameters import MAX_POSITION_SIZE_DOLLARS, BUYING_POWER_USAGE_PERCENT, MAX_POSITIONS, SHOW_ORDER_OUTPUT, MAX_NET_EXPOSURE_PERCENT


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
        self.max_position_size = MAX_POSITION_SIZE_DOLLARS  # Kept for backward compatibility
        self.buying_power_percent = BUYING_POWER_USAGE_PERCENT
        logger.info(f"PositionSizer initialized - using {self.buying_power_percent*100:.0f}% of intraday buying power for equal position sizing")
    
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
            
            # Prioritize intraday buying power for day trading
            intraday_buying_power = (
                current_balances.get('dayTradingBuyingPower') or
                current_balances.get('intradayBuyingPower') or
                current_balances.get('dayTradingBuyingPowerCall')
            )
            
            # Fallback to regular buying power
            regular_buying_power = (
                current_balances.get('buyingPower') or
                current_balances.get('buyingPowerNonMarginableTrade') or
                current_balances.get('availableFunds') or
                current_balances.get('cashBalance')
            )
            
            # Use intraday if available, otherwise use regular
            buying_power = intraday_buying_power if intraday_buying_power is not None else regular_buying_power
            
            if buying_power is not None:
                if intraday_buying_power is not None:
                    logger.info(f"Intraday buying power: ${intraday_buying_power:,.2f}")
                    if regular_buying_power is not None and regular_buying_power != intraday_buying_power:
                        logger.info(f"Regular buying power: ${regular_buying_power:,.2f}")
                else:
                    logger.info(f"Available buying power: ${buying_power:,.2f} (intraday not available)")
                return float(buying_power)
            else:
                logger.warning("Buying power not found in account info")
                logger.debug(f"Available balance fields: {list(current_balances.keys())}")
                logger.debug(f"Full currentBalances structure: {current_balances}")
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
            
            # Check nested 'quote' field first (primary structure in Schwab API)
            quote_field = quote_data.get('quote', {})
            if isinstance(quote_field, dict):
                price = (
                    quote_field.get('lastPrice') or
                    quote_field.get('regularMarketLastPrice') or
                    quote_field.get('closePrice') or
                    quote_field.get('bidPrice') or
                    quote_field.get('askPrice')
                )
                if price is not None:
                    logger.debug(f"Current price for {ticker} (from quote field): ${price:.2f}")
                    return float(price)
            
            # Check nested 'regular' field
            regular_field = quote_data.get('regular', {})
            if isinstance(regular_field, dict):
                price = regular_field.get('regularMarketLastPrice')
                if price is not None:
                    logger.debug(f"Current price for {ticker} (from regular field): ${price:.2f}")
                    return float(price)
            
            # Fallback to top-level fields
            price = (
                quote_data.get('lastPrice') or
                quote_data.get('regularMarketLastPrice') or
                quote_data.get('last') or
                quote_data.get('closePrice') or
                quote_data.get('regularMarketPrice') or
                quote_data.get('bidPrice') or
                quote_data.get('bid') or
                quote_data.get('askPrice') or
                quote_data.get('ask')
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
    
    def calculate_position_size(self, ticker: str, price: float, target_position_value: float) -> int:
        """
        Calculate position size in shares based on target position value.
        
        Args:
            ticker: Stock ticker symbol
            price: Current price per share
            target_position_value: Target dollar value for this position
        
        Returns:
            int: Number of shares to purchase (0 if constraints not met)
        """
        if price <= 0:
            logger.warning(f"Invalid price for {ticker}: ${price:.2f}")
            return 0
        
        if target_position_value <= 0:
            logger.warning(f"Invalid target position value for {ticker}: ${target_position_value:.2f}")
            return 0
        
        # Calculate shares based on target value
        position_size = int(target_position_value / price)
        
        if position_size <= 0:
            logger.warning(f"Cannot create position for {ticker}: price=${price:.2f}, target_value=${target_position_value:.2f}")
            return 0
        
        position_value = position_size * price
        if SHOW_ORDER_OUTPUT:
            logger.info(f"Position size for {ticker}: {position_size} shares @ ${price:.2f} = ${position_value:.2f}")
        
        return position_size
    
    def get_current_exposure(self) -> float:
        """
        Calculate current total exposure (long + short) from existing positions.
        
        Returns:
            float: Total exposure in dollars
        """
        try:
            positions = self.account_client.get_positions()
            if positions is None:
                return 0.0
            
            total_exposure = 0.0
            for position in positions:
                market_value = position.get('marketValue', 0) or 0
                # Use absolute value to get total exposure (both longs and shorts)
                total_exposure += abs(market_value)
            
            return total_exposure
        except Exception as e:
            logger.error(f"Error calculating current exposure: {e}")
            return 0.0
    
    def get_current_exposure_breakdown(self) -> Dict[str, float]:
        """
        Calculate current long, short, and net exposure from existing positions.
        
        Returns:
            dict: {'long_exposure': float, 'short_exposure': float, 'net_exposure': float}
        """
        try:
            positions = self.account_client.get_positions()
            if positions is None:
                return {'long_exposure': 0.0, 'short_exposure': 0.0, 'net_exposure': 0.0}
            
            long_exposure = 0.0
            short_exposure = 0.0
            
            for position in positions:
                long_qty = position.get('longQuantity', 0) or 0
                short_qty = position.get('shortQuantity', 0) or 0
                market_value = position.get('marketValue', 0) or 0
                
                # Use marketValue if available (most accurate)
                if market_value != 0:
                    if long_qty > 0:
                        # Long positions have positive market value
                        long_exposure += abs(market_value)
                    elif short_qty > 0:
                        # Short positions have negative market value
                        short_exposure += abs(market_value)
                else:
                    # Fallback: calculate from quantity and price
                    current_price = position.get('currentPrice', 0) or position.get('averagePrice', 0) or 0
                    if long_qty > 0 and current_price > 0:
                        long_exposure += long_qty * current_price
                    elif short_qty > 0 and current_price > 0:
                        short_exposure += short_qty * current_price
            
            net_exposure = long_exposure - short_exposure
            
            return {
                'long_exposure': round(long_exposure, 2),
                'short_exposure': round(short_exposure, 2),
                'net_exposure': round(net_exposure, 2)
            }
        except Exception as e:
            logger.error(f"Error calculating exposure breakdown: {e}")
            return {'long_exposure': 0.0, 'short_exposure': 0.0, 'net_exposure': 0.0}
    
    def _calculate_balanced_target_values(
        self, 
        long_candidates: List[Dict], 
        short_candidates: List[Dict], 
        current_net: float,
        max_net_exposure: float,
        base_target_value: float,
        available_buying_power: float
    ) -> Tuple[float, float]:
        """
        Calculate adjusted target position values for longs and shorts to balance net exposure.
        Keeps all candidates but adjusts their sizes.
        
        Args:
            long_candidates: List of long trade candidates
            short_candidates: List of short trade candidates
            current_net: Current net exposure (long - short)
            max_net_exposure: Maximum allowed net exposure (absolute value)
            base_target_value: Base target value per position (equal allocation)
            available_buying_power: Available buying power for new positions
        
        Returns:
            Tuple of (target_long_value, target_short_value)
        """
        num_long = len(long_candidates)
        num_short = len(short_candidates)
        
        if num_long == 0 and num_short == 0:
            return base_target_value, base_target_value
        
        # Calculate what net exposure would be if we sized all positions equally
        equal_long_net = num_long * base_target_value
        equal_short_net = num_short * base_target_value
        projected_net_equal = current_net + equal_long_net - equal_short_net
        
        # If equal sizing keeps us within limits, use equal sizing
        # Check if max_net_exposure is valid (not infinity) before comparing
        if max_net_exposure != float('inf') and abs(projected_net_equal) <= max_net_exposure:
            logger.info(f"Equal sizing keeps net exposure within limits (${projected_net_equal:,.2f} <= ${max_net_exposure:,.2f})")
            return base_target_value, base_target_value
        elif max_net_exposure == float('inf'):
            logger.warning(f"Net exposure limit is infinity (account value not available), using equal sizing")
            return base_target_value, base_target_value
        
        # Need to adjust sizing to balance
        # We want: |current_net + (num_long * target_long - num_short * target_short)| <= max_net_exposure
        # Also: num_long * target_long + num_short * target_short <= available_buying_power
        
        # Strategy: Calculate target values that keep net exposure within the limit
        # Target net exposure should be within ±max_net_exposure
        # If we have more shorts, we'll end up negative, so target something reasonable within the limit
        
        if num_long == 0 or num_short == 0:
            # Can't balance if we only have one direction
            return base_target_value, base_target_value
        
        # Calculate what net exposure we'd have with equal sizing
        # If it's way over the limit, we need aggressive adjustment
        
        # Target net exposure: try to get close to zero, but stay within limit
        # If equal sizing would be way over, target the limit instead
        if abs(projected_net_equal) > max_net_exposure:
            # Way over limit - target staying within limit
            # If projected would be very negative, target -max_net_exposure
            # If projected would be very positive, target +max_net_exposure
            if projected_net_equal < 0:
                target_net = -max_net_exposure * 0.9  # Target 90% of limit (negative side)
            else:
                target_net = max_net_exposure * 0.9  # Target 90% of limit (positive side)
        else:
            # Close to limit or within - target zero for balance
            target_net = 0.0
        
        # Solve the system:
        # 1. num_long * target_long + num_short * target_short = available_buying_power (total exposure)
        # 2. current_net + (num_long * target_long - num_short * target_short) = target_net (net exposure)
        # 
        # From (2): num_long * target_long - num_short * target_short = target_net - current_net
        # 
        # Adding (1) and (2): 2 * num_long * target_long = available_buying_power + (target_net - current_net)
        # Subtracting: 2 * num_short * target_short = available_buying_power - (target_net - current_net)
        
        net_adjustment = target_net - current_net
        target_long = (available_buying_power + net_adjustment) / (2 * num_long)
        target_short = (available_buying_power - net_adjustment) / (2 * num_short)
        
        # Ensure minimum size (at least 10% of base) but allow much larger sizes (up to 5x base)
        min_target = base_target_value * 0.1
        max_target = base_target_value * 5.0  # Allow up to 5x for aggressive balancing
        
        # Clamp to reasonable bounds
        target_long = max(min_target, min(target_long, max_target))
        target_short = max(min_target, min(target_short, max_target))
        
        # Verify the projected net is within limits
        # NOTE: This projection assumes all candidates will be executed at exact target values
        # Actual execution may differ due to: share rounding, price changes, partial fills
        projected_net = current_net + (num_long * target_long - num_short * target_short)
        
        # If still over limit, iteratively adjust
        max_iterations = 5
        iteration = 0
        while abs(projected_net) > max_net_exposure * 1.05 and iteration < max_iterations:  # 5% tolerance
            iteration += 1
            if projected_net < -max_net_exposure:
                # Too short - increase longs more, decrease shorts more
                adjustment_factor = 1.1
                target_long = min(target_long * adjustment_factor, max_target)
                target_short = max(target_short / adjustment_factor, min_target)
            elif projected_net > max_net_exposure:
                # Too long - increase shorts more, decrease longs more
                adjustment_factor = 1.1
                target_short = min(target_short * adjustment_factor, max_target)
                target_long = max(target_long / adjustment_factor, min_target)
            
            projected_net = current_net + (num_long * target_long - num_short * target_short)
        
        if abs(projected_net) > max_net_exposure * 1.1:
            logger.warning(f"After {iteration} adjustments, projected net=${projected_net:,.2f} still exceeds limit ${max_net_exposure:,.2f}")
        else:
            logger.info(f"Balanced sizing: LONG=${target_long:,.2f} ({target_long/base_target_value:.1f}x), SHORT=${target_short:,.2f} ({target_short/base_target_value:.1f}x), projected net=${projected_net:,.2f}")
            logger.debug(f"Projection details: current_net=${current_net:,.2f}, num_long={num_long}, num_short={num_short}, target_long_total=${num_long * target_long:,.2f}, target_short_total=${num_short * target_short:,.2f}")
            logger.warning(f"⚠️  NOTE: Projected net assumes ideal target values. Actual net will differ due to:")
            logger.warning(f"   1. Share rounding (shares must be whole numbers, rounded down)")
            logger.warning(f"   2. Price changes between sizing and execution")
            logger.warning(f"   3. Market values vs entry values (actual exposure uses current market prices)")
        
        return target_long, target_short
    
    def size_trades(self, trade_candidates: List[Dict], current_position_count: int = 0) -> List[Dict]:
        """
        Calculate position sizes for a list of trade candidates using equal allocation
        based on percentage of intraday buying power.
        
        Args:
            trade_candidates: List of trade candidate dicts with 'ticker' and 'direction' keys
                            Example: [{'ticker': 'AAPL', 'direction': 'LONG', 'prob_up': 0.65}, ...]
            current_position_count: Current number of open positions (for calculating total positions)
        
        Returns:
            list: List of sized trades with 'ticker', 'direction', 'shares', 'price', 'value' keys
        """
        logger.info("=" * 60)
        logger.info("Position Sizing")
        logger.info("=" * 60)
        
        # Get intraday buying power
        buying_power = self.get_buying_power()
        if buying_power is None:
            logger.error("Cannot size trades without buying power")
            return []
        
        # Calculate total allocatable buying power
        allocatable_buying_power = buying_power * self.buying_power_percent
        
        # Get current exposure to see how much is already used
        current_exposure = self.get_current_exposure()
        
        # Calculate available buying power (allocatable - already used)
        available_buying_power = allocatable_buying_power - current_exposure
        
        if available_buying_power <= 0:
            logger.warning(
                f"Insufficient buying power for new positions. "
                f"Allocatable: ${allocatable_buying_power:,.2f}, "
                f"Current exposure: ${current_exposure:,.2f}, "
                f"Available: ${available_buying_power:,.2f}"
            )
            return []
        
        # Calculate total number of positions (existing + new)
        num_new_positions = len(trade_candidates)
        total_positions = current_position_count + num_new_positions
        
        if total_positions == 0:
            logger.warning("No positions to size")
            return []
        
        # Calculate target position value: (allocatable buying power) / total positions
        # This ensures equal allocation across all positions
        target_position_value = allocatable_buying_power / total_positions
        
        # But we can only use available buying power for new positions
        # So limit target to available / new positions
        max_target_per_new_position = available_buying_power / num_new_positions if num_new_positions > 0 else 0
        target_position_value = min(target_position_value, max_target_per_new_position)
        
        # Get current exposure breakdown and account value for net exposure limit
        current_exposure_breakdown = self.get_current_exposure_breakdown()
        current_long = current_exposure_breakdown['long_exposure']
        current_short = current_exposure_breakdown['short_exposure']
        current_net = current_exposure_breakdown['net_exposure']
        
        # Get account value to calculate net exposure limit
        account_info = self.account_client.get_account_info()
        
        # Parse account structure - same as get_buying_power method
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
            current_balances = account_info
        
        # Get account value (try multiple field names)
        account_value = 0
        if current_balances:
            account_value = (
                current_balances.get('liquidationValue') or
                current_balances.get('totalEquity') or
                current_balances.get('equity') or
                current_balances.get('netValue') or
                0
            )
        
        max_net_exposure_dollars = abs(account_value * MAX_NET_EXPOSURE_PERCENT) if account_value > 0 else float('inf')
        
        logger.info(f"Intraday buying power: ${buying_power:,.2f}")
        logger.info(f"Allocatable ({self.buying_power_percent*100:.0f}%): ${allocatable_buying_power:,.2f}")
        logger.info(f"Current exposure: ${current_exposure:,.2f}")
        logger.info(f"Available for new positions: ${available_buying_power:,.2f}")
        logger.info(f"Current positions: {current_position_count}, New positions: {num_new_positions}, Total: {total_positions}")
        logger.info(f"Base target position value: ${target_position_value:,.2f}")
        logger.info(f"Current net exposure: ${current_net:,.2f} (limit: ±${max_net_exposure_dollars:,.2f} = ±{MAX_NET_EXPOSURE_PERCENT*100:.0f}% of account)")
        
        # Separate candidates by direction
        long_candidates = [c for c in trade_candidates if c.get('direction', '').upper() == 'LONG']
        short_candidates = [c for c in trade_candidates if c.get('direction', '').upper() == 'SHORT']
        
        # Calculate adjusted target values for longs and shorts to balance net exposure
        target_long_value, target_short_value = self._calculate_balanced_target_values(
            long_candidates, short_candidates, current_net, max_net_exposure_dollars, 
            target_position_value, available_buying_power
        )
        
        logger.info(f"Candidates: {len(long_candidates)} long, {len(short_candidates)} short")
        logger.info(f"Adjusted target values: LONG=${target_long_value:,.2f}, SHORT=${target_short_value:,.2f}")
        
        sized_trades = []
        total_allocated = 0.0
        new_long_exposure = 0.0
        new_short_exposure = 0.0
        
        # Process ALL candidates (not filtered) with adjusted sizing
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
            
            # Use direction-specific target value for sizing
            direction_target_value = target_long_value if direction == 'LONG' else target_short_value
            
            # Calculate position size based on direction-specific target value
            shares = self.calculate_position_size(ticker, price, direction_target_value)
            
            if shares <= 0:
                logger.warning(f"Cannot size position for {ticker}, skipping")
                continue
            
            position_value = shares * price
            
            # Check if we have enough buying power remaining
            if total_allocated + position_value > available_buying_power:
                logger.warning(
                    f"Insufficient buying power for {ticker} "
                    f"(${position_value:.2f} needed, ${available_buying_power - total_allocated:.2f} available)"
                )
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
            
            # Track long/short exposure separately
            if direction == 'LONG':
                new_long_exposure += position_value
            elif direction == 'SHORT':
                new_short_exposure += position_value
            
            if SHOW_ORDER_OUTPUT:
                logger.info(f"✓ Sized {direction} {ticker}: {shares} shares @ ${price:.2f} = ${position_value:.2f}")
        
        # Calculate total exposure after new trades
        total_long_exposure = current_long + new_long_exposure
        total_short_exposure = current_short + new_short_exposure
        total_net_exposure = total_long_exposure - total_short_exposure
        total_exposure_after = total_long_exposure + total_short_exposure
        
        # Calculate what the projection expected vs what we actually sized
        expected_long_total = len(long_candidates) * target_long_value if long_candidates else 0
        expected_short_total = len(short_candidates) * target_short_value if short_candidates else 0
        expected_net = current_net + (expected_long_total - expected_short_total)
        
        logger.info("=" * 60)
        logger.info(f"Position Sizing Complete")
        logger.info(f"Total trades sized: {len(sized_trades)}")
        logger.info(f"Total allocated: ${total_allocated:,.2f} / ${available_buying_power:,.2f} ({total_allocated/available_buying_power*100:.1f}% of available)")
        logger.info(f"Long exposure: ${total_long_exposure:,.2f} | Short exposure: ${total_short_exposure:,.2f} | Net: ${total_net_exposure:,.2f}")
        logger.info(f"Total exposure after: ${total_exposure_after:,.2f} / ${allocatable_buying_power:,.2f} ({total_exposure_after/allocatable_buying_power*100:.1f}% of allocatable)")
        logger.debug(f"Projection vs Actual: Expected net=${expected_net:,.2f}, Actual sized net=${total_net_exposure:,.2f}, Difference=${total_net_exposure - expected_net:,.2f}")
        logger.debug(f"  Expected: LONG=${expected_long_total:,.2f}, SHORT=${expected_short_total:,.2f}")
        logger.debug(f"  Actual sized: LONG=${new_long_exposure:,.2f}, SHORT=${new_short_exposure:,.2f}")
        logger.info("=" * 60)
        
        return sized_trades

