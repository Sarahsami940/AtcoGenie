"""One-shot script to create the AtcoGenie_Checkpoints database if it doesn't exist."""
import asyncio
import selectors

async def create_db():
    from psycopg import AsyncConnection
    try:
        conn = await AsyncConnection.connect(
            "postgresql://postgres:postgres@localhost:5432/postgres",
            autocommit=True,
        )
        await conn.execute('CREATE DATABASE "AtcoGenie_Checkpoints"')
        print("Database AtcoGenie_Checkpoints created successfully")
        await conn.close()
    except Exception as e:
        if "already exists" in str(e):
            print("Database AtcoGenie_Checkpoints already exists")
        else:
            print(f"Failed: {e}")

asyncio.run(create_db(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
