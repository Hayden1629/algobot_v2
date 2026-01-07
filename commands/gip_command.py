"""
GIP (Intraday Chart) Command
Displays intraday price chart (data extraction not yet implemented)
"""

from selenium.webdriver.common.by import By
from datetime import datetime
from typing import Dict, Optional

from core.controller import BaseCommand


class GIPCommand(BaseCommand):
    """Intraday Chart (GIP) command - displays intraday price chart"""
    
    def get_command_string(self, ticker: str, asset_class: str) -> str:
        return f"{ticker} {asset_class} GIP"
    
    def extract_data(self) -> Dict:
        """Extract intraday chart data - placeholder for future implementation"""
        data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'window_id': self.window_id,
            'ticker': self._extract_ticker(),
            'type': 'intraday_chart',
            'note': 'Intraday chart data extraction not yet implemented'
        }
        return data
    
    def _extract_ticker(self) -> Optional[str]:
        """Extract ticker from input field"""
        try:
            ticker_input = self.window.find_element(By.CSS_SELECTOR, "input[value]")
            return ticker_input.get_attribute('value')
        except:
            return None 