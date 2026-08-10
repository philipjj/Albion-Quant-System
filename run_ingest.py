import asyncio
from app.ingestion.collector import MarketCollector

async def run():
    async with MarketCollector() as coll:
        await coll.collect_partition(2, 6)

if __name__ == "__main__":
    asyncio.run(run())
