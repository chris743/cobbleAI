import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    "server": os.getenv("DB_SERVER", "RDGW-CF"),
    "database": os.getenv("DB_DATABASE", "DM03"),
    "username": os.getenv("DB_USERNAME"),
    "password": os.getenv("DB_PASSWORD"),
    "trusted_connection": os.getenv("DB_TRUSTED_CONNECTION", "yes").lower() == "yes",
    "context_path": os.getenv("CONTEXT_PATH", "./data-catalog"),
    "learning_path": os.getenv("LEARNING_PATH", "./agent-learning"),
    "max_rows": int(os.getenv("MAX_ROWS", "5000")),
    "query_timeout": int(os.getenv("QUERY_TIMEOUT", "30")),
}

# Build connection string
if CONFIG["trusted_connection"]:
    CONNECTION_STRING = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={CONFIG['server']};"
        f"DATABASE={CONFIG['database']};"
        f"Trusted_Connection=yes;"
    )
else:
    CONNECTION_STRING = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={CONFIG['server']};"
        f"DATABASE={CONFIG['database']};"
        f"UID={CONFIG['username']};"
        f"PWD={CONFIG['password']};"
        f"Encrypt=no;"
        f"TrustServerCertificate=yes;"
        f"Application Name=DM03_Agent;"
    )


# =============================================================================
# QUERY EXECUTOR
# =============================================================================
sql = """SELECT      Size, Grade,     SUM(AvailableQuantity) as TotalBins,     SUM(equivctns)
      as TotalCartonEquiv FROM dbo.VW_BININVENTORY WHERE AvailableQuantity > 0 
      AND Commodity = 'NAVEL'   AND Size = '088'   AND Grade = 'FANCY' GROUP BY
     Size, Grade"""

print(CONFIG)

conn = pyodbc.connect(CONNECTION_STRING, timeout=10)

if conn:
    print("im here")
    conn.close()
