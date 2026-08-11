import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import ApiError, init_state, router
from app.config import Settings

logger = logging.getLogger("llmbench")

_ALLOWED_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="LLM Bench")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_ALLOWED_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "context": exc.context},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        origin = request.headers.get("origin")
        allow_origin = origin if origin in _ALLOWED_ORIGINS else _ALLOWED_ORIGINS[0]
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"{type(exc).__name__}: {exc}",
                "context": {"type": type(exc).__name__},
            },
            headers={"Access-Control-Allow-Origin": allow_origin},
        )

    init_state(settings)
    app.include_router(router)
    return app


app = create_app()
