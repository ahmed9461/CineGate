from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from cinegate.logging import sanitized_request_path
from cinegate.runtime import AppRuntime, build_runtime
from cinegate.web.rewards import build_reward_router

RuntimeFactory = Callable[[], AppRuntime]

logger = logging.getLogger(__name__)


def create_app(runtime_factory: RuntimeFactory = build_runtime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = runtime_factory()
        app.state.runtime = runtime
        await runtime.start()
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(
        title="CineGate",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def structured_request_log(request: Request, call_next):
        request_id = secrets.token_hex(8)
        started = time.perf_counter()
        sanitized_path = sanitized_request_path(request.url.path)

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.error(
                "HTTP request failed",
                extra={
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": sanitized_path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "exception_class": type(exc).__name__,
                },
            )
            raise

        response.headers["X-Request-ID"] = request_id
        if request.url.path not in {"/healthz", "/readyz"}:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "HTTP request completed",
                extra={
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": sanitized_path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        return response

    app.include_router(build_reward_router())

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"])
    async def readyz(request: Request) -> JSONResponse:
        runtime: AppRuntime = request.app.state.runtime
        ready, reason = await runtime.check_ready()
        return JSONResponse(
            {"status": "ready" if ready else "not_ready", "reason": reason},
            status_code=200 if ready else 503,
        )

    @app.post("/telegram/webhook", include_in_schema=False)
    async def telegram_webhook(request: Request) -> Response:
        runtime: AppRuntime = request.app.state.runtime
        expected_secret = runtime.settings.webhook_secret.get_secret_value()
        provided_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token",
            "",
        )
        if not secrets.compare_digest(provided_secret, expected_secret):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="invalid webhook secret",
            )

        try:
            payload = await request.json()
            update = Update.model_validate(payload, context={"bot": runtime.bot})
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid Telegram update",
            ) from exc

        logger.info(
            "Telegram update accepted",
            extra={
                "event": "telegram_update",
                "update_id": update.update_id,
            },
        )
        await runtime.dispatcher.feed_update(runtime.bot, update)
        return Response(status_code=status.HTTP_200_OK)

    return app
