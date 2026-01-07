"""
Database initialization module for algobot_v2.
Handles creating and initializing the local SQLite database.
"""
import sqlite3
from pathlib import Path
from loguru import logger
from constants.parameters import DATABASE_NAME, DATABASE_TYPE
from typing import Optional


def get_database_path() -> Path:
    """Get the path to the database file."""
    project_root = Path(__file__).parent.parent
    return project_root / DATABASE_NAME


def init_database() -> bool:
    """
    Initialize the local SQLite database with schema.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        db_path = get_database_path()
        
        logger.info(f"Initializing database at {db_path}...")
        
        # Connect to SQLite database (creates file if it doesn't exist)
        connection = sqlite3.connect(str(db_path))
        connection.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
        
        cursor = connection.cursor()
        
        # Read and execute schema file
        schema_file = Path(__file__).parent / "schema.sql"
        if not schema_file.exists():
            logger.error(f"Schema file not found at {schema_file}")
            return False
        
        logger.info(f"Reading schema from {schema_file}...")
        with open(schema_file, 'r') as f:
            schema_sql = f.read()
        
        # Execute schema (SQLite can execute multiple statements)
        # Split by semicolons and execute each statement
        statements = [s.strip() for s in schema_sql.split(';') if s.strip() and not s.strip().startswith('--')]
        
        logger.info("Creating tables...")
        for statement in statements:
            if statement:
                try:
                    cursor.execute(statement)
                    logger.debug(f"Executed: {statement[:50]}...")
                except sqlite3.Error as e:
                    # Some errors are expected (e.g., table already exists)
                    if "already exists" not in str(e).lower():
                        logger.warning(f"Schema execution warning: {e}")
        
        connection.commit()
        cursor.close()
        connection.close()
        
        logger.info(f"Database '{db_path}' initialized successfully!")
        return True
        
    except sqlite3.Error as e:
        logger.error(f"Error initializing database: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error initializing database: {e}")
        return False


def database_exists() -> bool:
    """Check if database file exists."""
    return get_database_path().exists()


def get_connection() -> Optional[sqlite3.Connection]:
    """
    Get a connection to the database.
    
    Returns:
        SQLite connection object, or None if connection fails
    """
    try:
        db_path = get_database_path()
        
        # Initialize database if it doesn't exist
        if not database_exists():
            logger.info("Database not found, initializing...")
            if not init_database():
                logger.error("Failed to initialize database")
                return None
        
        connection = sqlite3.connect(str(db_path))
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
        
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database: {e}")
        return None


if __name__ == "__main__":
    """Run database initialization as standalone script."""
    print("=" * 60)
    print("Algobot v2 Database Initialization")
    print("=" * 60)
    print()
    
    success = init_database()
    
    if success:
        print(f"\n✅ Database initialized successfully!")
        print(f"   Location: {get_database_path()}")
        print("\nYou can now run the algorithm and it will store trades in the database.")
    else:
        print("\n❌ Database initialization failed")
        print("Please check the logs for details.")

