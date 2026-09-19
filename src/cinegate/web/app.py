from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import ValidationError

from cinegate.runtime import AppRuntime, build_runtime

RuntimeFactory = Callable[[], AppRuntime]


def create_app(runtime_factory: RuntimeFactory = build_runtime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = runtime_factory()
        app.state.runtime = runtime
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

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

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

        await runtime.dispatcher.feed_update(runtime.bot, update)
        return Response(status_code=status.HTTP_200_OK)

    return app
