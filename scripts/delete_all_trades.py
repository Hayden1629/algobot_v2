"""
Script to delete ALL trades from the Railway SQL database trades table.

⚠️  WARNING: This will permanently delete ALL trades from the database.
This action cannot be undone.

This script connects to the Railway MySQL database remotely using the public TCP proxy.
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import railway_config FIRST to set up Railway environment variables for remote connection
import railway_config  # Sets up Railway environment variables for remote database connection
from database.db_manager import DatabaseManager
from loguru import logger


def delete_all_trades() -> int:
    """
    Delete ALL records from the trades table.
    Connects to Railway MySQL database remotely.
    
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
        logger.info(f"Querying trades table on remote Railway database...")
        db_manager._reconnect_if_needed()
        cursor = db_manager.connection.cursor()
        
        # First, count how many records will be deleted
        count_query = "SELECT COUNT(*) FROM trades"
        cursor.execute(count_query)
        count = cursor.fetchone()[0]
        
        if count == 0:
            logger.info("No trades found in the database")
            cursor.close()
            return 0
        
        # Show breakdown of trades
        closed_query = "SELECT COUNT(*) FROM trades WHERE is_closed = TRUE"
        cursor.execute(closed_query)
        closed_count = cursor.fetchone()[0]
        open_count = count - closed_count
        
        logger.warning("=" * 60)
        logger.warning("⚠️  WARNING: About to delete ALL trades from the database!")
        logger.warning("=" * 60)
        logger.warning(f"Total trades to delete: {count}")
        logger.warning(f"  - Closed trades: {closed_count}")
        logger.warning(f"  - Open trades: {open_count}")
        logger.warning("=" * 60)
        logger.warning("This action CANNOT be undone!")
        logger.warning("=" * 60)
        
        # Confirm deletion
        response = input("\nType 'DELETE ALL TRADES' to confirm: ").strip()
        
        if response != 'DELETE ALL TRADES':
            logger.info("Deletion cancelled by user")
            cursor.close()
            return 0
        
        # Delete all trades
        logger.warning("Deleting all trades...")
        delete_query = "DELETE FROM trades"
        cursor.execute(delete_query)
        deleted_count = cursor.rowcount
        
        db_manager.connection.commit()
        cursor.close()
        
        logger.success(f"Successfully deleted {deleted_count} trades from the database")
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error deleting trades: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            db_manager.connection.rollback()
        except:
            pass
        return -1
    finally:
        db_manager.close()


if __name__ == "__main__":
    logger.info("Starting deletion of ALL trades from Railway database")
    deleted = delete_all_trades()
    
    if deleted >= 0:
        logger.info(f"Deletion complete. {deleted} trades deleted.")
        sys.exit(0)
    else:
        logger.error("Deletion failed.")
        sys.exit(1)

