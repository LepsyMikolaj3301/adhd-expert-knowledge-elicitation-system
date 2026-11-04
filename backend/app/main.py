from fastapi import APIRouter, FastAPI

from app.assignments.router import router as assignments_router
from app.auth.router import router as auth_router
from app.core.errors import ErrorResponse, install_error_handlers
from app.knowledge.router import router as knowledge_router
from app.reviews.router import router as reviews_router
from app.users.router import router as users_router
from app.vignettes.router import router as vignettes_router

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(
        title="ADHD Expert Knowledge RAG Backend",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    install_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX, responses={"4XX": {"model": ErrorResponse}})

    @api.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in (
        auth_router,
        users_router,
        vignettes_router,
        assignments_router,
        reviews_router,
        knowledge_router,
    ):
        api.include_router(router)
    app.include_router(api)
    return app


app = create_app()
