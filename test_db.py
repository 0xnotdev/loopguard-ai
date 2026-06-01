import asyncio
from database import get_pool

async def main():
    pool = await get_pool()
    print("Database connected successfully!")

asyncio.run(main())