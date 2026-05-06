"""Check actual DB names in Postgres — case-sensitive check."""
import asyncio, asyncpg

async def test():
    c = await asyncpg.connect("postgresql://postgres:postgres@127.0.0.1:5432/postgres")
    rows = await c.fetch("SELECT datname FROM pg_database ORDER BY datname")
    for r in rows:
        print(f"  DB: [{r['datname']}]")
    await c.close()

asyncio.run(test())
