import numpy as np
from datetime import datetime, timedelta
from massive import RESTClient  # Compatible with Massive API
from constants.parameters import MASSIVE_API_KEY
import pandas as pd
import time
# Initialize client with your API key
client = RESTClient(api_key=MASSIVE_API_KEY)  # Or use os.environ['POLYGON_API_KEY']

# Define parameters
symbol = "AAPL"  # Replace with your stock symbol, e.g., "MSFT"
end_date = datetime.now()
start_date = end_date - timedelta(days=365)  # Last 1 year; adjust as needed
multiplier = 1  # For daily bars
timespan = "day"

def get_std_dev(symbol: str, start_date: datetime, end_date: datetime, multiplier: int = 1, timespan: str = "day") -> float:
    aggs = client.get_aggs(
        ticker=symbol,
        multiplier=multiplier,
        timespan=timespan,
        from_=start_date.strftime("%Y-%m-%d"),
        to=end_date.strftime("%Y-%m-%d"),
        adjusted=True,  # Adjust for splits/dividends
        sort="asc",
        limit=50000  # Sufficient for 1 year
    )

    # Extract closing prices
    if not aggs:
        raise ValueError(f"No data returned for {symbol}")

    closes = np.array([agg.close for agg in aggs])

    # Compute daily returns (skip first day)
    returns = np.diff(closes) / closes[:-1]

    # Calculate std dev
    daily_std_dev = np.std(returns)
    annualized_std_dev = daily_std_dev * np.sqrt(252)  # Annualize assuming 252 trading days
    '''
    print(f"Stock: {symbol}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Daily Std Dev: {daily_std_dev:.4f}")
    print(f"Annualized Std Dev: {annualized_std_dev:.4f} (approx. {annualized_std_dev * 100:.2f}%)")
    '''
    return annualized_std_dev

if __name__ == "__main__":
    print(MASSIVE_API_KEY)
    data = pd.read_csv("/home/hayden/code/algobot_v2/prt_trade_analysis.csv")
    tickers_series_unique = data['ticker'].unique()
    print(tickers_series_unique)
    for ticker in tickers_series_unique:
        #make a dictionary of ticker and std dev
        ticker_std_dev = {}
        ticker_std_dev[ticker] = get_std_dev(ticker, start_date, end_date, multiplier, timespan)
        print(f"Ticker: {ticker}, Std Dev: {ticker_std_dev[ticker]:.4f}")
        time.sleep(13)
    #save the dictionary to a csv
    pd.DataFrame(ticker_std_dev.items(), columns=['ticker', 'std_dev']).to_csv('/home/hayden/code/algobot_v2/ticker_std_dev.csv', index=False)