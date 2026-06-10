import os
import sqlite3
import logging
from datetime import datetime

# Configure a professional engineering logging system
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

class EdgeDatabaseManager:
    """
    Handles initialization, connection lifecycles, and relational execution 
    for the local SQLite database running on the edge hardware nodes.
    """
    
    def __init__(self, database_path: str = "local_edge_cache.db"):
        """
        Initializes the database management service layer with a persistent file destination.
        """
        self.database_path = database_path
        self.connection = None

    def connect(self) -> sqlite3.Connection:
        """
        Establishes a connection to the SQLite database file and enforces standard performance settings.
        """
        try:
            self.connection = sqlite3.connect(self.database_path)
            
            # CRITICAL FOR RELATIONAL INTEGRITY: SQLite disables foreign key tracking by default.
            # This operational pragma statement forces runtime validation of all foreign keys.
            self.connection.execute("PRAGMA foreign_keys = ON;")
            
            # Performance optimization: Enable Write-Ahead Logging (WAL) mode for simultaneous 
            # read/write operations during real-time camera face detection checks.
            self.connection.execute("PRAGMA journal_mode = WAL;")
            
            return self.connection
        except sqlite3.Error as error:
            logging.error(f"Failed to initialize database connection framework: {error}")
            raise

    def close_connection(self):
        """
        Safely disposes of active transactional connection pointers to mitigate write locks.
        """
        if self.connection:
            self.connection.close()
            logging.info("Edge database connection pool closed cleanly.")

    def create_schema(self):
        """
        Executes structural schema generation scripts sequentially to satisfy cross-table 
        relational validation dependencies.
        """
        if not self.connection:
            self.connect()

        cursor = self.connection.cursor()
        logging.info("Compiling local 3NF edge layout tables...")

        try:
            # =========================================================================
            # STAGE 1: FOUNDATIONAL REFERENCE TABLES (No Foreign Key Targets)
            # =========================================================================

            # Table 1: device_roles
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_roles (
                    role_id INTEGER PRIMARY KEY NOT NULL,
                    role_name TEXT NOT NULL,
                    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Table 2: device_users
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_users (
                    user_id INTEGER PRIMARY KEY NOT NULL,
                    face_vector BLOB NOT NULL,
                    is_active INTEGER DEFAULT 1 NOT NULL,
                    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Table 3: device_info
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    node_id INTEGER NOT NULL,
                    location_name TEXT NOT NULL,
                    last_cloud_sync DATETIME NULL
                );
            """)

            # =========================================================================
            # STAGE 2: RELATIONAL CLEARANCE MATRICES & TRANSACTIONS (Contains FK Targets)
            # =========================================================================

            # Table 4: device_user_roles (Composite mapping architecture)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_user_roles (
                    user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, role_id),
                    FOREIGN KEY (user_id) REFERENCES device_users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE
                );
            """)

            # Table 5: device_node_rbac
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_node_rbac (
                    node_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (node_id, role_id),
                    FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE
                );
            """)

            # Table 6: device_auth_logs (Offline-buffered verification telemetry)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_auth_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NULL,
                    auth_status TEXT NOT NULL,
                    confidence_score REAL NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    sync_status INTEGER DEFAULT 0 NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES device_users(user_id) ON DELETE SET NULL
                );
            """)

            # =========================================================================
            # STAGE 3: INDEX CREATION FOR ULTRA-LOW LATENCY QUERIES
            # =========================================================================
            
            # Accelerates the LAN chronological cache replay engine when sorting unsynced tracking arrays
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_logs_sync ON device_auth_logs(sync_status);")
            
            # Optimizes validation processing during immediate user login authorization checks
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_roles_lookup ON device_user_roles(user_id);")

            self.connection.commit()
            logging.info("All 6 edge schema tables and indexing targets built successfully.")

        except sqlite3.Error as error:
            self.connection.rollback()
            logging.critical(f"Aborting database transaction loop. Fatal compilation error: {error}")
            raise
        finally:
            cursor.close()

    def seed_initial_roles(self):
        """
        Seeds foundational reference states to handle security assignments without cloud reliance.
        """
        cursor = self.connection.cursor()
        
        # Identity indices match master seed structures identically
        default_roles = [
            (1, "ADMIN"),
            (2, "STAFF"),
            (3, "LECTURER"),
            (4, "STUDENT"),
            (5, "VISITOR")
        ]
        
        try:
            cursor.executemany("""
                INSERT OR IGNORE INTO device_roles (role_id, role_name)
                VALUES (?, ?);
            """, default_roles)
            
            self.connection.commit()
            logging.info(f"Successfully verified/seeded {len(default_roles)} primary identity roles.")
        except sqlite3.Error as error:
            self.connection.rollback()
            logging.error(f"Error executing static role seeds: {error}")
            raise
        finally:
            cursor.close()

def main():
    # Instantiate the database management class
    db_manager = EdgeDatabaseManager("local_edge_cache.db")
    
    try:
        logging.info("Starting automated edge system setup context...")
        db_manager.create_schema()
        db_manager.seed_initial_roles()
        logging.info("Edge database pipeline initialization completed successfully.")
    except Exception as error:
        logging.critical(f"Local environment build sequence terminated unexpectedly: {error}")
    finally:
        db_manager.close_connection()

if __name__ == "__main__":
    main()