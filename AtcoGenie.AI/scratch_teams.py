"""Check what teams exist in SS_Team — uses the same config as the running server."""
import asyncio
from app.config import get_settings
from app.database.manager import DatabaseManager

async def main():
    s = get_settings()
    dm = DatabaseManager(s)
    await dm.initialize()

    # 1. Search for Betaderm
    rows = await dm.execute_raw("pharma", "SELECT TeamId, Name, Active FROM SS_Team WHERE Name LIKE ? ORDER BY Name", "%etaderm%")
    print("=== Betaderm matches ===")
    for r in rows:
        print(f"  ID={r['TeamId']:>4} | Name={r['Name']} | Active={r['Active']}")
    if not rows:
        print("  (NONE — 'Betaderm' does NOT exist as a team name)")

    # 2. All active teams
    rows2 = await dm.execute_raw("pharma", "SELECT TeamId, Name FROM SS_Team WHERE Active=1 ORDER BY TeamId")
    print(f"\n=== All {len(rows2)} active teams ===")
    for r in rows2:
        print(f"  ID={str(r['TeamId']):>4} | {r['Name']}")

    await dm.close()

asyncio.run(main())
