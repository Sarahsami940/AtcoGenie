"""Final targeted query — Users table + UserFormRights + GroupFormRights for PharmaCRM."""
import pyodbc

DSN = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=10.10.0.88,1433;"
    "DATABASE=Security;"
    "UID=dakiadbreader;"
    "PWD={s0ftr0n1c@5607};"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)

conn = pyodbc.connect(DSN, timeout=10)
cur = conn.cursor()

def safe_str(v):
    if isinstance(v, (bytes, bytearray)):
        return "<bin>"
    elif v is None:
        return "NULL"
    else:
        return str(v)[:35].strip()

# 1. Users table schema
print("=== Security.Users — Schema ===")
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME='Users' ORDER BY ORDINAL_POSITION
""")
for r in cur.fetchall():
    print(f"  {r[0]:30} {r[1]}")

print("\n  Sample (top 5):")
cur.execute("SELECT TOP 5 * FROM Users WITH (NOLOCK)")
cols = [d[0] for d in cur.description]
print("  " + " | ".join(cols))
for r in cur.fetchmany(5):
    print("  " + " | ".join(safe_str(v) for v in r))

# 2. UserFormRights schema
print("\n=== Security.UserFormRights — Schema ===")
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME='UserFormRights' ORDER BY ORDINAL_POSITION
""")
for r in cur.fetchall():
    print(f"  {r[0]:30} {r[1]}")

cur.execute("SELECT COUNT(*) FROM UserFormRights WITH (NOLOCK)")
print(f"\n  Total rows: {cur.fetchone()[0]}")

print("\n  Sample — PharmaCRM ReportsMode='Y' rows (top 10):")
cur.execute("""
    SELECT TOP 10 UserID, ApplicationCode, FormID, ViewMode, ReportsMode, Delflag
    FROM UserFormRights WITH (NOLOCK)
    WHERE ApplicationCode='PharmaCRM' AND ReportsMode='Y' AND Delflag='N'
""")
cols = [d[0] for d in cur.description]
print("  " + " | ".join(cols))
for r in cur.fetchmany(10):
    print("  " + " | ".join(safe_str(v) for v in r))

# 3. GroupFormRights for PharmaCRM — correct column name
print("\n=== GroupFormRights — PharmaCRM Sample ===")
cur.execute("""
    SELECT TOP 10 GroupCode, ApplicationCode, FormID, ViewMode, ReportsMode, Delflag
    FROM GroupFormRights WITH (NOLOCK)
    WHERE ApplicationCode='PharmaCRM' AND ReportsMode='Y' AND Delflag='N'
""")
cols = [d[0] for d in cur.description]
print("  " + " | ".join(cols))
for r in cur.fetchmany(10):
    print("  " + " | ".join(safe_str(v) for v in r))

# 4. UserMapping - linking users to groups?
print("\n=== UserMapping — Schema + Sample ===")
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME='UserMapping' ORDER BY ORDINAL_POSITION
""")
for r in cur.fetchall():
    print(f"  {r[0]:30} {r[1]}")

cur.execute("SELECT TOP 5 * FROM UserMapping WITH (NOLOCK)")
cols = [d[0] for d in cur.description]
print("  " + " | ".join(cols))
for r in cur.fetchmany(5):
    print("  " + " | ".join(safe_str(v) for v in r))

# 5. tblUserDetails — possible AD-to-SecurityUser link
print("\n=== tblUserDetails — Schema + Sample ===")
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME='tblUserDetails' ORDER BY ORDINAL_POSITION
""")
for r in cur.fetchall():
    print(f"  {r[0]:30} {r[1]}")

cur.execute("SELECT TOP 5 * FROM tblUserDetails WITH (NOLOCK)")
cols = [d[0] for d in cur.description]
print("  " + " | ".join(cols))
for r in cur.fetchmany(5):
    print("  " + " | ".join(safe_str(v) for v in r))

conn.close()
