"""
Script to delete portfolio_value_history records from Railway SQL database.
Deletes all records where timestamp is January 5th or before (default: 2025-01-05 23:59:59).

This script connects to the Railway MySQL database remotely using the public TCP proxy.
"""
import sys
import os
from datetime import datetime
import pytz

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import railway_config FIRST to set up Railway environment variables for remote connection
import railway_config  # Sets up Railway environment variables for remote database connection
from database.db_manager import DatabaseManager
from loguru import logger


def delete_portfolio_history_before_date(cutoff_date_str: str = "2025-01-05 23:59:59") -> int:
    """
    Delete all records from portfolio_value_history where timestamp <= cutoff_date.
    Connects to Railway MySQL database remotely.
    
    Args:
        cutoff_date_str: Date string in format 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD'
                        Defaults to '2025-01-05 23:59:59'
    
    Returns:
        int: Number of records deleted, or -1 if error occurred
    """
    # Log connection details (without password)
    railway_host = os.getenv('MYSQLHOST') or os.getenv('MYSQL_HOST')
    railway_port = os.getenv('MYSQLPORT') or os.getenv('MYSQL_PORT', '3306')
    railway_database = os.getenv('MYSQLDATABASE') or os.getenv('MYSQL_DATABASE', 'railway')
    railway_user = os.getenv('MYSQLUSER') or os.getenv('MYSQL_USER', 'root')
    
    if railway_host:
        logger.info(f"Connecting to Railway MySQL database remotely:")
        logger.info(f"  Host: {railway_host}")
        logger.info(f"  Port: {railway_port}")
        logger.info(f"  Database: {railway_database}")
        logger.info(f"  User: {railway_user}")
    else:
        logger.error("Railway connection details not found. Make sure railway_config.py is set up correctly.")
        return -1
    
    db_manager = DatabaseManager()
    
    if not db_manager.is_available():
        logger.error("Database is not available. Check your Railway connection settings.")
        logger.error("Verify that railway_config.py has the correct Railway remote connection details.")
        return -1
    
    # Verify connection by testing a simple query
    try:
        db_manager._reconnect_if_needed()
        test_cursor = db_manager.connection.cursor()
        test_cursor.execute("SELECT DATABASE(), VERSION()")
        db_name, db_version = test_cursor.fetchone()
        test_cursor.close()
        logger.success(f"Successfully connected to remote Railway database: {db_name} (MySQL {db_version})")
    except Exception as e:
        logger.error(f"Failed to verify database connection: {e}")
        return -1
    
    try:
        # Parse the cutoff date
        try:
            # Try parsing with time first
            cutoff_date = datetime.strptime(cutoff_date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                # Try parsing with just date (defaults to end of day)
                cutoff_date = datetime.strptime(cutoff_date_str, "%Y-%m-%d")
                cutoff_date = cutoff_date.replace(hour=23, minute=59, second=59)
            except ValueError:
                logger.error(f"Invalid date format: {cutoff_date_str}. Use 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD'")
                return -1
        
        # Localize to UTC if no timezone info
        if cutoff_date.tzinfo is None:
            cutoff_date = pytz.UTC.localize(cutoff_date)
        else:
            cutoff_date = cutoff_date.astimezone(pytz.UTC)
        
        logger.info(f"Querying portfolio_value_history table on remote Railway database...")
        db_manager._reconnect_if_needed()
        cursor = db_manager.connection.cursor()
        
        # First, count how many records will be deleted
        count_query = """
            SELECT COUNT(*) FROM portfolio_value_history 
            WHERE timestamp <= %s
        """
        cursor.execute(count_query, (cutoff_date,))
        count = cursor.fetchone()[0]
        
        if count == 0:
            logger.info(f"No records found with timestamp <= {cutoff_date_str}")
            cursor.close()
            return 0
        
        # Confirm deletion
        logger.warning(f"About to delete {count} records from portfolio_value_history where timestamp <= {cutoff_date_str}")
        response = input("Are you sure you want to proceed? (yes/no): ").strip().lower()
        
        if response != 'yes':
            logger.info("Deletion cancelled by user")
            cursor.close()
            return 0
        
        # Delete the records
        delete_query = """
            DELETE FROM portfolio_value_history 
            WHERE timestamp <= %s
        """
        cursor.execute(delete_query, (cutoff_date,))
        deleted_count = cursor.rowcount
        
        db_manager.connection.commit()
        cursor.close()
        
        logger.success(f"Successfully deleted {deleted_count} records from portfolio_value_history")
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error deleting portfolio history: {e}")
        try:
            db_manager.connection.rollback()
        except:
            pass
        return -1
    finally:
        db_manager.close()


if __name__ == "__main__":
    # Default to January 5th, 2025 at end of day
    cutoff_date = "2025-01-05 23:59:59"
    
    # Allow command line argument to override
    if len(sys.argv) > 1:
        cutoff_date = sys.argv[1]
    
    logger.info(f"Starting deletion of portfolio_value_history records <= {cutoff_date}")
    deleted = delete_portfolio_history_before_date(cutoff_date)
    
    if deleted >= 0:
        logger.info(f"Deletion complete. {deleted} records deleted.")
        sys.exit(0)
    else:
        logger.error("Deletion failed.")
        sys.exit(1)

