from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.cover_generation import CoverGenerationError, OpenAICoverClient, sanitize_cover_error
from backend.app.database import get_db_session
from backend.app.domain import MANUAL_UPLOAD_STEP_NAMES, SourceType, TaskStatus
from backend.app.models import AccountBinding
from backend.app.repositories import TaskRepository
from backend.app.runner.download import DownloadRunner, run_download_task
from backend.app.runner.dry_run import DryRunRunner
from backend.app.runner.manual_upload import run_manual_upload_task
from backend.app.runner.processing import WorkflowRunner
from backend.app.runner.workflow import mark_task_cancelled, next_failed_step_name
from backend.app.schemas import (
    BilibiliUploadRequest,
    LogListResponse,
    LogResponse,
    MetadataUpdateRequest,
    SubmissionMetadataResponse,
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
DOWNLOAD_RETRY_STEPS = {"import", "download_video", "download_thumbnail"}
OPTIONAL_STEP_NAMES = ("download_thumbnail", "transcribe", "translate", "synthesize_voice")
AUTOMATIC_READY_STEPS = {
    "import",
    "download_video",
    "download_thumbnail",
    "extract_audio",
    "transcribe",
    "translate",
    "synthesize_voice",
    "sync_preview",
    "generate_metadata",
}


def _get_task_or_404(repo: TaskRepository, task_id: int):
    task = repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _retry_route_step_name(task, failed_step_name: str | None) -> str | None:
    if failed_step_name is not None:
        return failed_step_name
    for step in sorted(task.steps, key=lambda item: item.order):
        if step.status == TaskStatus.CANCELLED.value:
            return step.name
    return task.current_step


def _get_step_or_404(task, step_id: int):
    for step in task.steps:
        if step.id == step_id:
            return step
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task step not found")


def _ready_for_manual_upload(task) -> bool:
    if task.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
        return False
    automatic_steps = [step for step in task.steps if step.name in AUTOMATIC_READY_STEPS]
    if not automatic_steps:
        return False
    return all(step.status in {TaskStatus.SUCCESS.value, TaskStatus.SKIPPED.value} for step in automatic_steps)


def _has_preview_and_metadata(task) -> bool:
    has_preview = any(artifact.artifact_type == "preview" for artifact in task.artifacts)
    metadata = task.metadata_record
    has_metadata = metadata is not None and bool(metadata.title.strip())
    return has_preview and has_metadata


def _validate_bilibili_upload_account(repo: TaskRepository, account_id: int | None) -> None:
    if account_id is None:
        return

    account = repo.session.get(AccountBinding, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bilibili account binding not found",
        )
    if account.platform != "bilibili":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Selected account is not a Bilibili account",
        )
    if account.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Selected Bilibili account is not active",
        )


def _run_retry_route(repo: TaskRepository, task_id: int, route_step_name: str | None) -> TaskResponse:
    task = _get_task_or_404(repo, task_id)
    if task.source_type == "youtube":
        if route_step_name in DOWNLOAD_RETRY_STEPS:
            DownloadRunner(repo).start(task_id)
            run_download_task(task_id)
        else:
            WorkflowRunner(repo).run_task(task_id)
    else:
        DryRunRunner(repo).run_task(task_id)
    return TaskResponse.from_model(_get_task_or_404(repo, task_id))


def _selected_disabled_steps(options: dict) -> set[str]:
    enabled_steps = options.get("enabled_steps")
    if not isinstance(enabled_steps, dict):
        return set()

    disabled_steps = {
        step_name
        for step_name in OPTIONAL_STEP_NAMES
        if enabled_steps.get(step_name, True) is False
    }
    if "transcribe" in disabled_steps:
        disabled_steps.update(
            {"translate", "synthesize_voice", "sync_preview", "generate_metadata", "upload_subtitle"}
        )
    if "translate" in disabled_steps:
        disabled_steps.update({"synthesize_voice", "sync_preview", "generate_metadata", "upload_subtitle"})
    if "synthesize_voice" in disabled_steps:
        disabled_steps.add("sync_preview")
    return disabled_steps


def _apply_create_options(repo: TaskRepository, task_id: int, options: dict) -> None:
    task = _get_task_or_404(repo, task_id)
    disabled_steps = _selected_disabled_steps(options)
    if not disabled_steps:
        return

    for step in task.steps:
        if step.name in disabled_steps:
            repo.update_step_status(step, TaskStatus.SKIPPED, 100, "由本次提交设置跳过")


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
) -> TaskResponse:
    repo = TaskRepository(db)
    task = repo.create_task(source_type=payload.source_type, input_value=payload.input)
    _apply_create_options(repo, task.id, payload.options)
    if payload.source_type.value == "youtube":
        DownloadRunner(repo).start(task.id)
        background_tasks.add_task(run_download_task, task.id)
    loaded_task = _get_task_or_404(repo, task.id)
    return TaskResponse.from_model(loaded_task)


@router.get("", response_model=TaskListResponse)
def list_tasks(
    status_filter: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> TaskListResponse:
    repo = TaskRepository(db)
    tasks = repo.list_tasks(status=status_filter, source_type=source_type, keyword=keyword)
    return TaskListResponse(items=[TaskResponse.from_model(task) for task in tasks])


@router.get("/{task_id}", response_model=TaskResponse)
def get_task_detail(task_id: int, db: Session = Depends(get_db_session)) -> TaskResponse:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    return TaskResponse.from_model(task)


@router.post("/{task_id}/retry", response_model=TaskResponse)
def retry_task(task_id: int, db: Session = Depends(get_db_session)) -> TaskResponse:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    if task.status not in {TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task in status '{task.status}' cannot be retried",
        )

    failed_step_name = next_failed_step_name(task)
    route_step_name = _retry_route_step_name(task, failed_step_name)
    if task.status == TaskStatus.FAILED.value and failed_step_name is not None:
        retry_step = next(step for step in task.steps if step.name == failed_step_name)
        repo.reset_steps_from(task, retry_step.order, retried_step_name=retry_step.name)
    elif task.status == TaskStatus.CANCELLED.value:
        cancelled_steps = [step for step in task.steps if step.status == TaskStatus.CANCELLED.value]
        if cancelled_steps:
            first_cancelled = min(cancelled_steps, key=lambda item: item.order)
            repo.reset_steps_from(task, first_cancelled.order)

    return _run_retry_route(repo, task_id, route_step_name)


@router.post("/{task_id}/steps/{step_id}/retry", response_model=TaskResponse)
def retry_task_step(task_id: int, step_id: int, db: Session = Depends(get_db_session)) -> TaskResponse:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    if task.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task in status '{task.status}' cannot retry steps while task is running",
        )

    target_step = _get_step_or_404(task, step_id)
    if target_step.name in MANUAL_UPLOAD_STEP_NAMES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manual upload steps must be triggered from preview detail",
        )
    repo.reset_steps_from(task, target_step.order, retried_step_name=target_step.name)
    return _run_retry_route(repo, task_id, target_step.name)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db_session)) -> Response:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    if task.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task in status '{task.status}' cannot be deleted",
        )
    repo.delete_task(task)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{task_id}/bilibili-upload", response_model=TaskResponse)
def run_bilibili_upload(
    task_id: int,
    background_tasks: BackgroundTasks,
    payload: BilibiliUploadRequest | None = None,
    db: Session = Depends(get_db_session),
) -> TaskResponse:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    if not _ready_for_manual_upload(task):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task automatic processing is not ready for manual upload",
        )
    if not _has_preview_and_metadata(task):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task preview video and submission metadata are required before manual upload",
        )

    account_id = payload.account_id if payload is not None else None
    _validate_bilibili_upload_account(repo, account_id)

    has_uploaded_video = bool(task.metadata_record and task.metadata_record.bilibili_video_id)
    first_upload_step_name = "upload_subtitle" if has_uploaded_video else "upload_video"
    if task.metadata_record is not None:
        task.metadata_record.upload_status = "pending"
        repo.session.commit()
    for step in task.steps:
        if step.name in MANUAL_UPLOAD_STEP_NAMES and not (has_uploaded_video and step.name == "upload_video"):
            repo.update_step_status(step, TaskStatus.PENDING, 0, "")
    repo.update_task_status(task, TaskStatus.RUNNING, current_step=first_upload_step_name, progress=task.progress)
    repo.append_log(task.id, None, "info", "B 站后台上传任务已启动")
    background_tasks.add_task(run_manual_upload_task, task_id, account_id)
    return TaskResponse.from_model(_get_task_or_404(repo, task_id))


@router.post("/{task_id}/cover-generation", response_model=TaskResponse)
async def generate_task_cover(
    task_id: int,
    mode: str = Form(...),
    prompt: str = Form(...),
    reference_image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db_session),
) -> TaskResponse:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    if task.metadata_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task metadata not found")
    if mode not in {"text", "image"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="mode must be text or image")

    reference_bytes = None
    reference_filename = None
    if reference_image is not None:
        reference_bytes = await reference_image.read()
        reference_filename = reference_image.filename or "reference.png"
        if not reference_bytes:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reference image is empty")

    try:
        client = OpenAICoverClient(db)
        if mode == "text":
            client.generate_from_text(task, prompt)
        else:
            client.generate_from_image(
                task,
                prompt,
                reference_bytes=reference_bytes,
                reference_filename=reference_filename,
            )
    except CoverGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"封面生成失败：{sanitize_cover_error(exc)}",
        ) from exc

    return TaskResponse.from_model(_get_task_or_404(repo, task_id))


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(task_id: int, db: Session = Depends(get_db_session)) -> TaskResponse:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    if task.status not in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task in status '{task.status}' cannot be cancelled",
        )
    mark_task_cancelled(repo, task)
    return TaskResponse.from_model(_get_task_or_404(repo, task_id))


@router.get("/{task_id}/logs", response_model=LogListResponse)
def get_task_logs(
    task_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db_session),
) -> LogListResponse:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    logs = sorted(task.logs, key=lambda item: (item.created_at, item.id))
    total = len(logs)
    paginated_logs = logs[offset : offset + limit]
    return LogListResponse(
        items=[LogResponse.from_model(log) for log in paginated_logs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{task_id}/metadata", response_model=SubmissionMetadataResponse)
def update_task_metadata(
    task_id: int,
    payload: MetadataUpdateRequest,
    db: Session = Depends(get_db_session),
) -> SubmissionMetadataResponse:
    repo = TaskRepository(db)
    task = _get_task_or_404(repo, task_id)
    metadata = task.metadata_record
    if metadata is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task metadata not found")

    updated = repo.update_metadata(
        task_id=task_id,
        title=payload.title if payload.title is not None else metadata.title,
        description=payload.description if payload.description is not None else metadata.description,
        tags=(
            payload.tags
            if "tags" in payload.model_fields_set
            else SubmissionMetadataResponse.from_model(metadata).tags
        ),
        category=payload.category if payload.category is not None else metadata.category,
        copyright_type=(
            payload.copyright_type if payload.copyright_type is not None else metadata.copyright_type
        ),
    )
    return SubmissionMetadataResponse.from_model(updated)
