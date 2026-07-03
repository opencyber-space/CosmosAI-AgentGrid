import pymysql
import logging

class TiDBInterface:
    def __init__(self, mysql_url: str):
        """
        mysql_url: format -> 'mysql+pymysql://user:password@host:port/dbname'
        """
        self.mysql_url = mysql_url
        self.logger = logging.getLogger("TiDBInterface")
        self.connection = None

    def connect(self):
        try:
            from sqlalchemy.engine.url import make_url
            url = make_url(self.mysql_url)

            self.connection = pymysql.connect(
                host=url.host,
                port=url.port or 4000,
                user=url.username,
                password=url.password,
                database=url.database,
                charset='utf8mb4',
                autocommit=True
            )

            self.logger.info(f"Connected to TiDB at {url.host}:{url.port}/{url.database}")
            self._ensure_table_exists()

        except Exception as e:
            self.logger.error(f"Failed to connect to TiDB: {e}")
            raise

    def _ensure_table_exists(self):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS data_table (
                        `key` VARCHAR(255) PRIMARY KEY,
                        `data` LONGBLOB
                    );
                """)
                self.logger.info("Ensured data_table exists.")
        except Exception as e:
            self.logger.error(f"Error ensuring table exists: {e}")
            raise

    def set(self, key: str, data: bytes):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    REPLACE INTO data_table (`key`, `data`)
                    VALUES (%s, %s);
                """, (key, data))
                self.logger.debug(f"Set key='{key}' ({len(data)} bytes)")
        except Exception as e:
            self.logger.error(f"Error setting key '{key}' in TiDB: {e}")
            raise

    def get(self, key: str) -> bytes:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT `data` FROM data_table WHERE `key` = %s;", (key,))
                result = cursor.fetchone()
                if result:
                    self.logger.debug(f"Fetched key='{key}' ({len(result[0])} bytes)")
                    return result[0]
                else:
                    self.logger.warning(f"Key '{key}' not found in TiDB")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting key '{key}' from TiDB: {e}")
            raise
