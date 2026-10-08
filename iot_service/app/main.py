import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

if sys.platform == "win32":
    # Required on Windows for async psycopg connection pool
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.commands import command_dispatcher
from app.config import settings
from app.db import db_manager
from app.gateway.actions import action_service
from app.gateway.lifecycle import IncidentLifecycleManager
from app.gateway.router import router as gateway_router
from app.ingest import MqttIngestService
from app.monitor import ThresholdMonitor
from app.routers import tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")

action_service.db = db_manager
command_dispatcher.db = db_manager
lifecycle_manager = IncidentLifecycleManager(db=db_manager, action_service=action_service)
ingest_service = MqttIngestService(
    db=db_manager,
    lifecycle_manager=lifecycle_manager,
    command_dispatcher=command_dispatcher,
)
threshold_monitor = ThresholdMonitor(
    db_manager=db_manager,
    lifecycle_manager=lifecycle_manager,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing DENSO IoT Service...")
    # 1. Connect Database
    await db_manager.connect()

    # 2. Start Services
    await lifecycle_manager.start()
    await ingest_service.start()
    await threshold_monitor.start()

    logger.info("DENSO IoT Service fully operational.")
    try:
        yield
    finally:
        logger.info("Shutting down DENSO IoT Service...")
        await threshold_monitor.stop()
        await ingest_service.stop()
        await lifecycle_manager.stop()
        await db_manager.close()
        logger.info("DENSO IoT Service shutdown complete.")


app = FastAPI(
    title="DENSO Compressor Test Bench IoT & Agent Service",
    description="IoT telemetry ingestion, threshold monitoring, and Agent Tool APIs",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tools.router)
app.include_router(gateway_router)


@app.get("/health", tags=["Health"])
@app.get("/api/v1/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "service": "denso-iot-service",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "database": "connected" if db_manager.is_connected else "in_memory_fallback",
        "mqtt": "connected" if ingest_service.is_connected else "connecting",
    }


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "DENSO Compressor Test Bench IoT Service",
        "docs": "/docs",
        "health": "/health",
    }


def start_server():
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.GATEWAY_PORT,
        reload=False,
    )


if __name__ == "__main__":
    start_server()
