import shutil

import psutil
from fastapi import APIRouter

from backend.app.schemas import SystemMetricsResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/metrics", response_model=SystemMetricsResponse)
def get_system_metrics() -> SystemMetricsResponse:
    disk_usage = shutil.disk_usage(".")
    memory = psutil.virtual_memory()
    gb = 1024**3

    return SystemMetricsResponse(
        disk_free_gb=round(disk_usage.free / gb, 2),
        disk_total_gb=round(disk_usage.total / gb, 2),
        cpu_percent=float(psutil.cpu_percent(interval=None)),
        memory_available_gb=round(memory.available / gb, 2),
        memory_total_gb=round(memory.total / gb, 2),
    )
