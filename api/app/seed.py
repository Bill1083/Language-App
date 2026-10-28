"""Seed the curriculum and scenarios. Run once per container start (after
migrations, before the API starts):  python -m app.seed"""

import asyncio
import logging

from .db import SessionLocal, engine
from .logging_setup import setup_logging
from .services.curriculum import seed_curriculum


async def main() -> None:
    setup_logging()
    async with SessionLocal() as db:
        await seed_curriculum(db)
    await engine.dispose()
    logging.getLogger("parlo.seed").info("curriculum seeded")


if __name__ == "__main__":
    asyncio.run(main())
