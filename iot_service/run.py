import asyncio
import logging
import sys
import uvicorn

from app.config import settings

logger = logging.getLogger("app.run")

def setup_event_loop():
    if sys.platform == "win32":
        # Required on Windows for async psycopg connection pool to avoid ProactorEventLoop incompatibility
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        logger.info("Configured WindowsSelectorEventLoopPolicy for async psycopg compatibility")

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    setup_event_loop()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.GATEWAY_PORT,
        loop="none",
        reload=False,
    )

if __name__ == "__main__":
    main()
