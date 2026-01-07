"""
Commission blacklist for stocks that have trading commissions.
These stocks should be avoided to prevent commission fees.
"""

# Blacklist of known commission stocks (based on user's experience)
COMMISSION_BLACKLIST = {
    'ASST',  # STRIVE INC CLASS A
    'UP',    # WHEELS UP EXPERIENCE INC CLASS A
    'AMC',   # AMC ENTMT HLDGS INC CLASS CLASS A
    'BTBT',  # BATTLEBIT TECHNOLOGIES INC CLASS A
    'BTQ',
    'PLUG',  # PLUG POWER INC CLASS A
    'BITF',  # BITFINEX LTD CLASS A
    'DNN',
    'BTG',
    'RIG',
    'RXRX',
    'BBAI',
    'GRAB',
    'JBLU',
    'NIO',
    'CAN',
    'MARA',
    'ONDS',
    'RDW',
    'SOC',
    'BMNR',
    'AAL',
    'ACHR',
    'VG',
    'RZLV',
    'SOUN',
    'WULF',
    'CLSK',
    'CIFR',
    'CDE',
    'DJT',   # TRUMP MEDIA & TECHNO
    'HL',    # HECLA MNG CO
    'HYMC',  # HYCROFT MNG HLDG CORP CLASS A
    'IOVA',  # IOVANCE BIOTHERAPEUTICS
    'OMER',  # OMEROS CORP
    'OWL',   # BLUE OWL CAP INC CLASS A
    'PATH',  # UIPATH INC CLASS CLASS A
    'QBTS',  # D-WAVE QUANTUM INC
    'QUBT',  # QUANTUM COMPUTING INC
    'RGTI',  # RIGETTI COMPUTING INC
    'RITM',  # RITHM CAPITAL CORP REIT
    'RIVN',  # RIVIAN AUTOMOTIVE INC CLASS A
    'JOBY',
    'SBSW',
    'SNAP',
    'BBD',
    'AUR',
    'AGNC',
    'VALE',
    'PBR',
    'QS',
    'RIOT',
    'NGD',
    'SAN',
    'BCS',
    'CMCSA',
    'ET',
    'F',
    'INFY',
    'LYG',
}


def is_blacklisted(ticker: str) -> bool:
    """
    Check if a ticker is in the commission blacklist.
    
    Args:
        ticker: Stock ticker symbol
    
    Returns:
        bool: True if ticker is blacklisted, False otherwise
    """
    return ticker.upper() in COMMISSION_BLACKLIST


def filter_blacklisted_tickers(tickers: list) -> tuple[list, list]:
    """
    Filter out blacklisted tickers from a list.
    
    Args:
        tickers: List of ticker symbols
    
    Returns:
        tuple: (filtered_tickers, blacklisted_tickers)
    """
    filtered = []
    blacklisted = []
    
    for ticker in tickers:
        if is_blacklisted(ticker):
            blacklisted.append(ticker)
        else:
            filtered.append(ticker)
    
    return filtered, blacklisted

