import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.repositories import TaskRepository
from backend.app.schemas import TaskListResponse, TaskResponse

router = APIRouter(prefix="/videos", tags=["videos"])


def _get_task_or_404(repo: TaskRepository, task_id: int):
    task = repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.get("", response_model=TaskListResponse)
def list_videos(db: Session = Depends(get_db_session)) -> TaskListResponse:
    repo = TaskRepository(db)
    tasks = [
        task
        for task in repo.list_tasks()
        if task.status in {"success", "failed"}
    ]
    return TaskListResponse(items=[TaskResponse.from_model(task) for task in tasks])


@router.get("/{task_id}/artifacts/{artifact_id}", response_class=FileResponse)
def get_video_artifact(
    task_id: int,
    artifact_id: int,
    db: Session = Depends(get_db_session),
) -> FileResponse:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    artifact = next((item for item in task.artifacts if item.id == artifact_id), None)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    artifact_path = Path(artifact.path)
    if not artifact_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact file not found")

    media_type = mimetypes.guess_type(artifact_path.name)[0] or "application/octet-stream"
    return FileResponse(path=artifact_path, media_type=media_type, filename=artifact_path.name)
