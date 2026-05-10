import json
from datetime import datetime
from json import JSONDecodeError
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain import SourceType
from backend.app.models import (
    AccountBinding,
    Artifact,
    SubmissionMetadata,
    SubscriptionChannel,
    SubscriptionVideo,
    Task,
    TaskLog,
    TaskStep,
)

TTS_PROVIDER_MIMO = "mimo_v2_5_tts"
TTS_PROVIDER_OPENAI = "openai"
TTS_PROVIDERS = {TTS_PROVIDER_MIMO, TTS_PROVIDER_OPENAI}


def _loads_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


class TaskCreateRequest(BaseModel):
    source_type: SourceType
    input: str = Field(min_length=1, max_length=2048)
    options: dict[str, Any] = Field(default_factory=dict)


class MetadataUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    copyright_type: int | None = Field(default=None, ge=1, le=2)


class BilibiliUploadRequest(BaseModel):
    account_id: int | None = Field(default=None, ge=1)


class TaskStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    order: int
    label: str
    status: str
    progress: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str
    retry_count: int

    @classmethod
    def from_model(cls, step: TaskStep) -> "TaskStepResponse":
        return cls.model_validate(step)


class ArtifactResponse(BaseModel):
    id: int
    task_id: int
    step_id: int | None
    artifact_type: str
    path: str
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_model(cls, artifact: Artifact) -> "ArtifactResponse":
        return cls(
            id=artifact.id,
            task_id=artifact.task_id,
            step_id=artifact.step_id,
            artifact_type=artifact.artifact_type,
            path=artifact.path,
            metadata=_loads_json_object(artifact.metadata_json),
            created_at=artifact.created_at,
        )


class LogResponse(BaseModel):
    id: int
    task_id: int
    step_id: int | None
    level: str
    message: str
    context: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_model(cls, log: TaskLog) -> "LogResponse":
        return cls(
            id=log.id,
            task_id=log.task_id,
            step_id=log.step_id,
            level=log.level,
            message=log.message,
            context=_loads_json_object(log.context),
            created_at=log.created_at,
        )


class SubmissionMetadataResponse(BaseModel):
    id: int
    task_id: int
    title: str
    description: str
    tags: list[str]
    category: str
    copyright_type: int
    cover_artifact_id: int | None
    visibility: str
    bilibili_video_id: str
    bilibili_aid: str
    bilibili_cid: str
    bilibili_filename: str
    bilibili_cover_url: str
    upload_status: str
    updated_at: datetime

    @classmethod
    def from_model(cls, metadata: SubmissionMetadata) -> "SubmissionMetadataResponse":
        return cls(
            id=metadata.id,
            task_id=metadata.task_id,
            title=metadata.title,
            description=metadata.description,
            tags=_loads_json_list(metadata.tags),
            category=metadata.category,
            copyright_type=metadata.copyright_type,
            cover_artifact_id=metadata.cover_artifact_id,
            visibility=metadata.visibility,
            bilibili_video_id=metadata.bilibili_video_id,
            bilibili_aid=metadata.bilibili_aid,
            bilibili_cid=metadata.bilibili_cid,
            bilibili_filename=metadata.bilibili_filename,
            bilibili_cover_url=metadata.bilibili_cover_url,
            upload_status=metadata.upload_status,
            updated_at=metadata.updated_at,
        )


class TaskResponse(BaseModel):
    id: int
    source_type: str
    input: str
    title: str
    status: str
    current_step: str
    progress: int
    error_summary: str
    created_at: datetime
    updated_at: datetime
    steps: list[TaskStepResponse]
    artifacts: list[ArtifactResponse]
    metadata: SubmissionMetadataResponse | None

    @classmethod
    def from_model(cls, task: Task) -> "TaskResponse":
        steps = sorted(task.steps, key=lambda item: (item.order, item.id))
        artifacts = sorted(task.artifacts, key=lambda item: (item.created_at, item.id))
        metadata = (
            SubmissionMetadataResponse.from_model(task.metadata_record)
            if task.metadata_record is not None
            else None
        )
        return cls(
            id=task.id,
            source_type=task.source_type,
            input=task.input,
            title=task.title,
            status=task.status,
            current_step=task.current_step,
            progress=task.progress,
            error_summary=task.error_summary,
            created_at=task.created_at,
            updated_at=task.updated_at,
            steps=[TaskStepResponse.from_model(step) for step in steps],
            artifacts=[ArtifactResponse.from_model(artifact) for artifact in artifacts],
            metadata=metadata,
        )


class TaskListResponse(BaseModel):
    items: list[TaskResponse]


class LogListResponse(BaseModel):
    items: list[LogResponse]
    total: int
    limit: int
    offset: int


class SubscriptionChannelCreateRequest(BaseModel):
    input: str = Field(min_length=1, max_length=2048)


class SubscriptionChannelResponse(BaseModel):
    id: int
    source_url: str
    channel_id: str
    title: str
    thumbnail_url: str
    status: str
    error_summary: str
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
    video_count: int

    @classmethod
    def from_model(cls, channel: SubscriptionChannel) -> "SubscriptionChannelResponse":
        return cls(
            id=channel.id,
            source_url=channel.source_url,
            channel_id=channel.channel_id,
            title=channel.title,
            thumbnail_url=channel.thumbnail_url,
            status=channel.status,
            error_summary=channel.error_summary,
            last_synced_at=channel.last_synced_at,
            created_at=channel.created_at,
            updated_at=channel.updated_at,
            video_count=len(channel.videos),
        )


class SubscriptionChannelListResponse(BaseModel):
    items: list[SubscriptionChannelResponse]


class SubscriptionVideoResponse(BaseModel):
    id: int
    channel_id: int
    channel_title: str
    video_id: str
    youtube_url: str
    title: str
    published_at: datetime | None
    thumbnail_url: str
    status: str
    task_id: int | None
    discovered_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, video: SubscriptionVideo) -> "SubscriptionVideoResponse":
        return cls(
            id=video.id,
            channel_id=video.channel_id,
            channel_title=video.channel.title if video.channel is not None else "",
            video_id=video.video_id,
            youtube_url=video.youtube_url,
            title=video.title,
            published_at=video.published_at,
            thumbnail_url=video.thumbnail_url,
            status=video.status,
            task_id=video.task_id,
            discovered_at=video.discovered_at,
            updated_at=video.updated_at,
        )


class SubscriptionVideoListResponse(BaseModel):
    items: list[SubscriptionVideoResponse]


class AccountBindingResponse(BaseModel):
    id: int
    platform: str
    platform_user_id: str
    nickname: str
    avatar_url: str
    status: str
    is_primary: bool
    cookie_summary: str
    last_login_at: datetime | None
    error_summary: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, account: AccountBinding) -> "AccountBindingResponse":
        return cls(
            id=account.id,
            platform=account.platform,
            platform_user_id=account.platform_user_id,
            nickname=account.nickname,
            avatar_url=account.avatar_url,
            status=account.status,
            is_primary=bool(account.is_primary),
            cookie_summary=account.cookie_summary,
            last_login_at=account.last_login_at,
            error_summary=account.error_summary,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )


class AccountBindingListResponse(BaseModel):
    items: list[AccountBindingResponse]


class BilibiliQrCodeResponse(BaseModel):
    login_session_id: str
    qrcode_data_url: str
    expires_at: datetime


class BilibiliQrCodePollResponse(BaseModel):
    status: str
    message: str
    account: AccountBindingResponse | None = None


class SettingsPatchRequest(BaseModel):
    default_category: str | None = Field(default=None, max_length=64)
    dry_run_step_delay_ms: int | None = Field(default=None, ge=0, le=10_000)
    assistant_base_url: str | None = Field(default=None, max_length=2000)
    assistant_api_key: str | None = Field(default=None, max_length=2000)
    assistant_model_id: str | None = Field(default=None, max_length=255)
    image_model_id: str | None = Field(default=None, max_length=255)
    tts_provider: str | None = Field(default=None, max_length=32)
    mimo_base_url: str | None = Field(default=None, max_length=2000)
    mimo_api_key: str | None = Field(default=None, max_length=2000)
    mimo_tts_model: str | None = Field(default=None, max_length=255)
    mimo_tts_voice: str | None = Field(default=None, max_length=255)
    mimo_tts_style_prompt: str | None = Field(default=None, max_length=10_000)
    mimo_tts_timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    mimo_tts_concurrency: int | None = Field(default=None, ge=1, le=50)
    tts_concurrency: int | None = Field(default=None, ge=1, le=50)
    openai_tts_base_url: str | None = Field(default=None, max_length=2000)
    openai_tts_api_key: str | None = Field(default=None, max_length=2000)
    openai_tts_model: str | None = Field(default=None, max_length=255)
    openai_tts_voice: str | None = Field(default=None, max_length=255)
    openai_tts_instructions: str | None = Field(default=None, max_length=10_000)
    openai_tts_speed: float | None = Field(default=None, ge=0.25, le=4.0)

    @field_validator("tts_provider")
    @classmethod
    def validate_tts_provider(cls, value: str | None) -> str | None:
        if value is not None and value not in TTS_PROVIDERS:
            raise ValueError("tts_provider must be mimo_v2_5_tts or openai")
        return value


class SettingsResponse(BaseModel):
    dependencies: dict[str, bool]
    config: dict[str, bool]
    settings: dict[str, str]


class AssistantSettingsPatchRequest(BaseModel):
    base_url: str = Field(default="", max_length=2000)
    api_key: str = Field(default="", max_length=2000)
    model_id: str = Field(default="", max_length=255)
    postprocess_prompt: str = Field(min_length=1, max_length=10_000)
    translation_prompt: str = Field(min_length=1, max_length=10_000)
    metadata_prompt: str = Field(min_length=1, max_length=10_000)


class AssistantSettingsResponse(BaseModel):
    base_url: str
    api_key: str
    model_id: str
    postprocess_prompt: str
    translation_prompt: str
    metadata_prompt: str
    defaults: dict[str, str]
    updated_at: datetime | None


class SystemMetricsResponse(BaseModel):
    disk_free_gb: float
    disk_total_gb: float
    cpu_percent: float
    memory_available_gb: float
    memory_total_gb: float
