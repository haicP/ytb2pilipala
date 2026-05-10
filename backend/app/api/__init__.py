from fastapi import APIRouter

from backend.app.api.accounts import router as accounts_router
from backend.app.api.assistant import router as assistant_router
from backend.app.api.health import router as health_router
from backend.app.api.settings import router as settings_router
from backend.app.api.subscriptions import router as subscriptions_router
from backend.app.api.system import router as system_router
from backend.app.api.tasks import router as tasks_router
from backend.app.api.videos import router as videos_router


api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(system_router)
api_router.include_router(accounts_router)
api_router.include_router(assistant_router)
api_router.include_router(settings_router)
api_router.include_router(subscriptions_router)
api_router.include_router(tasks_router)
api_router.include_router(videos_router)
