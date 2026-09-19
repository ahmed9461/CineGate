from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(
        title="CineGate",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
