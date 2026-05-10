from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api import api_router
from backend.app.database import init_db


RESERVED_PATH_PREFIXES = ("api", "docs", "openapi.json", "redoc")


def mount_frontend(app: FastAPI) -> None:
    static_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    index_file = static_dir / "index.html"
    if not index_file.exists():
        return

    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str = "") -> FileResponse:
        if path.startswith(RESERVED_PATH_PREFIXES):
            raise HTTPException(status_code=404)
        candidate = static_dir / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_file)


def create_app(init_database: bool = True) -> FastAPI:
    app = FastAPI(title="ytb2pilipala", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    if init_database:
        @app.on_event("startup")
        def on_startup() -> None:
            init_db()

    mount_frontend(app)

    return app


app = create_app()
