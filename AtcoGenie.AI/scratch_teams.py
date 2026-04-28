import asyncio
from app.database.manager import DatabaseManager
from app.config import get_settings

async def main():
    s = get_settings()
    db = DatabaseManager(s)
    await db.initialize()
    
    # Find team-related tables
    rows = await db.execute_raw("pharma", "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE '%eam%' ORDER BY TABLE_NAME")
    print("=== Team-related tables ===")
    for r in rows:
        print(r)
    
    # Also check SP that resolves teams
    print("\n=== Sp_GetEmployeeWiseTeam for emp 19762 ===")
    rows2 = await db.execute_sp("pharma", "Sp_GetEmployeeWiseTeam", "19762")
    print(f"Rows: {len(rows2)}")
    for r in rows2:
        print(r)

    # Try to find a team setup/master table
    print("\n=== Looking for team setup tables ===")
    for tbl in ["SS_TeamSetup", "SS_Team_Setup", "TeamSetup", "Team_Setup", "SS_Team", "Teams"]:
        try:
            r = await db.execute_raw("pharma", f"SELECT TOP 5 * FROM {tbl}")
            print(f"\n>> {tbl} - {len(r)} rows:")
            for row in r:
                print(row)
        except Exception as e:
            pass  # table doesn't exist

asyncio.run(main())
