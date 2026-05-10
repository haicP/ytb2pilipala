from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="未命名视频任务")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    current_step: Mapped[str] = mapped_column(String(64), nullable=False, default="import")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    steps: Mapped[list["TaskStep"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by=lambda: TaskStep.order,
    )
    logs: Mapped[list["TaskLog"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    metadata_record: Mapped["SubmissionMetadata"] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        uselist=False,
    )
    subscription_videos: Mapped[list["SubscriptionVideo"]] = relationship(back_populates="task")


class TaskStep(Base):
    __tablename__ = "task_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    task: Mapped[Task] = relationship(back_populates="steps")
    logs: Mapped[list["TaskLog"]] = relationship(back_populates="step")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="step")


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("task_steps.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="logs")
    step: Mapped[TaskStep | None] = relationship(back_populates="logs")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("task_steps.id"), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="artifacts")
    step: Mapped[TaskStep | None] = relationship(back_populates="artifacts")


class SubmissionMetadata(Base):
    __tablename__ = "submission_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="科技")
    copyright_type: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    cover_artifact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="public")
    bilibili_video_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    bilibili_aid: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    bilibili_cid: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    bilibili_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    bilibili_cover_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    upload_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="metadata_record")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AccountBinding(Base):
    __tablename__ = "account_bindings"
    __table_args__ = (UniqueConstraint("platform", "platform_user_id", name="uq_account_platform_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    nickname: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    avatar_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_primary: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cookie_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cookies_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SubscriptionChannel(Base):
    __tablename__ = "subscription_channels"
    __table_args__ = (UniqueConstraint("channel_id", name="uq_subscription_channels_channel_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    error_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    videos: Mapped[list["SubscriptionVideo"]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
        order_by=lambda: SubscriptionVideo.discovered_at.desc(),
    )


class SubscriptionVideo(Base):
    __tablename__ = "subscription_videos"
    __table_args__ = (UniqueConstraint("video_id", name="uq_subscription_videos_video_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("subscription_channels.id"), nullable=False)
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    youtube_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="discovered")
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    channel: Mapped[SubscriptionChannel] = relationship(back_populates="videos")
    task: Mapped[Task | None] = relationship(back_populates="subscription_videos")
