import asyncio
from app.database.manager import DatabaseManager
from app.config import get_settings

async def find_team_tables():
    settings = get_settings()
    db = DatabaseManager(settings)
    await db.initialize_pools()
    rows = await db.execute_raw("pharma", "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE '%Team%' OR TABLE_NAME LIKE '%dept%'")
    for r in rows:
        print(r)

if __name__ == "__main__":
    asyncio.run(find_team_tables())
