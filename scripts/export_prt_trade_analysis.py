"""
Export joined PRT data + trade data from the Railway MySQL database into a Pandas DataFrame
and save it to disk for offline analysis.

Joins:
    trades.id  <->  prt_data.trade_id

Outputs:
    - CSV:  prt_trade_analysis.csv  (in the algobot_v2 directory)
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import railway_config FIRST to set up Railway environment variables for remote connection
import railway_config  # Sets up Railway environment variables for remote database connection
from database.db_manager import DatabaseManager
from loguru import logger

import pandas as pd




def load_prt_trade_data():
    """
    Load joined trades + prt_data into a Pandas DataFrame.
    Uses DatabaseManager like other scripts in this folder.
    """
    db_manager = DatabaseManager()
    
    if not db_manager.is_available():
        logger.error("Database is not available. Check your Railway connection settings.")
        logger.error("Verify that railway_config.py has the correct Railway remote connection details.")
        raise Exception("Database connection failed")
    
    # Verify connection
    try:
        db_manager._reconnect_if_needed()
        test_cursor = db_manager.connection.cursor()
        test_cursor.execute("SELECT DATABASE(), VERSION()")
        db_name, db_version = test_cursor.fetchone()
        test_cursor.close()
        logger.info(f"Connected to Railway database: {db_name} (MySQL {db_version})")
    except Exception as e:
        logger.error(f"Failed to verify database connection: {e}")
        raise
    
    try:
        query = """
            SELECT
                t.id                AS trade_id,
                t.ticker,
                t.action,
                t.quantity,
                t.entry_price,
                t.exit_price,
                t.profit_loss,
                t.profit_loss_percent,
                t.time_placed,
                t.close_time,
                t.hold_time_minutes,
                t.order_id,
                t.is_closed,
                t.created_at       AS trade_created_at,
                t.updated_at       AS trade_updated_at,
                p.id               AS prt_id,
                p.edge,
                p.prob_up,
                p.mean,
                p.p10,
                p.p90,
                p.dist1,
                p.n,
                p.timestamp        AS prt_timestamp,
                p.created_at       AS prt_created_at
            FROM prt_data p
            INNER JOIN trades t
                ON p.trade_id = t.id
            ORDER BY t.time_placed ASC;
        """

        df = pd.read_sql(query, db_manager.connection)

        # Handle empty result set
        if df.empty:
            logger.warning("No trades found in database. Returning empty DataFrame.")
            return df

        # Derive some helper labels for analysis
        if "profit_loss" in df.columns:
            df["is_winner"] = df["profit_loss"] > 0
            df["is_loser"] = df["profit_loss"] < 0
            df["is_breakeven"] = df["profit_loss"] == 0

        # Simple label for stop-loss-triggered vs otherwise:
        # We don't have an explicit flag, but if the trade was closed and
        # exit_price was set by a stop, that will already be reflected in P&L.
        # You can refine this later once you add an explicit reason column.
        if "is_closed" in df.columns:
            df["closed"] = df["is_closed"].astype(bool)

        return df

    except Exception as e:
        logger.error(f"Error loading PRT trade data: {e}")
        raise
    finally:
        db_manager.close()


def main():
    df = load_prt_trade_data()

    # Save to CSV in algobot_v2 root
    project_root = Path(__file__).resolve().parents[1]
    out_path = project_root / "prt_trade_analysis.csv"

    df.to_csv(out_path, index=False)

    print(f"Saved {len(df)} joined PRT+trade rows to {out_path}")


if __name__ == "__main__":
    main()


