"""Search for invoice / summary tables."""
import pyodbc

DSN = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=10.10.0.9,1433;"
    "DATABASE=PharmaCRM;"
    "UID=softroniccrm;"
    "PWD={Admin123@};"
    "Encrypt=no;"
    "TrustServerCertificate=yes;"
)
conn = pyodbc.connect(DSN, timeout=30, autocommit=True)
cur = conn.cursor()

cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE 'SS_Invoice%' OR TABLE_NAME LIKE '%Sales%'")
tables = [r[0] for r in cur.fetchall()]
print(f"Candidate Tables: {tables}")

for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t} WITH (NOLOCK)")
    cnt = cur.fetchone()[0]
    print(f"{t}: {cnt} rows")

conn.close()
