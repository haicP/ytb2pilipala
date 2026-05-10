from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.repositories import TaskRepository
from backend.app.runner.download import DownloadRunner, run_download_task
from backend.app.schemas import (
    SubscriptionChannelCreateRequest,
    SubscriptionChannelListResponse,
    SubscriptionChannelResponse,
    SubscriptionVideoListResponse,
    SubscriptionVideoResponse,
)
from backend.app.subscriptions import SubscriptionRepository, SubscriptionService


router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _get_channel_or_404(repo: SubscriptionRepository, channel_id: int):
    channel = repo.get_channel(channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription channel not found")
    return channel


def _get_video_or_404(repo: SubscriptionRepository, video_id: int):
    video = repo.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription video not found")
    return video


@router.get("/channels", response_model=SubscriptionChannelListResponse)
def list_channels(
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> SubscriptionChannelListResponse:
    repo = SubscriptionRepository(db)
    channels = repo.list_channels(keyword=keyword)
    return SubscriptionChannelListResponse(
        items=[SubscriptionChannelResponse.from_model(channel) for channel in channels]
    )


@router.post("/channels", response_model=SubscriptionChannelResponse, status_code=status.HTTP_201_CREATED)
def create_channel(
    payload: SubscriptionChannelCreateRequest,
    db: Session = Depends(get_db_session),
) -> SubscriptionChannelResponse:
    repo = SubscriptionRepository(db)
    try:
        channel = SubscriptionService(repo).subscribe_channel(payload.input)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return SubscriptionChannelResponse.from_model(channel)


@router.post("/channels/sync", response_model=SubscriptionChannelListResponse)
def sync_channels(db: Session = Depends(get_db_session)) -> SubscriptionChannelListResponse:
    repo = SubscriptionRepository(db)
    channels = SubscriptionService(repo).sync_all()
    return SubscriptionChannelListResponse(
        items=[SubscriptionChannelResponse.from_model(channel) for channel in channels]
    )


@router.post("/channels/{channel_id}/sync", response_model=SubscriptionChannelResponse)
def sync_channel(channel_id: int, db: Session = Depends(get_db_session)) -> SubscriptionChannelResponse:
    repo = SubscriptionRepository(db)
    channel = _get_channel_or_404(repo, channel_id)
    synced = SubscriptionService(repo).sync_channel(channel)
    return SubscriptionChannelResponse.from_model(synced)


@router.get("/videos", response_model=SubscriptionVideoListResponse)
def list_videos(
    status_filter: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> SubscriptionVideoListResponse:
    repo = SubscriptionRepository(db)
    videos = repo.list_videos(status_filter=status_filter, keyword=keyword)
    return SubscriptionVideoListResponse(items=[SubscriptionVideoResponse.from_model(video) for video in videos])


@router.post("/videos/{video_id}/create-task", response_model=SubscriptionVideoResponse)
def create_task_for_video(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
) -> SubscriptionVideoResponse:
    repo = SubscriptionRepository(db)
    _get_video_or_404(repo, video_id)
    video, created = repo.create_task_for_video(video_id)
    if created and video.task_id is not None:
        DownloadRunner(TaskRepository(db)).start(video.task_id)
        background_tasks.add_task(run_download_task, video.task_id)
        video = repo.get_video(video_id)
        if video is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription video not found")
    return SubscriptionVideoResponse.from_model(video)
