import asyncio
import pyodbc

# Read env manually to avoid depending on app context in a simple script
import dotenv
import os
import sys

dotenv.load_dotenv(override=True)

db_host = os.environ.get("PHARMA_DB_HOST")
db_port = os.environ.get("PHARMA_DB_PORT", "1433")
db_name = os.environ.get("PHARMA_DB_NAME")
db_user = os.environ.get("PHARMA_DB_USER")
db_password = os.environ.get("PHARMA_DB_PASSWORD")
db_driver = os.environ.get("PHARMA_DB_DRIVER")

conn_str = f"DRIVER={{{db_driver}}};SERVER={db_host},{db_port};DATABASE={db_name};UID={db_user};PWD={db_password};TrustServerCertificate=yes;"

try:
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    
    # 1. Search for potential SP names
    print("--- Searching for relevant Stored Procedures ---")
    search_terms = ['%Activity%', '%Expense%', '%Call%', '%Daily%']
    
    sp_names = []
    for term in search_terms:
        cursor.execute("SELECT name FROM sys.procedures WHERE name LIKE ?", term)
        results = [row[0] for row in cursor.fetchall()]
        for r in results:
            if r not in sp_names:
                sp_names.append(r)
                
    print(f"Found {len(sp_names)} matching SPs.")
    for sp in sorted(sp_names):
        print(f"  - {sp}")
        
    print("\n--- Parameters for matches ---")
    
    # Let's target specific names if they stand out, or just print params for all matches
    # to find the right ones.
    
    for sp in sorted(sp_names):
        if "Activity" in sp or "Expense" in sp or "Call" in sp:
            print(f"\n[{sp}] Parameters:")
            cursor.execute("""
                SELECT p.name AS param_name, t.name AS data_type, p.max_length
                FROM sys.parameters p
                INNER JOIN sys.procedures pr ON p.object_id = pr.object_id
                INNER JOIN sys.types t ON p.user_type_id = t.user_type_id
                WHERE pr.name = ?
                ORDER BY p.parameter_id
            """, sp)
            params = cursor.fetchall()
            if not params:
                print("  (No parameters)")
            for p in params:
                print(f"  {p.param_name} ({p.data_type})")
                
except Exception as e:
    print(f"Error: {e}")
