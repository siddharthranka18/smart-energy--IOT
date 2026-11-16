"""FastAPI application and the command that starts it."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from phase4.api import router
from phase4.config import Settings, load_settings
from phase4.models import Base
from phase4.mqtt_listener import ServiceStatus, TelemetryListener


logger = logging.getLogger("phase4")


def _build_engine(database_url: str) -> Any:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def init_database(engine: Any) -> None:
    Base.metadata.create_all(engine)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = _build_engine(settings.database_url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    status = ServiceStatus()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Step 1: Open the database. The API stays up so /health can explain a failure.
        listener: TelemetryListener | None = None
        try:
            init_database(engine)
            app.state.database_error = None
            logger.info("PostgreSQL tables are ready")
        except SQLAlchemyError as exc:
            app.state.database_error = str(exc)
            logger.error("PostgreSQL is unavailable: %s", exc)

        # Step 2: Listen for the firmware telemetry topic when MQTT is enabled.
        if settings.mqtt_enabled:
            listener = TelemetryListener(settings, session_factory, status)
            listener.start()
        else:
            status.set_mqtt_connected(False, "MQTT listener disabled")

        try:
            yield
        finally:
            if listener is not None:
                listener.stop()
            engine.dispose()

    app = FastAPI(
        title="Smart Energy Phase 4",
        summary="Stores simulated ESP32 telemetry in PostgreSQL and serves the room history.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.status = status
    app.state.database_error = None
    app.include_router(router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "phase4.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
