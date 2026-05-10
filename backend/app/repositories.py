import json
import re
import shutil
from datetime import datetime
from pathlib import Path, PurePath, PureWindowsPath
from urllib.parse import parse_qs, urlparse

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, joinedload

from backend.app.domain import SourceType, TaskStatus, create_initial_steps
from backend.app.models import (
    AppSetting,
    Artifact,
    SubmissionMetadata,
    SubscriptionVideo,
    Task,
    TaskLog,
    TaskStep,
    utc_now,
)


def _youtube_video_id(input_value: str) -> str:
    parsed = urlparse(input_value)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if host.endswith("youtu.be") and path_parts:
        return path_parts[0]

    if "youtube.com" in host or "youtube-nocookie.com" in host:
        query_id = parse_qs(parsed.query).get("v", [""])[0]
        if query_id:
            return query_id
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed"}:
            return path_parts[1]

    return ""


def _local_video_name(input_value: str) -> str:
    path = PureWindowsPath(input_value) if "\\" in input_value else PurePath(input_value)
    return path.stem or path.name


def _task_title_from_input(source_type: SourceType, input_value: str) -> str:
    if source_type == SourceType.YOUTUBE:
        return _youtube_video_id(input_value) or "未命名 YouTube 视频"
    return _local_video_name(input_value) or "未命名本地视频"


class TaskRepository:
    def __init__(self, session: Session):
        self.session = session

    def _build_task_title(self, source_type: SourceType, input_value: str) -> str:
        base_title = _task_title_from_input(source_type, input_value)
        if source_type != SourceType.YOUTUBE:
            return base_title

        pattern = re.compile(rf"^{re.escape(base_title)}(?: #(\d+))?$")
        statement = (
            select(Task.title)
            .where(Task.source_type == source_type.value)
            .where(
                or_(
                    Task.title == base_title,
                    Task.title.startswith(f"{base_title} #"),
                )
            )
        )
        existing_titles = self.session.execute(statement).scalars().all()
        max_index = 0
        for title in existing_titles:
            matched = pattern.fullmatch(title)
            if matched is None:
                continue
            suffix = matched.group(1)
            max_index = max(max_index, int(suffix) if suffix is not None else 1)

        if max_index == 0:
            return base_title
        return f"{base_title} #{max_index + 1}"

    def create_task(self, source_type: SourceType, input_value: str) -> Task:
        task = Task(
            source_type=source_type.value,
            input=input_value,
            title=self._build_task_title(source_type, input_value),
            status=TaskStatus.PENDING.value,
            current_step="import",
            progress=0,
        )
        task.steps = [
            TaskStep(
                name=step.name.value,
                order=step.order,
                label=step.label,
                status=step.status.value,
                progress=0,
            )
            for step in create_initial_steps()
        ]
        task.metadata_record = SubmissionMetadata(
            title="",
            description="",
            tags="[]",
            copyright_type=2 if source_type == SourceType.YOUTUBE else 1,
        )
        self.session.add(task)
        self.session.commit()
        return self.get_task(task.id)  # type: ignore[arg-type, return-value]

    def get_task(self, task_id: int) -> Task | None:
        statement = (
            select(Task)
            .where(Task.id == task_id)
            .options(
                joinedload(Task.steps),
                joinedload(Task.logs),
                joinedload(Task.artifacts),
                joinedload(Task.metadata_record),
            )
        )
        return self.session.execute(statement).unique().scalar_one_or_none()

    def list_tasks(
        self,
        status: str | None = None,
        source_type: str | None = None,
        keyword: str | None = None,
    ) -> list[Task]:
        statement = select(Task).options(joinedload(Task.steps)).order_by(Task.created_at.desc())
        if status:
            statement = statement.where(Task.status == status)
        if source_type:
            statement = statement.where(Task.source_type == source_type)
        if keyword:
            statement = statement.where(Task.title.contains(keyword) | Task.input.contains(keyword))
        return list(self.session.execute(statement).unique().scalars())

    def get_app_settings(self, keys: list[str] | tuple[str, ...]) -> dict[str, str]:
        if not keys:
            return {}
        statement = select(AppSetting).where(AppSetting.key.in_(keys))
        rows = self.session.execute(statement).scalars().all()
        return {row.key: row.value for row in rows}

    def update_app_settings(self, updates: dict[str, str]) -> dict[str, str]:
        if not updates:
            return {}

        now = utc_now()
        for key, value in updates.items():
            setting = self.session.get(AppSetting, key)
            if setting is None:
                setting = AppSetting(key=key, value=value, updated_at=now)
                self.session.add(setting)
            else:
                setting.value = value
                setting.updated_at = now
        self.session.commit()
        return self.get_app_settings(tuple(updates.keys()))

    def latest_setting_timestamp(self, keys: list[str] | tuple[str, ...]) -> datetime | None:
        if not keys:
            return None
        statement = select(AppSetting).where(AppSetting.key.in_(keys))
        rows = self.session.execute(statement).scalars().all()
        timestamps = [row.updated_at for row in rows if row.updated_at is not None]
        return max(timestamps) if timestamps else None

    def append_log(self, task_id: int, step_id: int | None, level: str, message: str) -> TaskLog:
        log = TaskLog(task_id=task_id, step_id=step_id, level=level, message=message, context="{}")
        self.session.add(log)
        self.session.commit()
        log_id = log.id
        self.session.expunge(log)
        statement = (
            select(TaskLog)
            .where(TaskLog.id == log_id)
            .options(joinedload(TaskLog.task), joinedload(TaskLog.step))
            .execution_options(populate_existing=True)
        )
        loaded_log = self.session.execute(statement).unique().scalar_one_or_none()
        if loaded_log is None:
            raise ValueError("Log not found after insert")
        loaded_log.task
        loaded_log.step
        return loaded_log

    def add_artifact(
        self,
        task_id: int,
        step_id: int | None,
        artifact_type: str,
        path: str,
        metadata: dict[str, object] | None = None,
    ) -> Artifact:
        artifact = Artifact(
            task_id=task_id,
            step_id=step_id,
            artifact_type=artifact_type,
            path=path,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        )
        self.session.add(artifact)
        self.session.commit()
        artifact_id = artifact.id
        self.session.expunge(artifact)
        statement = (
            select(Artifact)
            .where(Artifact.id == artifact_id)
            .options(joinedload(Artifact.task), joinedload(Artifact.step))
            .execution_options(populate_existing=True)
        )
        loaded_artifact = self.session.execute(statement).unique().scalar_one_or_none()
        if loaded_artifact is None:
            raise ValueError("Artifact not found after insert")
        loaded_artifact.task
        loaded_artifact.step
        return loaded_artifact

    def update_task_status(
        self,
        task: Task,
        status: TaskStatus,
        current_step: str | None = None,
        progress: int | None = None,
        error_summary: str = "",
    ) -> Task:
        task.status = status.value
        if current_step is not None:
            task.current_step = current_step
        if progress is not None:
            task.progress = progress
        task.error_summary = error_summary
        task.updated_at = utc_now()
        self.session.commit()
        loaded_task = self.get_task(task.id)
        if loaded_task is None:
            raise ValueError(f"Task {task.id} not found")
        return loaded_task

    def update_step_status(
        self,
        step: TaskStep,
        status: TaskStatus,
        progress: int,
        error_message: str = "",
    ) -> TaskStep:
        step.status = status.value
        step.progress = progress
        step.error_message = error_message
        if status == TaskStatus.RUNNING and step.started_at is None:
            step.started_at = utc_now()
            step.finished_at = None
        if status in {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}:
            step.finished_at = utc_now()
        self.session.commit()
        statement = (
            select(TaskStep)
            .where(TaskStep.id == step.id)
            .options(joinedload(TaskStep.task), joinedload(TaskStep.logs), joinedload(TaskStep.artifacts))
        )
        loaded_step = self.session.execute(statement).unique().scalar_one_or_none()
        if loaded_step is None:
            raise ValueError(f"Step {step.id} not found")
        return loaded_step

    def reset_steps_from(self, task: Task, start_order: int, retried_step_name: str | None = None) -> Task:
        affected_steps = [step for step in task.steps if step.order >= start_order]
        if not affected_steps:
            return task

        affected_step_ids = [step.id for step in affected_steps]
        self.session.execute(delete(Artifact).where(Artifact.step_id.in_(affected_step_ids)))

        for step in affected_steps:
            step.status = TaskStatus.PENDING.value
            step.progress = 0
            step.error_message = ""
            step.started_at = None
            step.finished_at = None
            if retried_step_name is not None and step.name == retried_step_name:
                step.retry_count += 1

        task.status = TaskStatus.PENDING.value
        task.current_step = min(affected_steps, key=lambda item: item.order).name
        task.progress = 0
        task.error_summary = ""
        task.updated_at = utc_now()
        self.session.commit()

        loaded_task = self.get_task(task.id)
        if loaded_task is None:
            raise ValueError(f"Task {task.id} not found")
        return loaded_task

    def update_metadata(
        self,
        task_id: int,
        title: str,
        description: str,
        tags: list[str],
        category: str,
        copyright_type: int | None = None,
    ) -> SubmissionMetadata:
        task = self.get_task(task_id)
        if task is None or task.metadata_record is None:
            raise ValueError(f"Task {task_id} not found")
        metadata = task.metadata_record
        metadata.title = title
        metadata.description = description
        metadata.tags = json.dumps(tags, ensure_ascii=False)
        metadata.category = category
        if copyright_type is not None:
            metadata.copyright_type = copyright_type
        metadata.updated_at = utc_now()
        self.session.commit()
        statement = (
            select(SubmissionMetadata)
            .where(SubmissionMetadata.id == metadata.id)
            .options(joinedload(SubmissionMetadata.task))
        )
        loaded_metadata = self.session.execute(statement).unique().scalar_one_or_none()
        if loaded_metadata is None:
            raise ValueError(f"Metadata for task {task_id} not found")
        return loaded_metadata

    def update_metadata_cover(self, task_id: int, cover_artifact_id: int) -> SubmissionMetadata:
        task = self.get_task(task_id)
        if task is None or task.metadata_record is None:
            raise ValueError(f"Task {task_id} not found")
        metadata = task.metadata_record
        metadata.cover_artifact_id = cover_artifact_id
        metadata.updated_at = utc_now()
        self.session.commit()
        statement = (
            select(SubmissionMetadata)
            .where(SubmissionMetadata.id == metadata.id)
            .options(joinedload(SubmissionMetadata.task))
        )
        loaded_metadata = self.session.execute(statement).unique().scalar_one_or_none()
        if loaded_metadata is None:
            raise ValueError(f"Metadata for task {task_id} not found")
        return loaded_metadata

    def delete_task(self, task: Task) -> None:
        task_dir = Path("data") / "artifacts" / str(task.id)
        if task_dir.is_dir():
            shutil.rmtree(task_dir)

        linked_videos = list(
            self.session.execute(
                select(SubscriptionVideo).where(SubscriptionVideo.task_id == task.id)
            ).scalars()
        )
        now = utc_now()
        for video in linked_videos:
            video.task_id = None
            video.status = "discovered"
            video.updated_at = now

        try:
            self.session.delete(task)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
