"""
MOST (Most Active Stocks) Command
Opens the MOST window and extracts the table data into a pandas DataFrame
"""

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from datetime import datetime
from typing import Dict, Optional, List
import time
import pandas as pd

from core.controller import BaseCommand


class MOSTCommand(BaseCommand):
    """Most Active Stocks (MOST) command - extracts table data to DataFrame"""
    
    def __init__(self, controller, tab: str = "ACTIVE", limit: int = 75):
        """
        Initialize MOST command
        
        Args:
            controller: GodelTerminalController instance
            tab: Which tab to select (ACTIVE, GAINERS, LOSERS, VALUE)
            limit: Number of results to display (10, 25, 50, 75, 100)
        """
        super().__init__(controller)
        self.tab = tab.upper()
        self.limit = limit
        self.df = None
    
    def get_command_string(self, ticker: str = None, asset_class: str = None) -> str:
        """Return the command string to send to terminal"""
        return "MOST"
    
    def select_tab(self, tab_name: str) -> bool:
        """Select a specific tab (ACTIVE, GAINERS, LOSERS, VALUE)"""
        try:
            # Find and click the tab button
            tab_xpath = f".//div[contains(@class, 'cursor-pointer') and contains(text(), '{tab_name}')]"
            tab_button = self.window.find_element(By.XPATH, tab_xpath)
            tab_button.click()
            print(f"Selected tab: {tab_name}")
            time.sleep(1)  # Wait for table to update
            return True
        except Exception as e:
            print(f"Error selecting tab {tab_name}: {e}")
            return False
    
    def set_limit(self, limit: int) -> bool:
        """Set the number of results to display"""
        try:
            # Find the limit dropdown (first select element)
            selects = self.window.find_elements(By.TAG_NAME, "select")
            if len(selects) == 0:
                print("Could not find limit dropdown")
                return False
            
            limit_dropdown = selects[0]
            
            # Find the option with the desired value
            options = limit_dropdown.find_elements(By.TAG_NAME, "option")
            for option in options:
                if option.get_attribute("value") == str(limit):
                    option.click()
                    print(f"Set limit to: {limit}")
                    time.sleep(1)  # Wait for table to update
                    return True
            
            print(f"Could not find limit option: {limit}")
            return False
        except Exception as e:
            print(f"Error setting limit: {e}")
            return False
    
    def set_min_market_cap(self, min_cap_value: str = "FIVE_BILLION") -> bool:
        """
        Set the minimum market cap filter to prevent trading low float stocks.
        
        Args:
            min_cap_value: Market cap value to select. Options:
                - "ZERO" (0)
                - "FIFTY_MILLION" (50m)
                - "FIVE_HUNDRED_MILLION" (500m)
                - "FIVE_BILLION" (5b) - default, recommended to avoid low float stocks
                - "FIFTY_BILLION" (50b)
        
        Returns:
            bool: True if successfully set, False otherwise
        """
        try:
            # Find all select elements
            selects = self.window.find_elements(By.TAG_NAME, "select")
            if len(selects) < 2:
                print("Could not find market cap dropdown (need at least 2 select elements)")
                return False
            
            # The second select element is the minimum market cap dropdown
            market_cap_dropdown = selects[1]
            
            # Find the option with the desired value
            options = market_cap_dropdown.find_elements(By.TAG_NAME, "option")
            for option in options:
                if option.get_attribute("value") == min_cap_value:
                    # Check if option is disabled
                    if option.get_attribute("disabled"):
                        print(f"Market cap option {min_cap_value} is disabled")
                        return False
                    option.click()
                    print(f"Set minimum market cap to: {min_cap_value}")
                    time.sleep(1)  # Wait for table to update
                    return True
            
            print(f"Could not find market cap option: {min_cap_value}")
            return False
        except Exception as e:
            print(f"Error setting minimum market cap: {e}")
            return False
    
    def extract_data(self) -> Dict:
        """Extract table data from MOST window (required by BaseCommand)"""
        if not self.window:
            raise ValueError("No window available for extraction")
        
        # Extract the table into a DataFrame
        df = self.extract_table_data()
        
        if df is None:
            return {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'window_id': self.window_id,
                'tab': self.tab,
                'error': 'Failed to extract table data'
            }
        
        # Return data in dictionary format
        return {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'window_id': self.window_id,
            'tab': self.tab,
            'limit': self.limit,
            'row_count': len(df),
            'columns': df.columns.tolist(),
            'dataframe': df,
            'records': df.to_dict('records'),
            'tickers': df['Ticker'].tolist() if 'Ticker' in df.columns else []
        }
    
    def extract_table_data(self) -> Optional[pd.DataFrame]:
        """Extract the table data into a pandas DataFrame"""
        try:
            # Find the table (should be only one in the MOST window)
            table = self.window.find_element(By.TAG_NAME, "table")
            
            # Extract headers from thead
            thead = table.find_element(By.TAG_NAME, "thead")
            header_cells = thead.find_elements(By.TAG_NAME, "th")
            headers = [cell.text.strip() for cell in header_cells]
            print(f"Table headers: {headers}")
            
            # Extract rows from tbody - re-query the tbody each time to avoid stale elements
            tbody = table.find_element(By.TAG_NAME, "tbody")
            rows = tbody.find_elements(By.TAG_NAME, "tr")
            
            print(f"Found {len(rows)} rows in table")
            
            data = []
            # Iterate by index to avoid stale element references
            # Re-query rows each time through the loop to handle table updates
            num_rows = len(rows)
            for i in range(num_rows):
                try:
                    # Re-find table, tbody and rows fresh to avoid stale element references
                    # This ensures we have the latest DOM state after any table updates
                    table = self.window.find_element(By.TAG_NAME, "table")
                    tbody = table.find_element(By.TAG_NAME, "tbody")
                    rows = tbody.find_elements(By.TAG_NAME, "tr")
                    
                    # Make sure we still have enough rows (table might have changed)
                    if i >= len(rows):
                        print(f"Row index {i} out of bounds (table has {len(rows)} rows), stopping extraction")
                        break
                    
                    row = rows[i]
                    cells = row.find_elements(By.TAG_NAME, "td")
                    row_data = []
                    
                    for cell in cells:
                        # Try to get the span text first (for nested elements)
                        try:
                            span = cell.find_element(By.TAG_NAME, "span")
                            text = span.text.strip()
                        except NoSuchElementException:
                            text = cell.text.strip()
                        
                        row_data.append(text)
                    
                    if row_data:  # Only add non-empty rows
                        data.append(row_data)
                        
                except Exception as row_error:
                    # If we get a stale element or other error on a specific row, log and continue
                    # Re-query table and try to continue from next row
                    print(f"Error extracting row {i}: {row_error}")
                    try:
                        # Try to refresh table reference
                        table = self.window.find_element(By.TAG_NAME, "table")
                        tbody = table.find_element(By.TAG_NAME, "tbody")
                        rows = tbody.find_elements(By.TAG_NAME, "tr")
                        num_rows = len(rows)  # Update row count in case it changed
                    except:
                        pass  # If we can't refresh, continue anyway
                    continue
            
            # Create DataFrame
            if data:
                df = pd.DataFrame(data, columns=headers)
                print(f"Created DataFrame with {len(df)} rows and {len(df.columns)} columns")
                
                # Clean up the data
                df = self._clean_dataframe(df)
                
                self.df = df
                return df
            else:
                print("No data found in table")
                return None
                
        except Exception as e:
            print(f"Error extracting table data: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and format the DataFrame"""
        try:
            # Make a copy to avoid modifying original
            df = df.copy()
            
            # Clean percentage values (remove % sign and convert to float)
            if 'Chg %' in df.columns:
                df['Chg %'] = df['Chg %'].str.replace('%', '').replace('', '0')
                df['Chg % Numeric'] = pd.to_numeric(df['Chg %'], errors='coerce')
            
            # Clean numeric values (remove M, B, K suffixes)
            for col in ['Vol', 'Vol $', 'M Cap']:
                if col in df.columns:
                    df[f'{col} Raw'] = df[col]
                    df[f'{col} Numeric'] = df[col].apply(self._parse_number)
            
            # Clean Last price
            if 'Last' in df.columns:
                df['Last Numeric'] = pd.to_numeric(df['Last'], errors='coerce')
            
            # Clean Change
            if 'Chg' in df.columns:
                df['Chg Numeric'] = pd.to_numeric(df['Chg'], errors='coerce')
            
            return df
            
        except Exception as e:
            print(f"Warning: Error cleaning DataFrame: {e}")
            return df
    
    def _parse_number(self, value: str) -> float:
        """Parse numbers with K, M, B suffixes"""
        if not value or value == '':
            return 0.0
        
        try:
            value = value.strip().upper()
            
            if 'B' in value:
                return float(value.replace('B', '')) * 1_000_000_000
            elif 'M' in value:
                return float(value.replace('M', '')) * 1_000_000
            elif 'K' in value:
                return float(value.replace('K', '')) * 1_000
            else:
                return float(value)
        except:
            return 0.0
    
    def execute(self, ticker: str = None, asset_class: str = None) -> Dict:
        """Execute the MOST command and return results with DataFrame"""
        command_str = self.get_command_string()
        
        # Get current window count
        previous_count = len(self.dom_monitor.get_current_windows())
        
        print(f"\nExecuting: {command_str}")
        print(f"Tab: {self.tab}, Limit: {self.limit}")
        print(f"Current windows: {previous_count}")
        
        # Send command
        if not self.controller.send_command(command_str):
            return {
                'success': False,
                'error': 'Failed to send command',
                'command': command_str
            }
        
        # Wait for new window
        print("Waiting for MOST window...")
        self.window = self.dom_monitor.get_new_window(previous_count, timeout=10)
        
        if not self.window:
            return {
                'success': False,
                'error': 'No new window created',
                'command': command_str
            }
        
        self.window_id = self.window.get_attribute('id')
        print(f"MOST window detected: {self.window_id}")
        
        # Wait for window to load
        print("Waiting for MOST window to load...")
        time.sleep(1)
        
        # Select the desired tab if not ACTIVE (which is sometimes default)
        if self.tab and self.tab != "ACTIVE":
            if not self.select_tab(self.tab):
                print(f"Warning: Could not select tab {self.tab}, using current tab")
        
        # Set the limit
        if self.limit:
            if not self.set_limit(self.limit):
                print(f"Warning: Could not set limit to {self.limit}, using default")
        
        # Set minimum market cap to 5b to prevent trading low float stocks
        if not self.set_min_market_cap("FIFTY_BILLION"):
            print("Warning: Could not set minimum market cap to 5b, using default")
        
        # Wait for table to populate and stabilize after filters are set
        # The table may update/refresh after setting filters, so wait longer to ensure stability
        time.sleep(1)
        
        # Extract data using the base extract_data method
        try:
            data = self.extract_data()
        except Exception as e:
            print(f"Error extracting data: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': f'Failed to extract data: {str(e)}',
                'window_id': self.window_id
            }
        
        # Check if extraction was successful
        if 'error' in data:
            return {
                'success': False,
                'error': data['error'],
                'window_id': self.window_id
            }
        
        # Return successful result
        return {
            'success': True,
            'command': command_str,
            'data': data
        }
    
    def get_dataframe(self) -> Optional[pd.DataFrame]:
        """Get the extracted DataFrame"""
        return self.df
    
    def save_to_csv(self, filepath: str) -> bool:
        """Save the DataFrame to CSV"""
        if self.df is not None:
            try:
                self.df.to_csv(filepath, index=False)
                print(f"Saved DataFrame to: {filepath}")
                return True
            except Exception as e:
                print(f"Error saving to CSV: {e}")
                return False
        else:
            print("No DataFrame to save")
            return False
    
    def save_to_json(self, filepath: str) -> bool:
        """Save the DataFrame to JSON"""
        if self.df is not None:
            try:
                self.df.to_json(filepath, orient='records', indent=2)
                print(f"Saved DataFrame to: {filepath}")
                return True
            except Exception as e:
                print(f"Error saving to JSON: {e}")
                return False
        else:
            print("No DataFrame to save")
            return False

