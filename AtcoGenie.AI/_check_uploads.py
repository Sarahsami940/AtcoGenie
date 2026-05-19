import asyncio, asyncpg, os
from dotenv import load_dotenv
load_dotenv()

async def main():
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "atcogenie_checkpoints")
    user = os.getenv("POSTGRES_USER", "postgres")
    pw = os.getenv("POSTGRES_PASSWORD", "postgres")
    dsn = f"postgresql://{user}:{pw}@{host}:{port}/{db}"

    conn = await asyncpg.connect(dsn)
    rows = await conn.fetch(
        "SELECT id, filename, status, error_message, created_at "
        "FROM document_uploads ORDER BY created_at DESC LIMIT 10"
    )
    print(f"Total records: {len(rows)}")
    for r in rows:
        err = (r["error_message"] or "-")[:80]
        print(f'  {r["created_at"]} | {r["status"]:<12} | {r["filename"][:40]:<40} | {err}')

    # Clean error records
    deleted = await conn.execute("DELETE FROM document_uploads WHERE status='error'")
    print(f"\nCleaned: {deleted}")

    remaining = await conn.fetchval("SELECT COUNT(*) FROM document_uploads")
    print(f"Remaining: {remaining}")
    await conn.close()

asyncio.run(main())
