"""
PRT (Pattern Real-Time) Command
Accepts a list of tickers, runs PRT analysis, and exports results to CSV
"""

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from datetime import datetime
from typing import Dict, Optional, List
import time
import os
import pandas as pd

from core.controller import BaseCommand


class PRTCommand(BaseCommand):
    """Pattern Real-Time (PRT) command - runs batch analysis and exports CSV"""
    
    def __init__(self, controller, tickers: List[str] = None):
        super().__init__(controller)
        self.tickers = tickers or []
        self.csv_file_path = None
        self.df = None
    
    def get_command_string(self, ticker: str = None, asset_class: str = None) -> str:
        """Return the command string to send to terminal"""
        return "PRT"
    
    def set_tickers(self, tickers: List[str]):
        """Update the list of tickers"""
        self.tickers = tickers
    
    def input_tickers(self) -> bool:
        """Input tickers into the textarea"""
        try:
            # Find the textarea for symbols input
            textarea = self.window.find_element(
                By.XPATH,
                ".//label[contains(., 'Symbols')]//textarea"
            )
            
            # Clear existing content
            textarea.clear()
            time.sleep(0.1)  # Reduced from 0.3
            
            # Format tickers as space-separated string
            ticker_string = " ".join(self.tickers)
            
            # Input the tickers
            textarea.send_keys(ticker_string)
            time.sleep(0.1)  # Reduced from 0.3
            
            print(f"Tickers entered: {ticker_string}")
            return True
            
        except Exception as e:
            print(f"Error inputting tickers: {e}")
            return False
    
    def click_run_button(self) -> bool:
        """Click the Run button to start the batch analysis with retry logic"""
        max_attempts = 3
        wait_time = 1
        
        for attempt in range(1, max_attempts + 1):
            try:
                # On retry attempts, resize the window to ensure elements are visible
                # Window should already be maximized from controller initialization
                # No need to maximize again on retry attempts
                if attempt > 1:
                    # Just wait a bit longer on retry
                    time.sleep(0.5)
                
                # Wait a bit for the button to become available
                time.sleep(wait_time)
                
                # Find the Run button
                run_button = WebDriverWait(self.window, 5).until(
                    EC.presence_of_element_located((
                        By.XPATH,
                        ".//button[contains(@class, 'bg-emerald-600') and contains(text(), 'Run')]"
                    ))
                )
                
                # Scroll button into view if needed (use driver, not window element)
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", run_button)
                time.sleep(0.5)
                
                # Wait for button to be clickable
                run_button = WebDriverWait(self.window, 5).until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        ".//button[contains(@class, 'bg-emerald-600') and contains(text(), 'Run')]"
                    ))
                )
                
                if run_button.is_enabled():
                    try:
                        # Try normal click first
                        run_button.click()
                        print(f"Run button clicked (attempt {attempt})")
                        time.sleep(1)
                        return True
                    except Exception as click_error:
                        # If normal click fails, try JavaScript click as fallback
                        print(f"Normal click failed, trying JavaScript click: {click_error}")
                        try:
                            self.driver.execute_script("arguments[0].click();", run_button)
                            print(f"Run button clicked via JavaScript (attempt {attempt})")
                            time.sleep(1)
                            return True
                        except Exception as js_error:
                            print(f"JavaScript click also failed: {js_error}")
                            if attempt < max_attempts:
                                time.sleep(1)
                                continue
                            return False
                else:
                    print(f"Run button is disabled (attempt {attempt})")
                    # Try JavaScript click even if button appears disabled
                    try:
                        print("Attempting JavaScript click despite disabled state...")
                        self.driver.execute_script("arguments[0].click();", run_button)
                        print(f"Run button clicked via JavaScript despite disabled state (attempt {attempt})")
                        time.sleep(1)
                        return True
                    except Exception as js_error:
                        print(f"JavaScript click failed on disabled button: {js_error}")
                        if attempt < max_attempts:
                            time.sleep(1)
                            continue
                        return False
                    
            except TimeoutException:
                print(f"Timeout waiting for Run button (attempt {attempt}/{max_attempts})")
                if attempt < max_attempts:
                    time.sleep(1)
                    continue
                return False
            except Exception as e:
                print(f"Error clicking Run button (attempt {attempt}/{max_attempts}): {e}")
                if attempt < max_attempts:
                    time.sleep(1)
                    continue
                return False
        
        return False
    
    def wait_for_completion(self, timeout: int = 120) -> bool:
        """Wait for the batch analysis to complete"""
        try:
            print("Waiting for analysis to complete...")
            start_time = time.time()
            
            # Wait for the progress bar to reach 100%
            while time.time() - start_time < timeout:
                try:
                    # Check if the progress bar shows 100%
                    progress_div = self.window.find_element(
                        By.CSS_SELECTOR,
                        "div.h-full.bg-\\[\\#10b981\\]"
                    )
                    width = progress_div.get_attribute('style')
                    
                    if 'width: 100%' in width or 'width:100%' in width:
                        print("Analysis complete (progress bar at 100%)")
                        time.sleep(0.5)  # Reduced from 2 seconds
                        return True
                    
                    # Also check progress text (e.g., "20 / 20")
                    progress_text = self.window.find_element(
                        By.XPATH,
                        ".//div[contains(text(), '/')]"
                    ).text
                    
                    if progress_text:
                        parts = progress_text.split('/')
                        if len(parts) == 2:
                            current = parts[0].strip()
                            total = parts[1].strip()
                            if current == total:
                                print(f"Analysis complete ({progress_text})")
                                time.sleep(0.5)  # Reduced from 2 seconds
                                return True
                    
                except NoSuchElementException:
                    pass
                
                time.sleep(1)
            
            print("Timeout waiting for analysis to complete")
            return False
            
        except Exception as e:
            print(f"Error waiting for completion: {e}")
            return False
    
    def verify_results_table(self) -> bool:
        """Verify that the results table has populated with data"""
        try:
            # Look for the "Top suggestions" table with actual data rows
            table = self.window.find_element(
                By.XPATH,
                ".//div[contains(text(), 'Top suggestions')]/..//table"
            )
            
            tbody = table.find_element(By.TAG_NAME, "tbody")
            rows = tbody.find_elements(By.TAG_NAME, "tr")
            
            if len(rows) > 0:
                print(f"Results table populated with {len(rows)} rows")
                return True
            else:
                print("Results table is empty")
                return False
                
        except Exception as e:
            print(f"Error verifying results table: {e}")
            return False
    
    def export_csv(self) -> Optional[str]:
        """Click Export CSV button and return the file path"""
        try:
            # Get download directory before clicking
            download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
            
            # Get list of existing CSV files before export
            existing_files = set()
            if os.path.exists(download_dir):
                existing_files = set([
                    f for f in os.listdir(download_dir) 
                    if f.endswith('.csv')
                ])
            
            # Find and click Export CSV button
            export_button = self.window.find_element(
                By.XPATH,
                ".//button[contains(text(), 'Export CSV')]"
            )
            
            export_button.click()
            print("Export CSV button clicked")
            time.sleep(0.5)  # Reduced from 2 seconds
            
            # Wait for new CSV file to appear (up to 10 seconds)
            for _ in range(20):
                if os.path.exists(download_dir):
                    current_files = set([
                        f for f in os.listdir(download_dir) 
                        if f.endswith('.csv')
                    ])
                    new_files = current_files - existing_files
                    
                    if new_files:
                        new_file = new_files.pop()
                        file_path = os.path.join(download_dir, new_file)
                        print(f"CSV file downloaded: {file_path}")
                        self.csv_file_path = file_path
                        
                        # Load CSV into DataFrame
                        try:
                            self.df = pd.read_csv(file_path)
                            print(f"Loaded DataFrame with {len(self.df)} rows and {len(self.df.columns)} columns")
                        except Exception as e:
                            print(f"Warning: Could not load CSV into DataFrame: {e}")
                        
                        return file_path
                
                time.sleep(0.5)
            
            print("Timeout waiting for CSV download")
            return None
            
        except Exception as e:
            print(f"Error exporting CSV: {e}")
            return None
    
    def execute(self, ticker: str = None, asset_class: str = None) -> Dict:
        """Execute the PRT command and return results with CSV file path"""
        # Override the base execute to customize for PRT
        command_str = self.get_command_string()
        
        # Get current window count
        previous_count = len(self.dom_monitor.get_current_windows())
        
        print(f"\nExecuting: {command_str}")
        print(f"Tickers: {' '.join(self.tickers)}")
        print(f"Current windows: {previous_count}")
        
        # Send command
        if not self.controller.send_command(command_str):
            return {
                'success': False,
                'error': 'Failed to send command',
                'command': command_str
            }
        
        # Wait for new window
        print("Waiting for PRT window...")
        self.window = self.dom_monitor.get_new_window(previous_count, timeout=10)
        
        if not self.window:
            return {
                'success': False,
                'error': 'No new window created',
                'command': command_str
            }
        
        self.window_id = self.window.get_attribute('id')
        print(f"PRT window detected: {self.window_id}")
        
        # Wait for window to load
        print("Waiting for PRT window to load...")
        time.sleep(0.5)  # Reduced from 2 seconds
        
        # Input tickers if provided
        if self.tickers:
            if not self.input_tickers():
                return {
                    'success': False,
                    'error': 'Failed to input tickers',
                    'window_id': self.window_id
                }
        
        # Click Run button
        if not self.click_run_button():
            return {
                'success': False,
                'error': 'Failed to click Run button',
                'window_id': self.window_id
            }
        
        # Wait for analysis to complete
        if not self.wait_for_completion():
            return {
                'success': False,
                'error': 'Analysis did not complete in time',
                'window_id': self.window_id
            }
        
        # Verify results table populated
        if not self.verify_results_table():
            print("Warning: Results table may be empty")
        
        # Export CSV
        csv_path = self.export_csv()
        
        if not csv_path:
            return {
                'success': False,
                'error': 'Failed to export CSV',
                'window_id': self.window_id
            }
        
        # Extract additional data
        try:
            data = self.extract_data()
            data['csv_file_path'] = csv_path
            data['dataframe'] = self.df
            data['row_count'] = len(self.df) if self.df is not None else 0
            data['columns'] = self.df.columns.tolist() if self.df is not None else []
        except Exception as e:
            print(f"Warning: Data extraction failed: {e}")
            data = {
                'csv_file_path': csv_path,
                'dataframe': self.df,
                'row_count': len(self.df) if self.df is not None else 0,
                'columns': self.df.columns.tolist() if self.df is not None else []
            }
        
        return {
            'success': True,
            'command': command_str,
            'data': data,
            'csv_file': csv_path
        }
    
    def extract_data(self) -> Dict:
        """Extract summary data from PRT window"""
        if not self.window:
            raise ValueError("No window available for extraction")
        
        data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'window_id': self.window_id,
            'tickers': self.tickers,
            'csv_file_path': self.csv_file_path
        }
        
        # Extract performance summary
        try:
            data['performance_summary'] = self._extract_performance_summary()
        except Exception as e:
            print(f"Could not extract performance summary: {e}")
            data['performance_summary'] = None
        
        # Extract progress info
        try:
            data['progress'] = self._extract_progress()
        except Exception as e:
            print(f"Could not extract progress: {e}")
            data['progress'] = None
        
        # Extract failure count
        try:
            data['failures'] = self._extract_failure_count()
        except Exception as e:
            print(f"Could not extract failures: {e}")
            data['failures'] = 0
        
        return data
    
    def _extract_performance_summary(self) -> List[Dict]:
        """Extract the performance summary table"""
        try:
            summary = []
            table = self.window.find_element(
                By.XPATH,
                ".//div[contains(text(), 'Performance Summary')]/..//table"
            )
            
            tbody = table.find_element(By.TAG_NAME, "tbody")
            rows = tbody.find_elements(By.TAG_NAME, "tr")
            
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 7:
                    summary.append({
                        'bucket': cells[0].text.strip(),
                        'n': cells[1].text.strip(),
                        'long': cells[2].text.strip(),
                        'short': cells[3].text.strip(),
                        'win_rate': cells[4].text.strip(),
                        'mean_pl': cells[5].text.strip(),
                        'median_pl': cells[6].text.strip()
                    })
            
            return summary
        except Exception as e:
            print(f"Error extracting performance summary: {e}")
            return []
    
    def _extract_progress(self) -> Dict:
        """Extract progress information"""
        try:
            progress_text = self.window.find_element(
                By.XPATH,
                ".//div[contains(text(), '/')]"
            ).text
            
            if '/' in progress_text:
                parts = progress_text.split('/')
                return {
                    'completed': parts[0].strip(),
                    'total': parts[1].strip()
                }
            return None
        except Exception as e:
            print(f"Error extracting progress: {e}")
            return None
    
    def _extract_failure_count(self) -> int:
        """Extract the number of failures"""
        try:
            failures_text = self.window.find_element(
                By.XPATH,
                ".//div[contains(text(), 'Failures in last batch')]//strong"
            ).text.strip()
            
            return int(failures_text)
        except Exception as e:
            print(f"Error extracting failure count: {e}")
            return 0
    
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
        