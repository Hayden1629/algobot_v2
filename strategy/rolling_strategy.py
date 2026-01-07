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
    PRT_MAX_TICKERS
)
from constants.blacklist import filter_blacklisted_tickers
from strategy.trade_tracker import TradeTracker
from strategy.position_sizing import PositionSizer
from strategy.trade_executor import TradeExecutor


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
        
        # Register commands
        self.controller.register_command("MOST", MOSTCommand)
        self.controller.register_command("PRT", PRTCommand)
    
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
                symbol = position.get('symbol', '')
                if symbol:
                    tickers.append(symbol.upper())
            
            logger.info(f"Found {len(tickers)} open positions")
            return tickers
            
        except Exception as e:
            logger.error(f"Error getting open positions: {e}")
            return []
    
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
            
            # Step 5: Filter by prob_up thresholds to find new trade candidates
            long_candidates, short_candidates = self.filter_trades_by_prob_up(prt_data)
            
            # Step 6: Check which active positions should be closed (based on PRT)
            # These positions will NOT feed into the next iteration
            positions_to_close = []
            for ticker in active_positions:
                if ticker in prt_data and self.should_close_position(ticker, prt_data):
                    positions_to_close.append(ticker)
            
            results['trades_closed'] = len(positions_to_close)
            
            # Step 7: Determine new positions to open (not already in active positions)
            # These new positions will feed into the next iteration's PRT analysis
            new_long_candidates = [c for c in long_candidates if c['ticker'] not in active_positions]
            new_short_candidates = [c for c in short_candidates if c['ticker'] not in active_positions]
            
            results['trades_opened'] = len(new_long_candidates) + len(new_short_candidates)
            
            # Step 8: Log summary
            logger.info(f"Active positions (will feed into next iteration): {len(active_positions)}")
            logger.info(f"Positions to close: {len(positions_to_close)} {positions_to_close[:5] if positions_to_close else ''}")
            logger.info(f"New long candidates: {len(new_long_candidates)} {[c['ticker'] for c in new_long_candidates[:5]]}")
            logger.info(f"New short candidates: {len(new_short_candidates)} {[c['ticker'] for c in new_short_candidates[:5]]}")
            
            # Step 9: Close positions that no longer meet criteria
            if positions_to_close and self.order_manager:
                logger.info(f"Closing {len(positions_to_close)} position(s) that no longer meet criteria...")
                for ticker in positions_to_close:
                    try:
                        # Get position details to determine direction and quantity
                        positions = self.account_client.get_positions()
                        for pos in positions:
                            if pos.get('instrument', {}).get('symbol', '').upper() == ticker.upper():
                                long_qty = pos.get('longQuantity', 0)
                                short_qty = pos.get('shortQuantity', 0)
                                
                                if long_qty > 0:
                                    result = self.order_manager.create_market_order(ticker, "SELL", int(long_qty))
                                    if 'orderId' in result or 'success' in result:
                                        logger.info(f"✓ Closed long position: {ticker} {int(long_qty)} shares")
                                        self.trade_tracker.remove_trade(ticker)
                                    else:
                                        logger.error(f"✗ Failed to close long {ticker}: {result}")
                                
                                if short_qty > 0:
                                    result = self.order_manager.create_market_order(ticker, "BUY_TO_COVER", int(short_qty))
                                    if 'orderId' in result or 'success' in result:
                                        logger.info(f"✓ Closed short position: {ticker} {int(short_qty)} shares")
                                        self.trade_tracker.remove_trade(ticker)
                                    else:
                                        logger.error(f"✗ Failed to close short {ticker}: {result}")
                                
                                break
                    except Exception as e:
                        logger.error(f"Error closing position {ticker}: {e}")
            
            # Step 10: Size and execute new trades
            if (new_long_candidates or new_short_candidates) and self.position_sizer and self.trade_executor:
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
                
                if trade_candidates:
                    logger.info(f"Sizing {len(trade_candidates)} trade candidate(s)...")
                    # Size the trades
                    sized_trades = self.position_sizer.size_trades(trade_candidates)
                    
                    if sized_trades:
                        logger.info(f"Executing {len(sized_trades)} trade(s)...")
                        # Execute the trades
                        execution_results = self.trade_executor.execute_trades(sized_trades)
                        
                        # Track successful trades
                        successful_trades = 0
                        for result in execution_results:
                            if result.get('success'):
                                successful_trades += 1
                                ticker = result.get('ticker', '').upper()
                                direction = result.get('direction', '').upper()
                                shares = result.get('shares', 0)
                                
                                # Track the trade
                                if ticker:
                                    self.trade_tracker.add_trade(ticker)
                                    logger.debug(f"Tracking new trade: {ticker} ({direction}, {shares} shares)")
                        
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

