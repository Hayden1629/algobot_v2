"""
DES (Description) Command
Extracts comprehensive company information including description, financials, and analyst ratings
"""

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from datetime import datetime
from typing import Dict, Optional, List
import time

from core.controller import BaseCommand


class DESCommand(BaseCommand):
    """Description (DES) command - extracts company information"""
    
    def get_command_string(self, ticker: str, asset_class: str) -> str:
        return f"{ticker} {asset_class} DES"
    
    def expand_description(self) -> bool:
        """Click 'See more' to expand full description"""
        try:
            see_more_link = self.window.find_element(
                By.XPATH,
                ".//a[contains(@class, 'cursor-pointer') and contains(text(), 'See more')]"
            )
            see_more_link.click()
            time.sleep(0.5)
            print("Description expanded")
            return True
        except NoSuchElementException:
            print("'See more' link not found (description may already be expanded)")
            return False
        except Exception as e:
            print(f"Error expanding description: {e}")
            return False
    
    def expand_analyst_ratings(self) -> bool:
        """Click 'Show all' to expand all analyst ratings"""
        try:
            show_all_button = self.window.find_element(
                By.XPATH,
                "//div[@class='cursor-pointer p-2' and text()='Show all']"
            )
            if show_all_button:
                # Use JavaScript to click the button instead of regular click
                self.driver.execute_script("arguments[0].click();", show_all_button)
                time.sleep(0.5)
                print("Analyst ratings expanded")
                return True
            return False
        except NoSuchElementException:
            print("'Show all' button not found (ratings may already be expanded)")
            return False
        except Exception as e:
            print(f"Error expanding analyst ratings: {e}")
            return False
    
    def extract_data(self) -> Dict:
        """Extract all data from DES window"""
        if not self.window:
            raise ValueError("No window available for extraction")
        
        # Expand sections before extracting
        self.expand_description()
        self.expand_analyst_ratings()
        
        data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'window_id': self.window_id,
            'ticker': self._extract_ticker(),
            'company_info': self._extract_company_header(),
            'description': self._extract_description(),
            'eps_estimates': self._extract_eps_estimates(),
            'analyst_ratings': self._extract_analyst_ratings(),
            'snapshot': self._extract_snapshot()
        }
        
        return data
    
    def _extract_ticker(self) -> Optional[str]:
        """Extract ticker from input field"""
        try:
            ticker_input = self.window.find_element(
                By.CSS_SELECTOR,
                "input.uppercase.bg-\\[\\#121212\\]"
            )
            ticker_value = ticker_input.get_attribute('value')
            return ticker_value if ticker_value else None
        except Exception as e:
            print(f"Error extracting ticker: {e}")
            return None
    
    def _extract_company_header(self) -> Dict:
        """Extract company name, logo, website, address, CEO"""
        try:
            data = {}
            
            # Company name - extract from h1.text-2xl (not font-semibold)
            try:
                company_name_h1 = self.window.find_element(By.CSS_SELECTOR, "h1.text-2xl")
                # Get all text nodes, excluding the badge span
                full_text = company_name_h1.text
                # Try to find and remove the badge text
                try:
                    badge = company_name_h1.find_element(By.CSS_SELECTOR, "span.blue-box")
                    badge_text = badge.text.strip()
                    data['company_name'] = full_text.replace(badge_text, '').strip()
                except:
                    # If no badge found, use full text
                    data['company_name'] = full_text.strip()
            except Exception as e:
                print(f"Error extracting company name: {e}")
                data['company_name'] = None
            
            # Asset class - find blue-box span within the h1
            try:
                company_name_h1 = self.window.find_element(By.CSS_SELECTOR, "h1.text-2xl")
                asset_class = company_name_h1.find_element(By.CSS_SELECTOR, "span.blue-box")
                data['asset_class'] = asset_class.text.strip()
            except:
                # Fallback: try finding blue-box anywhere
                try:
                    asset_class = self.window.find_element(By.CSS_SELECTOR, "span.blue-box")
                    data['asset_class'] = asset_class.text.strip()
                except:
                    data['asset_class'] = None
            
            # Logo URL
            try:
                logo_div = self.window.find_element(By.CSS_SELECTOR, "div.w-16.h-16")
                logo_style = logo_div.get_attribute('style')
                if 'background-image: url(' in logo_style:
                    if 'url("' in logo_style:
                        logo_url = logo_style.split('url("')[1].split('")')[0]
                    elif 'url(&quot;' in logo_style:
                        logo_url = logo_style.split('url(&quot;')[1].split('&quot;)')[0]
                    else:
                        logo_url = logo_style.split('url(')[1].split(')')[0].strip('"\'')
                    data['logo_url'] = logo_url
                else:
                    data['logo_url'] = None
            except Exception as e:
                print(f"Error extracting logo: {e}")
                data['logo_url'] = None
            
            # Website - find link with target='_blank' in the company header area
            try:
                # Look for link in the company header section (has orange color style)
                website_link = self.window.find_element(
                    By.XPATH,
                    ".//a[@target='_blank' and @href and contains(@style, 'rgb(255, 117, 26)')]"
                )
                data['website'] = website_link.get_attribute('href')
            except:
                # Fallback: any link with target='_blank'
                try:
                    website_link = self.window.find_element(By.CSS_SELECTOR, "a[href][target='_blank']")
                    data['website'] = website_link.get_attribute('href')
                except Exception as e:
                    print(f"Error extracting website: {e}")
                    data['website'] = None
            
            # Address and CEO - find the text-right uppercase div
            try:
                info_div = self.window.find_element(
                    By.XPATH,
                    ".//div[contains(@class, 'text-right') and contains(@class, 'uppercase')]"
                )
                info_text = info_div.text
                info_lines = [line.strip() for line in info_text.split('\n') if line.strip()]
                data['address'] = info_lines[0] if len(info_lines) > 0 else None
                data['ceo'] = info_lines[1] if len(info_lines) > 1 else None
            except Exception as e:
                print(f"Error extracting address/CEO: {e}")
                data['address'] = None
                data['ceo'] = None
            
            return data
        except Exception as e:
            print(f"Error extracting company header: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def _extract_description(self) -> Optional[str]:
        """Extract company description"""
        try:
            desc_divs = self.window.find_elements(By.XPATH, ".//div[contains(@style, 'color: rgb(234, 234, 234)')]")
            for div in desc_divs:
                text = div.text.strip()
                if len(text) > 100:
                    text = text.replace("See more", "").replace("See less", "").strip()
                    return text
            return None
        except Exception as e:
            print(f"Error extracting description: {e}")
            return None
    
    def _extract_eps_estimates(self) -> Dict:
        """Extract EPS estimates - returns flat dict like {'Q4, Dec 25': '-0.85'}"""
        try:
            eps_data = {}
            # Find EPS ESTIMATES span, get its parent div, then find following table
            eps_table = self.window.find_element(
                By.XPATH,
                ".//span[text()='EPS ESTIMATES']/ancestor::div[1]/following-sibling::table"
            )
            
            # Get headers (Q3, FY26, FY27, etc.) from thead
            headers = []
            try:
                header_row = eps_table.find_element(By.TAG_NAME, "thead")
                header_cells = header_row.find_elements(By.TAG_NAME, "td")
                for cell in header_cells:
                    text = cell.text.strip()
                    if text and text.lower() != '':
                        headers.append(text)
            except Exception as e:
                print(f"Error extracting EPS headers: {e}")
                return {}
            
            # Get data rows from tbody
            tbody = eps_table.find_element(By.TAG_NAME, "tbody")
            rows = tbody.find_elements(By.TAG_NAME, "tr")
            
            date_row = None
            eps_row = None
            
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) > 0:
                    row_label = cells[0].text.strip().lower()
                    if row_label == 'date':
                        date_row = [cell.text.strip() for cell in cells[1:]]
                    elif row_label == 'eps':
                        eps_row = [cell.text.strip() for cell in cells[1:]]
            
            # Combine headers with dates and EPS values
            if date_row and eps_row and headers:
                for i, header in enumerate(headers):
                    if i < len(date_row) and i < len(eps_row):
                        key = f"{header}, {date_row[i]}"
                        eps_data[key] = eps_row[i]
            
            return eps_data
        except Exception as e:
            print(f"Error extracting EPS estimates: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def _extract_analyst_ratings(self) -> List[Dict]:
        """Extract analyst ratings table"""
        try:
            import pandas as pd
            ratings = []
            # Find the ANALYST RATINGS header, then get the following div with the table
            ratings_table = self.window.find_element(
                By.XPATH,
                ".//span[text()='ANALYST RATINGS']/ancestor::div[1]/following-sibling::div[@class='w-full']//table"
            )
            
            tbody = ratings_table.find_element(By.TAG_NAME, "tbody")
            rows = tbody.find_elements(By.TAG_NAME, "tr")
            
            for row in rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 5:
                        # Get firm name and skip if empty
                        firm = cells[0].text.strip()
                        if not firm:
                            continue
                            
                        # Handle target price specially since it has a complex structure
                        target_cell = cells[3]
                        target_spans = target_cell.find_elements(By.TAG_NAME, "span")
                        old_target = ""
                        new_target = ""
                        
                        if target_spans:
                            # Extract old and new prices - first span is old, last span is new
                            old_target = target_spans[0].text.strip() if len(target_spans) > 0 else ""
                            # If there are 3+ spans, the last one is the new target
                            if len(target_spans) >= 3:
                                new_target = target_spans[-1].text.strip()
                            elif len(target_spans) == 2:
                                # Sometimes there's just old and new
                                new_target = target_spans[1].text.strip()
                            else:
                                new_target = old_target
                        
                        rating = {
                            'Firm': firm,
                            'Analyst': cells[1].text.strip(),
                            'Rating': cells[2].text.strip(),
                            'Old_Target': old_target,
                            'New_Target': new_target,
                            'Date': cells[4].text.strip()
                        }
                        
                        # Only add if we have actual data
                        if rating['Firm'] and rating['Analyst'] and rating['Rating']:
                            ratings.append(rating)
                            
                except Exception as e:
                    print(f"Error extracting rating row: {e}")
                    continue
            
            ''' Currently not printing out the contents of the DataFrame to avoid cluttering the console.
            If you want to see the contents of the DataFrame, you can uncomment the code below.
            # Convert to DataFrame for inspection
            if ratings:
                df = pd.DataFrame(ratings)
                print("\nAnalyst Ratings DataFrame:")
                print("Shape:", df.shape)
                print("\nContents:")
                print(df)
                print("\nEmpty Values:")
                print(df.isna().sum())
            '''
            return ratings
        except Exception as e:
            print(f"Error extracting analyst ratings: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _extract_snapshot(self) -> Dict:
        """Extract snapshot data - returns flat dict"""
        try:
            snapshot = {}
            # Find SNAPSHOT div, then get the following flex-1 div
            snapshot_div = self.window.find_element(
                By.XPATH,
                ".//div[text()='SNAPSHOT']/following-sibling::div[@class='flex-1']"
            )
            
            # Find all sections with mt-2 class
            sections = snapshot_div.find_elements(By.CSS_SELECTOR, "div.mt-2")
            
            for section in sections:
                try:
                    # Find all key-value pairs in this section
                    pairs = section.find_elements(By.CSS_SELECTOR, "div.flex.justify-between.text-sm")
                    
                    for pair in pairs:
                        spans = pair.find_elements(By.TAG_NAME, "span")
                        if len(spans) >= 2:
                            key = spans[0].text.strip()
                            # Get value from second span, or from abbr if present
                            value_span = spans[1]
                            # Check if there's an abbr tag inside (for exchange codes)
                            try:
                                abbr = value_span.find_element(By.TAG_NAME, "abbr")
                                value = abbr.get_attribute('title') or abbr.text.strip()
                            except:
                                value = value_span.text.strip()
                            
                            if key and value:
                                snapshot[key] = value
                except Exception as e:
                    print(f"Error extracting snapshot section: {e}")
                    continue
            
            return snapshot
        except Exception as e:
            print(f"Error extracting snapshot: {e}")
            import traceback
            traceback.print_exc()
            return {} 