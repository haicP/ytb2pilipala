# YouTube Bilibili Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP workbench for creating YouTube/local video processing tasks, running a dry-run workflow, viewing status/logs/artifacts, editing Bilibili submission metadata, and packaging the app for conda and Docker.

**Architecture:** Use a FastAPI backend with SQLite persistence and an in-process dry-run runner. Use a React/Vite frontend that follows the observed `127.0.0.1:8096/dashboard/` layout: fixed sidebar, high-density cards, task overview, submission form, task list, detail view, videos, and settings. External tools are represented through adapter interfaces in MVP, so `yt-dlp`, `ffmpeg`, LLM, and Bilibili upload can replace dry-run implementations without changing API contracts.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, pytest, React 18, TypeScript, Vite, Vitest, Testing Library, lucide-react, Docker, conda.

---

## File Structure

Create this project structure:

```text
backend/
  app/
    __init__.py
    main.py
    config.py
    database.py
    domain.py
    models.py
    repositories.py
    schemas.py
    runner/
      __init__.py
      adapters.py
      dry_run.py
      workflow.py
    api/
      __init__.py
      health.py
      settings.py
      system.py
      tasks.py
      videos.py
  tests/
    conftest.py
    test_health.py
    test_domain.py
    test_repository.py
    test_runner.py
    test_tasks_api.py
frontend/
  index.html
  package.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  src/
    main.tsx
    App.tsx
    api/
      client.ts
      types.ts
    components/
      AppShell.tsx
      Badge.tsx
      Card.tsx
      ProgressBar.tsx
      StepTimeline.tsx
      TaskForm.tsx
    pages/
      DashboardPage.tsx
      TaskListPage.tsx
      TaskDetailPage.tsx
      VideosPage.tsx
      SettingsPage.tsx
    styles.css
  src/__tests__/
    DashboardPage.test.tsx
    TaskDetailPage.test.tsx
Dockerfile
docker-compose.yml
environment.yml
pyproject.toml
.env.example
README.md
```

Responsibility boundaries:
- `backend/app/domain.py`: enums, workflow step names, state transition helpers.
- `backend/app/models.py`: SQLAlchemy ORM rows only.
- `backend/app/repositories.py`: database read/write operations only.
- `backend/app/runner/`: dry-run workflow execution and adapter contracts.
- `backend/app/api/`: request handling and response composition.
- `frontend/src/api/`: API types and fetch wrapper.
- `frontend/src/components/`: reusable UI primitives.
- `frontend/src/pages/`: route-level screens.

---

### Task 1: Backend Baseline And Health API

**Files:**
- Create: `pyproject.toml`
- Create: `environment.yml`
- Create: `.env.example`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/health.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Write the failing health API test**

Create `backend/tests/conftest.py`:

```python
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
```

Create `backend/tests/test_health.py`:

```python
def test_health_returns_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ytb2pilipala"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
rtk pytest backend/tests/test_health.py -q
```

Expected: FAIL because `backend.app.main` does not exist.

- [ ] **Step 3: Add backend package and config files**

Create `pyproject.toml`:

```toml
[project]
name = "ytb2pilipala"
version = "0.1.0"
description = "YouTube to Bilibili dry-run workbench"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.30.0",
  "pydantic>=2.8.0",
  "pydantic-settings>=2.4.0",
  "sqlalchemy>=2.0.32",
  "python-multipart>=0.0.9",
  "psutil>=6.0.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3.0",
  "httpx>=0.27.0",
  "ruff>=0.6.0",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["backend/tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

Create `environment.yml`:

```yaml
name: ytb2pilipala
channels:
  - conda-forge
dependencies:
  - python=3.12
  - pip
  - ffmpeg
  - yt-dlp
  - nodejs=22
  - pip:
      - ".[dev]"
```

Create `.env.example`:

```dotenv
APP_ENV=development
DATABASE_URL=sqlite:///./data/app.db
API2KEY_BASE_URL=
LLM_API_KEY=
BILIBILI_CREDENTIAL_SOURCE=
```

Create `backend/app/__init__.py`:

```python
__all__ = ["create_app"]
```

Create `backend/app/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./data/app.db"
    api2key_base_url: str = ""
    llm_api_key: str = ""
    bilibili_credential_source: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Add FastAPI app and health route**

Create `backend/app/api/__init__.py`:

```python
from fastapi import APIRouter

from backend.app.api.health import router as health_router


api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
```

Create `backend/app/api/health.py`:

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ytb2pilipala"}
```

Create `backend/app/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="ytb2pilipala", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
```

- [ ] **Step 5: Run backend baseline tests**

Run:

```bash
rtk pytest backend/tests/test_health.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add pyproject.toml environment.yml .env.example backend/app backend/tests
rtk git commit -m "feat(backend): 搭建 FastAPI 基线"
```

---

### Task 2: Domain Workflow And State Rules

**Files:**
- Create: `backend/app/domain.py`
- Create: `backend/tests/test_domain.py`

- [ ] **Step 1: Write domain tests**

Create `backend/tests/test_domain.py`:

```python
from backend.app.domain import STEP_DEFINITIONS, StepName, TaskStatus, create_initial_steps


def test_step_definitions_match_required_workflow_order():
    assert [step.name for step in STEP_DEFINITIONS] == [
        StepName.IMPORT,
        StepName.DOWNLOAD_VIDEO,
        StepName.DOWNLOAD_THUMBNAIL,
        StepName.EXTRACT_AUDIO,
        StepName.TRANSCRIBE,
        StepName.TRANSLATE,
        StepName.SYNTHESIZE_VOICE,
        StepName.SYNC_PREVIEW,
        StepName.GENERATE_METADATA,
        StepName.UPLOAD_VIDEO,
        StepName.UPLOAD_SUBTITLE,
    ]


def test_create_initial_steps_marks_only_import_ready():
    steps = create_initial_steps()

    assert steps[0].status == TaskStatus.PENDING
    assert all(step.status == TaskStatus.PENDING for step in steps)
    assert [step.order for step in steps] == list(range(1, 12))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
rtk pytest backend/tests/test_domain.py -q
```

Expected: FAIL because `backend.app.domain` does not exist.

- [ ] **Step 3: Implement domain definitions**

Create `backend/app/domain.py`:

```python
from dataclasses import dataclass
from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class SourceType(StrEnum):
    YOUTUBE = "youtube"
    LOCAL = "local"


class StepName(StrEnum):
    IMPORT = "import"
    DOWNLOAD_VIDEO = "download_video"
    DOWNLOAD_THUMBNAIL = "download_thumbnail"
    EXTRACT_AUDIO = "extract_audio"
    TRANSCRIBE = "transcribe"
    TRANSLATE = "translate"
    SYNTHESIZE_VOICE = "synthesize_voice"
    SYNC_PREVIEW = "sync_preview"
    GENERATE_METADATA = "generate_metadata"
    UPLOAD_VIDEO = "upload_video"
    UPLOAD_SUBTITLE = "upload_subtitle"


@dataclass(frozen=True)
class StepDefinition:
    name: StepName
    order: int
    label: str


@dataclass(frozen=True)
class InitialStep:
    name: StepName
    order: int
    label: str
    status: TaskStatus


STEP_DEFINITIONS: tuple[StepDefinition, ...] = (
    StepDefinition(StepName.IMPORT, 1, "导入任务"),
    StepDefinition(StepName.DOWNLOAD_VIDEO, 2, "下载视频"),
    StepDefinition(StepName.DOWNLOAD_THUMBNAIL, 3, "下载缩略图"),
    StepDefinition(StepName.EXTRACT_AUDIO, 4, "提取音频"),
    StepDefinition(StepName.TRANSCRIBE, 5, "生成字幕"),
    StepDefinition(StepName.TRANSLATE, 6, "翻译字幕"),
    StepDefinition(StepName.SYNTHESIZE_VOICE, 7, "合成配音"),
    StepDefinition(StepName.SYNC_PREVIEW, 8, "同步预览"),
    StepDefinition(StepName.GENERATE_METADATA, 9, "生成投稿信息"),
    StepDefinition(StepName.UPLOAD_VIDEO, 10, "上传视频"),
    StepDefinition(StepName.UPLOAD_SUBTITLE, 11, "上传字幕"),
)


def create_initial_steps() -> list[InitialStep]:
    return [
        InitialStep(
            name=definition.name,
            order=definition.order,
            label=definition.label,
            status=TaskStatus.PENDING,
        )
        for definition in STEP_DEFINITIONS
    ]
```

- [ ] **Step 4: Run domain tests**

Run:

```bash
rtk pytest backend/tests/test_domain.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/app/domain.py backend/tests/test_domain.py
rtk git commit -m "feat(backend): 定义任务工作流状态"
```

---

### Task 3: SQLite Models And Repository

**Files:**
- Create: `backend/app/database.py`
- Create: `backend/app/models.py`
- Create: `backend/app/repositories.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_repository.py`

- [ ] **Step 1: Write repository tests**

Create `backend/tests/test_repository.py`:

```python
from backend.app.domain import SourceType, TaskStatus
from backend.app.repositories import TaskRepository


def test_create_task_builds_steps_and_metadata(db_session):
    repo = TaskRepository(db_session)

    task = repo.create_task(source_type=SourceType.YOUTUBE, input_value="https://youtu.be/demo")

    assert task.id is not None
    assert task.status == TaskStatus.PENDING
    assert task.progress == 0
    assert len(task.steps) == 11
    assert task.metadata_record is not None
    assert task.steps[0].name == "import"


def test_append_log_and_artifact(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(source_type=SourceType.LOCAL, input_value="/videos/demo.mp4")
    first_step = task.steps[0]

    repo.append_log(task_id=task.id, step_id=first_step.id, level="info", message="导入完成")
    repo.add_artifact(task_id=task.id, step_id=first_step.id, artifact_type="video", path="/mock/video.mp4")
    loaded = repo.get_task(task.id)

    assert loaded is not None
    assert loaded.logs[0].message == "导入完成"
    assert loaded.artifacts[0].artifact_type == "video"
```

- [ ] **Step 2: Modify test fixtures**

Replace `backend/tests/conftest.py` with:

```python
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import Base, get_db_session
from backend.app.main import create_app


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db_session() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    with TestClient(app) as test_client:
        yield test_client
```

- [ ] **Step 3: Run repository tests to verify they fail**

Run:

```bash
rtk pytest backend/tests/test_repository.py -q
```

Expected: FAIL because database models and repository do not exist.

- [ ] **Step 4: Implement database and models**

Create `backend/app/database.py`:

```python
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings


class Base(DeclarativeBase):
    pass


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if database_url.startswith("sqlite:///./"):
        return Path(database_url.removeprefix("sqlite:///"))
    if database_url.startswith("sqlite:////"):
        return Path(database_url.removeprefix("sqlite:///"))
    return None


settings = get_settings()
sqlite_path = _sqlite_path_from_url(settings.database_url)
if sqlite_path is not None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

Create `backend/app/models.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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

    steps: Mapped[list["TaskStep"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    logs: Mapped[list["TaskLog"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    metadata_record: Mapped["SubmissionMetadata"] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        uselist=False,
    )


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
    cover_artifact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="public")
    bilibili_video_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    upload_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="metadata_record")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
```

- [ ] **Step 5: Implement repository**

Create `backend/app/repositories.py`:

```python
import json

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.domain import SourceType, TaskStatus, create_initial_steps
from backend.app.models import Artifact, SubmissionMetadata, Task, TaskLog, TaskStep, utc_now


class TaskRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_task(self, source_type: SourceType, input_value: str) -> Task:
        task = Task(
            source_type=source_type.value,
            input=input_value,
            title="未命名视频任务",
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
        task.metadata_record = SubmissionMetadata(title="", description="", tags="[]")
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

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

    def list_tasks(self, status: str | None = None, keyword: str | None = None) -> list[Task]:
        statement = select(Task).options(joinedload(Task.steps)).order_by(Task.created_at.desc())
        if status:
            statement = statement.where(Task.status == status)
        if keyword:
            statement = statement.where(Task.title.contains(keyword) | Task.input.contains(keyword))
        return list(self.session.execute(statement).unique().scalars())

    def append_log(self, task_id: int, step_id: int | None, level: str, message: str) -> TaskLog:
        log = TaskLog(task_id=task_id, step_id=step_id, level=level, message=message, context="{}")
        self.session.add(log)
        self.session.commit()
        self.session.refresh(log)
        return log

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
        self.session.refresh(artifact)
        return artifact

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
        self.session.refresh(task)
        return task

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
        if status == TaskStatus.RUNNING:
            step.started_at = utc_now()
        if status in {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}:
            step.finished_at = utc_now()
        self.session.commit()
        self.session.refresh(step)
        return step

    def update_metadata(
        self,
        task_id: int,
        title: str,
        description: str,
        tags: list[str],
        category: str,
    ) -> SubmissionMetadata:
        task = self.get_task(task_id)
        if task is None or task.metadata_record is None:
            raise ValueError(f"Task {task_id} not found")
        metadata = task.metadata_record
        metadata.title = title
        metadata.description = description
        metadata.tags = json.dumps(tags, ensure_ascii=False)
        metadata.category = category
        metadata.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(metadata)
        return metadata
```

- [ ] **Step 6: Run repository tests**

Run:

```bash
rtk pytest backend/tests/test_repository.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add backend/app/database.py backend/app/models.py backend/app/repositories.py backend/tests/conftest.py backend/tests/test_repository.py
rtk git commit -m "feat(backend): 持久化任务数据模型"
```

---

### Task 4: Dry-run Runner And Adapter Contracts

**Files:**
- Create: `backend/app/runner/__init__.py`
- Create: `backend/app/runner/adapters.py`
- Create: `backend/app/runner/workflow.py`
- Create: `backend/app/runner/dry_run.py`
- Create: `backend/tests/test_runner.py`

- [ ] **Step 1: Write runner tests**

Create `backend/tests/test_runner.py`:

```python
from backend.app.domain import SourceType, TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner.dry_run import DryRunRunner


def test_dry_run_runner_completes_task(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    runner = DryRunRunner(repo)

    runner.run_task(task.id)
    loaded = repo.get_task(task.id)

    assert loaded is not None
    assert loaded.status == TaskStatus.SUCCESS
    assert loaded.progress == 100
    assert all(step.status == TaskStatus.SUCCESS for step in loaded.steps)
    assert len(loaded.logs) >= 11
    assert len(loaded.artifacts) >= 5
    assert loaded.metadata_record.title == "【中文配音】未命名视频任务"
```

- [ ] **Step 2: Run runner test to verify it fails**

Run:

```bash
rtk pytest backend/tests/test_runner.py -q
```

Expected: FAIL because runner files do not exist.

- [ ] **Step 3: Add adapter contracts**

Create `backend/app/runner/__init__.py`:

```python
from backend.app.runner.dry_run import DryRunRunner

__all__ = ["DryRunRunner"]
```

Create `backend/app/runner/adapters.py`:

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class AdapterResult:
    success: bool
    message: str
    artifacts: list[tuple[str, str]] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


class WorkflowAdapter(Protocol):
    def execute(self, task_id: int, step_name: str) -> AdapterResult:
        raise NotImplementedError


class DryRunAdapter:
    def execute(self, task_id: int, step_name: str) -> AdapterResult:
        artifact_map = {
            "download_video": [("video", f"artifacts/{task_id}/source.mp4")],
            "download_thumbnail": [("thumbnail", f"artifacts/{task_id}/thumbnail.jpg")],
            "extract_audio": [("audio", f"artifacts/{task_id}/audio.wav")],
            "transcribe": [("subtitle_source", f"artifacts/{task_id}/source.srt")],
            "translate": [("subtitle_translated", f"artifacts/{task_id}/zh.srt")],
            "synthesize_voice": [("voiceover", f"artifacts/{task_id}/zh_voice.wav")],
            "sync_preview": [("preview", f"artifacts/{task_id}/preview.mp4")],
        }
        return AdapterResult(
            success=True,
            message=f"dry-run step {step_name} completed",
            artifacts=artifact_map.get(step_name, []),
            metadata={"mode": "dry-run"},
        )
```

- [ ] **Step 4: Implement workflow runner**

Create `backend/app/runner/workflow.py`:

```python
from backend.app.domain import TaskStatus
from backend.app.models import Task
from backend.app.repositories import TaskRepository


def calculate_task_progress(task: Task) -> int:
    if not task.steps:
        return 0
    completed = sum(1 for step in task.steps if step.status == TaskStatus.SUCCESS.value)
    return round(completed / len(task.steps) * 100)


def next_failed_step_name(task: Task) -> str | None:
    failed_steps = sorted(
        [step for step in task.steps if step.status == TaskStatus.FAILED.value],
        key=lambda step: step.order,
    )
    return failed_steps[0].name if failed_steps else None


def mark_task_cancelled(repo: TaskRepository, task: Task) -> None:
    for step in task.steps:
        if step.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
            repo.update_step_status(step, TaskStatus.CANCELLED, step.progress)
    repo.update_task_status(task, TaskStatus.CANCELLED, progress=calculate_task_progress(task))
```

Create `backend/app/runner/dry_run.py`:

```python
import json

from backend.app.domain import TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner.adapters import DryRunAdapter
from backend.app.runner.workflow import calculate_task_progress


class DryRunRunner:
    def __init__(self, repo: TaskRepository, adapter: DryRunAdapter | None = None):
        self.repo = repo
        self.adapter = adapter or DryRunAdapter()

    def run_task(self, task_id: int) -> None:
        task = self.repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        self.repo.update_task_status(task, TaskStatus.RUNNING, current_step=task.current_step, progress=0)

        for step in sorted(task.steps, key=lambda item: item.order):
            if step.status == TaskStatus.SUCCESS.value:
                continue
            self.repo.update_step_status(step, TaskStatus.RUNNING, 10)
            self.repo.append_log(task.id, step.id, "info", f"开始执行：{step.label}")

            result = self.adapter.execute(task.id, step.name)
            if not result.success:
                self.repo.update_step_status(step, TaskStatus.FAILED, 100, result.message)
                self.repo.update_task_status(
                    task,
                    TaskStatus.FAILED,
                    current_step=step.name,
                    progress=calculate_task_progress(task),
                    error_summary=result.message,
                )
                self.repo.append_log(task.id, step.id, "error", result.message)
                return

            for artifact_type, path in result.artifacts:
                self.repo.add_artifact(task.id, step.id, artifact_type, path, result.metadata)

            if step.name == "generate_metadata" and task.metadata_record is not None:
                metadata = task.metadata_record
                metadata.title = f"【中文配音】{task.title}"
                metadata.description = "由 ytb2pilipala dry-run 工作流生成的投稿简介。"
                metadata.tags = json.dumps(["YouTube", "中文配音", "AI翻译"], ensure_ascii=False)
                metadata.category = "科技"
                self.repo.session.commit()

            self.repo.update_step_status(step, TaskStatus.SUCCESS, 100)
            self.repo.append_log(task.id, step.id, "info", f"完成执行：{step.label}")
            self.repo.update_task_status(
                task,
                TaskStatus.RUNNING,
                current_step=step.name,
                progress=calculate_task_progress(task),
            )

        self.repo.update_task_status(task, TaskStatus.SUCCESS, progress=100)
        self.repo.append_log(task.id, None, "info", "dry-run 工作流已完成")
```

- [ ] **Step 5: Run runner tests**

Run:

```bash
rtk pytest backend/tests/test_runner.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/runner backend/tests/test_runner.py
rtk git commit -m "feat(backend): 实现 dry-run 任务执行器"
```

---

### Task 5: Task API, Settings API, System Metrics, And Videos API

**Files:**
- Create: `backend/app/schemas.py`
- Create: `backend/app/api/tasks.py`
- Create: `backend/app/api/settings.py`
- Create: `backend/app/api/system.py`
- Create: `backend/app/api/videos.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_tasks_api.py`

- [ ] **Step 1: Write API tests**

Create `backend/tests/test_tasks_api.py`:

```python
def test_create_task_runs_dry_run_and_returns_detail(client):
    response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/demo"},
    )

    assert response.status_code == 201
    created = response.json()
    assert created["source_type"] == "youtube"
    assert created["status"] == "success"
    assert created["progress"] == 100
    assert len(created["steps"]) == 11
    assert created["metadata"]["title"] == "【中文配音】未命名视频任务"


def test_task_list_and_logs(client):
    create_response = client.post(
        "/api/tasks",
        json={"source_type": "local", "input": "/videos/demo.mp4"},
    )
    task_id = create_response.json()["id"]

    list_response = client.get("/api/tasks")
    logs_response = client.get(f"/api/tasks/{task_id}/logs")

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == task_id
    assert logs_response.status_code == 200
    assert logs_response.json()["items"]


def test_update_metadata(client):
    create_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/demo"},
    )
    task_id = create_response.json()["id"]

    response = client.patch(
        f"/api/tasks/{task_id}/metadata",
        json={
            "title": "新的标题",
            "description": "新的简介",
            "tags": ["AI", "翻译"],
            "category": "科技",
        },
    )

    assert response.status_code == 200
    assert response.json()["title"] == "新的标题"
    assert response.json()["tags"] == ["AI", "翻译"]


def test_patch_settings_saves_non_sensitive_values(client):
    response = client.patch(
        "/api/settings",
        json={"default_category": "科技", "dry_run_step_delay_ms": 0},
    )

    assert response.status_code == 200
    assert response.json()["settings"]["default_category"] == "科技"
    assert response.json()["settings"]["dry_run_step_delay_ms"] == "0"
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
rtk pytest backend/tests/test_tasks_api.py -q
```

Expected: FAIL because task API files do not exist.

- [ ] **Step 3: Add Pydantic schemas**

Create `backend/app/schemas.py`:

```python
import json
from datetime import datetime

from pydantic import BaseModel, Field

from backend.app.domain import SourceType
from backend.app.models import Artifact, SubmissionMetadata, Task, TaskLog, TaskStep


class TaskCreateRequest(BaseModel):
    source_type: SourceType
    input: str = Field(min_length=1, max_length=2048)


class MetadataUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    category: str = Field(min_length=1, max_length=64)


class TaskStepResponse(BaseModel):
    id: int
    name: str
    order: int
    label: str
    status: str
    progress: int
    error_message: str

    @classmethod
    def from_model(cls, step: TaskStep) -> "TaskStepResponse":
        return cls(
            id=step.id,
            name=step.name,
            order=step.order,
            label=step.label,
            status=step.status,
            progress=step.progress,
            error_message=step.error_message,
        )


class ArtifactResponse(BaseModel):
    id: int
    artifact_type: str
    path: str

    @classmethod
    def from_model(cls, artifact: Artifact) -> "ArtifactResponse":
        return cls(id=artifact.id, artifact_type=artifact.artifact_type, path=artifact.path)


class LogResponse(BaseModel):
    id: int
    step_id: int | None
    level: str
    message: str
    created_at: datetime

    @classmethod
    def from_model(cls, log: TaskLog) -> "LogResponse":
        return cls(
            id=log.id,
            step_id=log.step_id,
            level=log.level,
            message=log.message,
            created_at=log.created_at,
        )


class SubmissionMetadataResponse(BaseModel):
    title: str
    description: str
    tags: list[str]
    category: str
    visibility: str
    upload_status: str

    @classmethod
    def from_model(cls, metadata: SubmissionMetadata) -> "SubmissionMetadataResponse":
        return cls(
            title=metadata.title,
            description=metadata.description,
            tags=json.loads(metadata.tags),
            category=metadata.category,
            visibility=metadata.visibility,
            upload_status=metadata.upload_status,
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
    metadata: SubmissionMetadataResponse

    @classmethod
    def from_model(cls, task: Task) -> "TaskResponse":
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
            steps=[TaskStepResponse.from_model(step) for step in sorted(task.steps, key=lambda s: s.order)],
            artifacts=[ArtifactResponse.from_model(artifact) for artifact in task.artifacts],
            metadata=SubmissionMetadataResponse.from_model(task.metadata_record),
        )


class TaskListResponse(BaseModel):
    items: list[TaskResponse]


class LogListResponse(BaseModel):
    items: list[LogResponse]
```

- [ ] **Step 4: Add API routes**

Create `backend/app/api/tasks.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.domain import TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner import DryRunRunner
from backend.app.schemas import (
    LogListResponse,
    LogResponse,
    MetadataUpdateRequest,
    SubmissionMetadataResponse,
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreateRequest, session: Session = Depends(get_db_session)) -> TaskResponse:
    repo = TaskRepository(session)
    task = repo.create_task(payload.source_type, payload.input)
    DryRunRunner(repo).run_task(task.id)
    loaded = repo.get_task(task.id)
    if loaded is None:
        raise HTTPException(status_code=500, detail="Task disappeared after creation")
    return TaskResponse.from_model(loaded)


@router.get("", response_model=TaskListResponse)
def list_tasks(
    status_filter: str | None = None,
    keyword: str | None = None,
    session: Session = Depends(get_db_session),
) -> TaskListResponse:
    repo = TaskRepository(session)
    return TaskListResponse(items=[TaskResponse.from_model(task) for task in repo.list_tasks(status_filter, keyword)])


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, session: Session = Depends(get_db_session)) -> TaskResponse:
    task = TaskRepository(session).get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse.from_model(task)


@router.post("/{task_id}/retry", response_model=TaskResponse)
def retry_task(task_id: int, session: Session = Depends(get_db_session)) -> TaskResponse:
    repo = TaskRepository(session)
    task = repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    repo.update_task_status(task, TaskStatus.RUNNING, progress=task.progress, error_summary="")
    DryRunRunner(repo).run_task(task.id)
    return TaskResponse.from_model(repo.get_task(task.id))


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(task_id: int, session: Session = Depends(get_db_session)) -> TaskResponse:
    repo = TaskRepository(session)
    task = repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    repo.update_task_status(task, TaskStatus.CANCELLED, progress=task.progress)
    return TaskResponse.from_model(repo.get_task(task.id))


@router.get("/{task_id}/logs", response_model=LogListResponse)
def get_logs(task_id: int, session: Session = Depends(get_db_session)) -> LogListResponse:
    task = TaskRepository(session).get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    logs = sorted(task.logs, key=lambda log: log.created_at)
    return LogListResponse(items=[LogResponse.from_model(log) for log in logs])


@router.patch("/{task_id}/metadata", response_model=SubmissionMetadataResponse)
def update_metadata(
    task_id: int,
    payload: MetadataUpdateRequest,
    session: Session = Depends(get_db_session),
) -> SubmissionMetadataResponse:
    metadata = TaskRepository(session).update_metadata(
        task_id,
        payload.title,
        payload.description,
        payload.tags,
        payload.category,
    )
    return SubmissionMetadataResponse.from_model(metadata)
```

Create `backend/app/api/system.py`:

```python
import shutil

import psutil
from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/metrics")
def metrics() -> dict[str, float]:
    disk = shutil.disk_usage(".")
    memory = psutil.virtual_memory()
    return {
        "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
        "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
        "cpu_percent": float(psutil.cpu_percent(interval=0.0)),
        "memory_available_gb": round(memory.available / 1024 / 1024 / 1024, 1),
        "memory_total_gb": round(memory.total / 1024 / 1024 / 1024, 1),
    }
```

Create `backend/app/api/settings.py`:

```python
import shutil

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db_session
from backend.app.models import AppSetting, utc_now

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdateRequest(BaseModel):
    default_category: str | None = Field(default=None, max_length=64)
    dry_run_step_delay_ms: int | None = Field(default=None, ge=0, le=10_000)


@router.get("")
def settings_status(session: Session = Depends(get_db_session)) -> dict[str, object]:
    settings = get_settings()
    saved_settings = {
        row.key: row.value
        for row in session.execute(select(AppSetting)).scalars()
    }
    return {
        "dependencies": {
            "yt_dlp": shutil.which("yt-dlp") is not None,
            "ffmpeg": shutil.which("ffmpeg") is not None,
        },
        "config": {
            "api2key_base_url": bool(settings.api2key_base_url),
            "llm_key": bool(settings.llm_api_key),
            "bilibili_credential_source": bool(settings.bilibili_credential_source),
        },
        "settings": saved_settings,
    }


@router.patch("")
def update_settings(
    payload: SettingsUpdateRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    allowed_values = payload.model_dump(exclude_none=True)
    for key, value in allowed_values.items():
        setting = session.get(AppSetting, key)
        if setting is None:
            setting = AppSetting(key=key, value=str(value))
            session.add(setting)
        else:
            setting.value = str(value)
            setting.updated_at = utc_now()
    session.commit()
    return settings_status(session)
```

Create `backend/app/api/videos.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.repositories import TaskRepository
from backend.app.schemas import TaskListResponse, TaskResponse

router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("", response_model=TaskListResponse)
def videos(session: Session = Depends(get_db_session)) -> TaskListResponse:
    repo = TaskRepository(session)
    completed = [task for task in repo.list_tasks() if task.status in {"success", "failed"}]
    return TaskListResponse(items=[TaskResponse.from_model(task) for task in completed])
```

Replace `backend/app/api/__init__.py` with:

```python
from fastapi import APIRouter

from backend.app.api.health import router as health_router
from backend.app.api.settings import router as settings_router
from backend.app.api.system import router as system_router
from backend.app.api.tasks import router as tasks_router
from backend.app.api.videos import router as videos_router


api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(system_router)
api_router.include_router(settings_router)
api_router.include_router(tasks_router)
api_router.include_router(videos_router)
```

Modify `backend/app/main.py` to initialize tables:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import api_router
from backend.app.database import init_db


def create_app() -> FastAPI:
    app = FastAPI(title="ytb2pilipala", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    return app


app = create_app()
```

- [ ] **Step 5: Run API tests**

Run:

```bash
rtk pytest backend/tests/test_tasks_api.py backend/tests/test_health.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/schemas.py backend/app/api backend/app/main.py backend/tests/test_tasks_api.py
rtk git commit -m "feat(api): 提供任务工作台接口"
```

---

### Task 6: Frontend Baseline, API Client, And Shell

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/pages/DashboardPage.tsx`
- Create: `frontend/src/pages/TaskListPage.tsx`
- Create: `frontend/src/pages/TaskDetailPage.tsx`
- Create: `frontend/src/pages/VideosPage.tsx`
- Create: `frontend/src/pages/SettingsPage.tsx`
- Create: `frontend/src/styles.css`

- [ ] **Step 1: Create frontend package files**

Create `frontend/package.json`:

```json
{
  "name": "ytb2pilipala-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc -b && vite build",
    "test": "vitest run --environment jsdom"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^4.3.0",
    "lucide-react": "^0.468.0",
    "vite": "^5.4.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^15.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.6.0",
    "vitest": "^2.0.0"
  }
}
```

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ytb2pilipala</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

Create `frontend/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  }
});
```

- [ ] **Step 2: Add API types and client**

Create `frontend/src/api/types.ts`:

```ts
export type Status = "pending" | "running" | "success" | "failed" | "skipped" | "cancelled";

export type TaskStep = {
  id: number;
  name: string;
  order: number;
  label: string;
  status: Status;
  progress: number;
  error_message: string;
};

export type Artifact = {
  id: number;
  artifact_type: string;
  path: string;
};

export type SubmissionMetadata = {
  title: string;
  description: string;
  tags: string[];
  category: string;
  visibility: string;
  upload_status: string;
};

export type Task = {
  id: number;
  source_type: "youtube" | "local";
  input: string;
  title: string;
  status: Status;
  current_step: string;
  progress: number;
  error_summary: string;
  created_at: string;
  updated_at: string;
  steps: TaskStep[];
  artifacts: Artifact[];
  metadata: SubmissionMetadata;
};

export type LogItem = {
  id: number;
  step_id: number | null;
  level: string;
  message: string;
  created_at: string;
};

export type SystemMetrics = {
  disk_free_gb: number;
  disk_total_gb: number;
  cpu_percent: number;
  memory_available_gb: number;
  memory_total_gb: number;
};
```

Create `frontend/src/api/client.ts`:

```ts
import type { LogItem, SubmissionMetadata, SystemMetrics, Task } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  metrics: () => request<SystemMetrics>("/api/system/metrics"),
  settings: () => request<Record<string, unknown>>("/api/settings"),
  tasks: () => request<{ items: Task[] }>("/api/tasks"),
  videos: () => request<{ items: Task[] }>("/api/videos"),
  task: (id: number) => request<Task>(`/api/tasks/${id}`),
  logs: (id: number) => request<{ items: LogItem[] }>(`/api/tasks/${id}/logs`),
  createTask: (payload: { source_type: "youtube" | "local"; input: string }) =>
    request<Task>("/api/tasks", { method: "POST", body: JSON.stringify(payload) }),
  updateMetadata: (id: number, metadata: Pick<SubmissionMetadata, "title" | "description" | "tags" | "category">) =>
    request<SubmissionMetadata>(`/api/tasks/${id}/metadata`, {
      method: "PATCH",
      body: JSON.stringify(metadata)
    })
};
```

- [ ] **Step 3: Add app shell and global styles**

Create `frontend/src/components/AppShell.tsx`:

```tsx
import { Bot, Home, ListVideo, Settings, UploadCloud, Video } from "lucide-react";
import type { ReactNode } from "react";

type NavItem = {
  href: string;
  label: string;
  icon: ReactNode;
};

const navItems: NavItem[] = [
  { href: "#/dashboard", label: "首页", icon: <Home size={18} /> },
  { href: "#/assistant", label: "AI 助手", icon: <Bot size={18} /> },
  { href: "#/videos", label: "视频列表", icon: <Video size={18} /> },
  { href: "#/tasks", label: "任务队列", icon: <ListVideo size={18} /> },
  { href: "#/settings", label: "系统设置", icon: <Settings size={18} /> }
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#/dashboard">
          <UploadCloud size={20} />
          <span>ytb2pilipala</span>
        </a>
        <nav className="nav-list">
          {navItems.map((item) => (
            <a key={item.href} href={item.href} className="nav-item">
              {item.icon}
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="sidebar-user">
          <span>本地工作台</span>
          <strong>dry-run</strong>
        </div>
      </aside>
      <main className="main-panel">{children}</main>
    </div>
  );
}
```

Create `frontend/src/App.tsx`:

```tsx
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { TaskListPage } from "./pages/TaskListPage";
import { VideosPage } from "./pages/VideosPage";

function currentRoute() {
  return window.location.hash || "#/dashboard";
}

export function App() {
  const route = currentRoute();
  let page = <DashboardPage />;
  if (route.startsWith("#/tasks/")) {
    page = <TaskDetailPage taskId={Number(route.replace("#/tasks/", ""))} />;
  } else if (route === "#/tasks") {
    page = <TaskListPage />;
  } else if (route === "#/videos") {
    page = <VideosPage />;
  } else if (route === "#/settings") {
    page = <SettingsPage />;
  }
  return <AppShell>{page}</AppShell>;
}
```

Create `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

Create `frontend/src/pages/DashboardPage.tsx`:

```tsx
export function DashboardPage() {
  return <h1>工作台加载中</h1>;
}
```

Create `frontend/src/pages/TaskListPage.tsx`:

```tsx
export function TaskListPage() {
  return <h1>任务队列加载中</h1>;
}
```

Create `frontend/src/pages/TaskDetailPage.tsx`:

```tsx
export function TaskDetailPage({ taskId }: { taskId: number }) {
  return <h1>任务详情 #{taskId}</h1>;
}
```

Create `frontend/src/pages/VideosPage.tsx`:

```tsx
export function VideosPage() {
  return <h1>视频列表加载中</h1>;
}
```

Create `frontend/src/pages/SettingsPage.tsx`:

```tsx
export function SettingsPage() {
  return <h1>系统设置加载中</h1>;
}
```

Create `frontend/src/styles.css`:

```css
:root {
  font-family: Inter, "Plus Jakarta Sans", "Noto Sans SC", system-ui, sans-serif;
  color: #0f172a;
  background: #f8fafc;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

a {
  color: inherit;
  text-decoration: none;
}

button,
input,
textarea {
  font: inherit;
}

.app-shell {
  display: grid;
  grid-template-columns: 252px minmax(0, 1fr);
  min-height: 100vh;
}

.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  border-right: 1px solid #e2e8f0;
  background: #ffffff;
  padding: 28px 20px;
}

.brand,
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand {
  font-size: 18px;
  font-weight: 800;
  margin-bottom: 28px;
}

.nav-list {
  display: grid;
  gap: 6px;
}

.nav-item {
  min-height: 40px;
  border-radius: 8px;
  padding: 0 12px;
  color: #475569;
}

.nav-item:hover {
  background: #f1f5f9;
  color: #1d4ed8;
}

.sidebar-user {
  position: absolute;
  left: 20px;
  right: 20px;
  bottom: 24px;
  display: grid;
  gap: 4px;
  color: #64748b;
  font-size: 13px;
}

.main-panel {
  padding: 36px;
}

.section-card {
  border: 1px solid #dbe4f0;
  border-radius: 16px;
  background: #ffffff;
  padding: 24px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.eyebrow {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.grid {
  display: grid;
  gap: 16px;
}

.grid-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.grid-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.grid-4 {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-card {
  min-height: 112px;
  border: 1px solid #dbe4f0;
  border-radius: 12px;
  padding: 20px;
}

.metric-card strong {
  display: block;
  margin-top: 8px;
  font-size: 28px;
}

.button {
  min-height: 44px;
  border: 0;
  border-radius: 10px;
  padding: 0 16px;
  color: #ffffff;
  background: #2563eb;
  cursor: pointer;
}

.button.secondary {
  border: 1px solid #dbe4f0;
  color: #0f172a;
  background: #ffffff;
}

.input,
.textarea {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 0 14px;
  color: #0f172a;
  background: #ffffff;
}

.input {
  min-height: 44px;
}

.textarea {
  min-height: 120px;
  padding-top: 12px;
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th,
.table td {
  border-bottom: 1px solid #e2e8f0;
  padding: 12px;
  text-align: left;
  vertical-align: top;
}

@media (max-width: 900px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: static;
    height: auto;
  }

  .main-panel {
    padding: 20px;
  }

  .grid-2,
  .grid-3,
  .grid-4 {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 4: Run frontend build**

Run:

```bash
rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 5: Commit shell files**

```bash
rtk git add frontend/package.json frontend/index.html frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/src
rtk git commit -m "feat(frontend): 搭建 React 工作台外壳"
```

---

### Task 7: Dashboard, Shared UI Components, And Task Submission

**Files:**
- Create: `frontend/src/components/Card.tsx`
- Create: `frontend/src/components/Badge.tsx`
- Create: `frontend/src/components/ProgressBar.tsx`
- Create: `frontend/src/components/TaskForm.tsx`
- Modify: `frontend/src/pages/DashboardPage.tsx`
- Create: `frontend/src/__tests__/DashboardPage.test.tsx`

- [ ] **Step 1: Write dashboard test**

Create `frontend/src/__tests__/DashboardPage.test.tsx`:

```tsx
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { DashboardPage } from "../pages/DashboardPage";

vi.mock("../api/client", () => ({
  api: {
    metrics: async () => ({
      disk_free_gb: 84.2,
      disk_total_gb: 96,
      cpu_percent: 0.2,
      memory_available_gb: 18.4,
      memory_total_gb: 19.6
    }),
    tasks: async () => ({ items: [] }),
    createTask: async () => ({})
  }
}));

test("dashboard shows primary workbench sections", () => {
  render(<DashboardPage />);

  expect(screen.getByText("系统信息")).toBeInTheDocument();
  expect(screen.getByText("任务概况")).toBeInTheDocument();
  expect(screen.getByText("提交新视频")).toBeInTheDocument();
  expect(screen.getByText("最近处理")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run dashboard test to verify it fails**

Run:

```bash
rtk npm --prefix frontend test -- DashboardPage.test.tsx
```

Expected: FAIL because `DashboardPage` still renders the placeholder from Task 6.

- [ ] **Step 3: Add shared components**

Create `frontend/src/components/Card.tsx`:

```tsx
import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`section-card ${className}`}>{children}</section>;
}
```

Create `frontend/src/components/Badge.tsx`:

```tsx
import type { Status } from "../api/types";

const labels: Record<Status, string> = {
  pending: "等待中",
  running: "处理中",
  success: "已完成",
  failed: "失败",
  skipped: "已跳过",
  cancelled: "已取消"
};

export function Badge({ status }: { status: Status }) {
  return <span className={`status-badge status-${status}`}>{labels[status]}</span>;
}
```

Create `frontend/src/components/ProgressBar.tsx`:

```tsx
export function ProgressBar({ value }: { value: number }) {
  const normalized = Math.max(0, Math.min(100, value));
  return (
    <div className="progress-track" aria-label={`进度 ${normalized}%`}>
      <div className="progress-fill" style={{ width: `${normalized}%` }} />
    </div>
  );
}
```

Create `frontend/src/components/TaskForm.tsx`:

```tsx
import { Settings, Send } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";

export function TaskForm({ onCreated }: { onCreated: () => void }) {
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!input.trim()) {
      return;
    }
    setSubmitting(true);
    const sourceType = input.startsWith("http") ? "youtube" : "local";
    await api.createTask({ source_type: sourceType, input: input.trim() });
    setInput("");
    setSubmitting(false);
    onCreated();
  }

  return (
    <form className="task-form" onSubmit={submit}>
      <input
        className="input"
        value={input}
        onChange={(event) => setInput(event.target.value)}
        placeholder="https://www.youtube.com/watch?v=... / /path/to/local.mp4"
      />
      <button className="button secondary" type="button">
        <Settings size={16} />
        设置
      </button>
      <button className="button" type="submit" disabled={submitting || !input.trim()}>
        <Send size={16} />
        提交
      </button>
    </form>
  );
}
```

- [ ] **Step 4: Add dashboard page**

Create `frontend/src/pages/DashboardPage.tsx`:

```tsx
import { Cpu, Database, HardDrive, MemoryStick, Video } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { SystemMetrics, Task } from "../api/types";
import { Card } from "../components/Card";
import { TaskForm } from "../components/TaskForm";

export function DashboardPage() {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);

  async function load() {
    const [metricData, taskData] = await Promise.all([api.metrics(), api.tasks()]);
    setMetrics(metricData);
    setTasks(taskData.items);
  }

  useEffect(() => {
    void load();
  }, []);

  const completed = tasks.filter((task) => task.status === "success").length;
  const running = tasks.filter((task) => task.status === "running").length;
  const uploaded = tasks.filter((task) => task.metadata.upload_status === "success").length;

  return (
    <div className="grid">
      <Card>
        <div className="eyebrow">System Overview</div>
        <h2>系统信息</h2>
        <p>这里只保留最常看的资源指标：磁盘剩余、CPU 占用、可用内存。</p>
        <div className="grid grid-3">
          <div className="metric-card">
            <HardDrive size={20} />
            <span>磁盘剩余</span>
            <strong>{metrics ? `${metrics.disk_free_gb} GB` : "-"}</strong>
          </div>
          <div className="metric-card">
            <Cpu size={20} />
            <span>CPU 占用</span>
            <strong>{metrics ? `${metrics.cpu_percent}%` : "-"}</strong>
          </div>
          <div className="metric-card">
            <MemoryStick size={20} />
            <span>可用内存</span>
            <strong>{metrics ? `${metrics.memory_available_gb} GB` : "-"}</strong>
          </div>
        </div>
      </Card>

      <Card>
        <div className="eyebrow">Task Overview</div>
        <h2>任务概况</h2>
        <div className="grid grid-4">
          <div className="metric-card"><Video size={20} /><span>视频总数</span><strong>{tasks.length}</strong></div>
          <div className="metric-card"><Database size={20} /><span>已完成</span><strong>{completed}</strong></div>
          <div className="metric-card"><Cpu size={20} /><span>处理中</span><strong>{running}</strong></div>
          <div className="metric-card"><HardDrive size={20} /><span>已上传 B 站</span><strong>{uploaded}</strong></div>
        </div>
      </Card>

      <Card>
        <h1>提交新视频</h1>
        <p>粘贴 YouTube 链接或填写本地视频路径后会加入任务队列，并按 dry-run 流程推进状态。</p>
        <TaskForm onCreated={load} />
        <div className="pill-row">
          <span>下载缩略图</span>
          <span>转录字幕</span>
          <span>AI 翻译字幕</span>
          <span>合成字幕配音</span>
        </div>
      </Card>

      <div className="grid grid-2">
        <Card>
          <h2>最近处理</h2>
          {tasks.length === 0 ? <p>暂无视频，提交第一个链接开始吧。</p> : null}
          {tasks.slice(0, 5).map((task) => (
            <a className="task-row" key={task.id} href={`#/tasks/${task.id}`}>
              <strong>{task.title}</strong>
              <span>{task.status} · {task.progress}%</span>
            </a>
          ))}
        </Card>
        <Card>
          <h2>快捷入口</h2>
          <div className="quick-links">
            <a href="#/tasks">任务队列</a>
            <a href="#/videos">视频库</a>
            <a href="#/settings">系统设置</a>
          </div>
        </Card>
      </div>
    </div>
  );
}
```

Append these styles to `frontend/src/styles.css`:

```css
.status-badge {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  border-radius: 999px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 700;
  background: #e2e8f0;
}

.status-success {
  color: #047857;
  background: #d1fae5;
}

.status-running {
  color: #1d4ed8;
  background: #dbeafe;
}

.status-failed {
  color: #be123c;
  background: #ffe4e6;
}

.progress-track {
  width: 100%;
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: #e2e8f0;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: #2563eb;
}

.task-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 118px 118px;
  gap: 10px;
}

.task-form .button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.pill-row span {
  border: 1px solid #dbe4f0;
  border-radius: 999px;
  padding: 4px 10px;
  color: #64748b;
  font-size: 12px;
}

.task-row,
.quick-links a {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px;
  margin-top: 10px;
}

@media (max-width: 900px) {
  .task-form {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Run dashboard test and build**

Run:

```bash
rtk npm --prefix frontend test -- DashboardPage.test.tsx
rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add frontend/src/components frontend/src/pages/DashboardPage.tsx frontend/src/__tests__/DashboardPage.test.tsx frontend/src/styles.css
rtk git commit -m "feat(frontend): 实现首页工作台"
```

---

### Task 8: Task List, Task Detail, Logs, And Metadata Editing

**Files:**
- Create: `frontend/src/components/StepTimeline.tsx`
- Modify: `frontend/src/pages/TaskListPage.tsx`
- Modify: `frontend/src/pages/TaskDetailPage.tsx`
- Create: `frontend/src/__tests__/TaskDetailPage.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write task detail test**

Create `frontend/src/__tests__/TaskDetailPage.test.tsx`:

```tsx
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { TaskDetailPage } from "../pages/TaskDetailPage";

vi.mock("../api/client", () => ({
  api: {
    task: async () => ({
      id: 1,
      source_type: "youtube",
      input: "https://youtu.be/demo",
      title: "未命名视频任务",
      status: "success",
      current_step: "upload_subtitle",
      progress: 100,
      error_summary: "",
      created_at: "2026-05-01T00:00:00Z",
      updated_at: "2026-05-01T00:00:00Z",
      steps: [],
      artifacts: [],
      metadata: {
        title: "【中文配音】未命名视频任务",
        description: "简介",
        tags: ["AI"],
        category: "科技",
        visibility: "public",
        upload_status: "pending"
      }
    }),
    logs: async () => ({ items: [] }),
    updateMetadata: async () => ({
      title: "【中文配音】未命名视频任务",
      description: "简介",
      tags: ["AI"],
      category: "科技",
      visibility: "public",
      upload_status: "pending"
    })
  }
}));

test("task detail renders loading state before API resolves", () => {
  render(<TaskDetailPage taskId={1} />);

  expect(screen.getByText("任务详情")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run detail test to verify it fails**

Run:

```bash
rtk npm --prefix frontend test -- TaskDetailPage.test.tsx
```

Expected: FAIL because `TaskDetailPage` still renders the placeholder from Task 6.

- [ ] **Step 3: Add step timeline**

Create `frontend/src/components/StepTimeline.tsx`:

```tsx
import type { TaskStep } from "../api/types";
import { Badge } from "./Badge";
import { ProgressBar } from "./ProgressBar";

export function StepTimeline({ steps }: { steps: TaskStep[] }) {
  return (
    <div className="step-timeline">
      {steps.map((step) => (
        <div className="step-item" key={step.id}>
          <div>
            <strong>{step.order}. {step.label}</strong>
            <p>{step.name}</p>
          </div>
          <Badge status={step.status} />
          <ProgressBar value={step.progress} />
          {step.error_message ? <p className="error-text">{step.error_message}</p> : null}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Add task list page**

Create `frontend/src/pages/TaskListPage.tsx`:

```tsx
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Task } from "../api/types";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ProgressBar } from "../components/ProgressBar";

export function TaskListPage() {
  const [tasks, setTasks] = useState<Task[]>([]);

  useEffect(() => {
    void api.tasks().then((data) => setTasks(data.items));
  }, []);

  return (
    <Card>
      <div className="eyebrow">Task Queue</div>
      <h1>任务队列</h1>
      <table className="table">
        <thead>
          <tr>
            <th>标题</th>
            <th>来源</th>
            <th>当前步骤</th>
            <th>进度</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id}>
              <td>{task.title}</td>
              <td>{task.source_type}</td>
              <td>{task.current_step}</td>
              <td><ProgressBar value={task.progress} /></td>
              <td><Badge status={task.status} /></td>
              <td><a className="text-link" href={`#/tasks/${task.id}`}>查看详情</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
```

- [ ] **Step 5: Add task detail page**

Create `frontend/src/pages/TaskDetailPage.tsx`:

```tsx
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { LogItem, Task } from "../api/types";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ProgressBar } from "../components/ProgressBar";
import { StepTimeline } from "../components/StepTimeline";

export function TaskDetailPage({ taskId }: { taskId: number }) {
  const [task, setTask] = useState<Task | null>(null);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [saving, setSaving] = useState(false);

  async function load() {
    const [taskData, logData] = await Promise.all([api.task(taskId), api.logs(taskId)]);
    setTask(taskData);
    setLogs(logData.items);
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [taskId]);

  async function saveMetadata(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!task) {
      return;
    }
    const form = new FormData(event.currentTarget);
    setSaving(true);
    await api.updateMetadata(task.id, {
      title: String(form.get("title")),
      description: String(form.get("description")),
      tags: String(form.get("tags")).split(",").map((tag) => tag.trim()).filter(Boolean),
      category: String(form.get("category"))
    });
    setSaving(false);
    await load();
  }

  return (
    <div className="grid">
      <Card>
        <div className="eyebrow">Task Detail</div>
        <h1>任务详情</h1>
        {task ? (
          <div className="detail-head">
            <div>
              <h2>{task.title}</h2>
              <p>{task.input}</p>
            </div>
            <Badge status={task.status} />
            <ProgressBar value={task.progress} />
          </div>
        ) : <p>加载中</p>}
      </Card>

      {task ? (
        <div className="grid grid-2">
          <Card>
            <h2>处理步骤</h2>
            <StepTimeline steps={task.steps} />
          </Card>
          <Card>
            <h2>投稿信息</h2>
            <form className="metadata-form" onSubmit={saveMetadata}>
              <label>标题<input className="input" name="title" defaultValue={task.metadata.title} /></label>
              <label>简介<textarea className="textarea" name="description" defaultValue={task.metadata.description} /></label>
              <label>标签<input className="input" name="tags" defaultValue={task.metadata.tags.join(", ")} /></label>
              <label>分区<input className="input" name="category" defaultValue={task.metadata.category} /></label>
              <button className="button" type="submit" disabled={saving}>保存投稿信息</button>
            </form>
          </Card>
        </div>
      ) : null}

      {task ? (
        <div className="grid grid-2">
          <Card>
            <h2>产物</h2>
            {task.artifacts.map((artifact) => (
              <div className="artifact-row" key={artifact.id}>
                <strong>{artifact.artifact_type}</strong>
                <span>{artifact.path}</span>
              </div>
            ))}
          </Card>
          <Card>
            <h2>日志</h2>
            <div className="log-list">
              {logs.map((log) => (
                <div key={log.id} className="log-row">
                  <span>{log.level}</span>
                  <p>{log.message}</p>
                </div>
              ))}
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
```

Append to `frontend/src/styles.css`:

```css
.text-link {
  color: #2563eb;
  font-weight: 700;
}

.detail-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: center;
}

.detail-head .progress-track {
  grid-column: 1 / -1;
}

.step-timeline,
.metadata-form,
.log-list {
  display: grid;
  gap: 12px;
}

.step-item,
.artifact-row,
.log-row {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px;
}

.step-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}

.step-item .progress-track {
  grid-column: 1 / -1;
}

.error-text {
  grid-column: 1 / -1;
  color: #be123c;
}

.metadata-form label {
  display: grid;
  gap: 6px;
  color: #475569;
  font-weight: 700;
}

.artifact-row,
.log-row {
  display: grid;
  gap: 4px;
}
```

- [ ] **Step 6: Run task detail test and frontend build**

Run:

```bash
rtk npm --prefix frontend test -- TaskDetailPage.test.tsx
rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add frontend/src/components/StepTimeline.tsx frontend/src/pages/TaskListPage.tsx frontend/src/pages/TaskDetailPage.tsx frontend/src/__tests__/TaskDetailPage.test.tsx frontend/src/styles.css
rtk git commit -m "feat(frontend): 实现任务队列与详情"
```

---

### Task 9: Videos Page, Settings Page, And Final Frontend Build

**Files:**
- Modify: `frontend/src/pages/VideosPage.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add videos page**

Create `frontend/src/pages/VideosPage.tsx`:

```tsx
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Task } from "../api/types";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";

export function VideosPage() {
  const [videos, setVideos] = useState<Task[]>([]);

  useEffect(() => {
    void api.videos().then((data) => setVideos(data.items));
  }, []);

  return (
    <Card>
      <div className="eyebrow">Video Library</div>
      <h1>视频列表</h1>
      <div className="video-grid">
        {videos.map((video) => (
          <a className="video-card" key={video.id} href={`#/tasks/${video.id}`}>
            <strong>{video.metadata.title || video.title}</strong>
            <span>{video.input}</span>
            <Badge status={video.status} />
          </a>
        ))}
      </div>
      {videos.length === 0 ? <p>暂无可投稿视频。</p> : null}
    </Card>
  );
}
```

- [ ] **Step 2: Add settings page**

Create `frontend/src/pages/SettingsPage.tsx`:

```tsx
import { CheckCircle2, CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { Card } from "../components/Card";

type SettingsStatus = {
  dependencies?: Record<string, boolean>;
  config?: Record<string, boolean>;
};

function StatusLine({ label, value }: { label: string; value: boolean }) {
  return (
    <div className="status-line">
      {value ? <CheckCircle2 size={18} /> : <CircleAlert size={18} />}
      <span>{label}</span>
      <strong>{value ? "已配置" : "未配置"}</strong>
    </div>
  );
}

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsStatus>({});

  useEffect(() => {
    void api.settings().then((data) => setSettings(data as SettingsStatus));
  }, []);

  return (
    <div className="grid">
      <Card>
        <div className="eyebrow">System Settings</div>
        <h1>系统设置</h1>
        <p>敏感配置只显示状态，不显示密钥、cookie 或 token 明文。</p>
      </Card>
      <div className="grid grid-2">
        <Card>
          <h2>前置依赖</h2>
          <StatusLine label="yt-dlp" value={Boolean(settings.dependencies?.yt_dlp)} />
          <StatusLine label="ffmpeg" value={Boolean(settings.dependencies?.ffmpeg)} />
        </Card>
        <Card>
          <h2>AI 与账号配置</h2>
          <StatusLine label="api2key.base_url" value={Boolean(settings.config?.api2key_base_url)} />
          <StatusLine label="LLM Key" value={Boolean(settings.config?.llm_key)} />
          <StatusLine label="B 站凭据来源" value={Boolean(settings.config?.bilibili_credential_source)} />
        </Card>
      </div>
    </div>
  );
}
```

Append to `frontend/src/styles.css`:

```css
.video-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}

.video-card {
  display: grid;
  gap: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
}

.video-card span {
  color: #64748b;
  overflow-wrap: anywhere;
}

.status-line {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px;
  margin-top: 10px;
}
```

- [ ] **Step 3: Run frontend tests and build**

Run:

```bash
rtk npm --prefix frontend test
rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add frontend/src/pages/VideosPage.tsx frontend/src/pages/SettingsPage.tsx frontend/src/styles.css
rtk git commit -m "feat(frontend): 实现视频与设置页面"
```

---

### Task 10: Docker, README, Static Frontend Serving, And End-to-End Verification

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `README.md`
- Modify: `backend/app/main.py`
- Modify: `.gitignore`

- [ ] **Step 1: Serve built frontend from FastAPI**

Modify `backend/app/main.py`:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api import api_router
from backend.app.database import init_db


def create_app() -> FastAPI:
    app = FastAPI(title="ytb2pilipala", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    static_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()
```

- [ ] **Step 2: Add Dockerfile**

Create `Dockerfile`:

```dockerfile
FROM node:22-bookworm AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir yt-dlp
COPY pyproject.toml ./
COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN pip install --no-cache-dir ".[dev]"
ENV DATABASE_URL=sqlite:///./data/app.db
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `docker-compose.yml`:

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: sqlite:///./data/app.db
      API2KEY_BASE_URL: ${API2KEY_BASE_URL:-}
      LLM_API_KEY: ${LLM_API_KEY:-}
      BILIBILI_CREDENTIAL_SOURCE: ${BILIBILI_CREDENTIAL_SOURCE:-}
    volumes:
      - ./data:/app/data
```

- [ ] **Step 3: Add README**

Create `README.md`:

```markdown
# ytb2pilipala

YouTube 到 B 站自动处理工作台。MVP 提供 FastAPI + React/Vite 工作台、SQLite 持久化和 dry-run 视频处理流程。

## 本地开发

```bash
conda env create -f environment.yml
conda activate ytb2pilipala
pip install -e ".[dev]"
npm --prefix frontend install
```

启动后端：

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

启动前端：

```bash
npm --prefix frontend run dev
```

打开 `http://127.0.0.1:5173`。

## Docker

```bash
docker compose up --build
```

打开 `http://127.0.0.1:8000`。

## 验证

```bash
pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

## 配置

复制 `.env.example` 为 `.env`，按需设置：

- `API2KEY_BASE_URL`
- `LLM_API_KEY`
- `BILIBILI_CREDENTIAL_SOURCE`

敏感值不提交到仓库。
```

- [ ] **Step 4: Ensure ignore rules cover runtime output**

Confirm `.gitignore` includes:

```gitignore
data/
storage/
artifacts/
frontend/dist/
frontend/node_modules/
```

If any line is missing, append only the missing line.

- [ ] **Step 5: Run full verification**

Run:

```bash
rtk pytest -q
rtk npm --prefix frontend test
rtk npm --prefix frontend run build
rtk docker compose config
```

Expected: all commands PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add Dockerfile docker-compose.yml README.md backend/app/main.py .gitignore
rtk git commit -m "chore(env): 添加 Docker 与运行说明"
```

---

### Task 11: Manual UI Verification In Browser

**Files:**
- Modify only files needed to fix defects found during verification.

- [ ] **Step 1: Start backend**

Run:

```bash
rtk uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Expected: server starts and prints Uvicorn running on `http://127.0.0.1:8000`.

- [ ] **Step 2: Start frontend**

Run in a second terminal:

```bash
rtk npm --prefix frontend run dev
```

Expected: Vite serves `http://127.0.0.1:5173`.

- [ ] **Step 3: Browser verification**

Open `http://127.0.0.1:5173/#/dashboard` in the in-app browser and verify:
- Sidebar matches the observed dashboard structure.
- System metrics cards render.
- Task overview cards render.
- Submitting a YouTube URL creates a task and refreshes recent processing.
- `#/tasks` shows the task table.
- `#/tasks/{id}` shows timeline, logs, artifacts, and editable metadata.
- `#/videos` shows completed dry-run records.
- `#/settings` shows dependency/config status without secret values.

- [ ] **Step 4: Responsive verification**

Use browser viewport checks for:
- 1440px desktop.
- 1024px tablet.
- 390px mobile.

Expected:
- No overlapping text.
- No clipped buttons.
- Task form stacks on mobile.
- Tables remain readable or horizontally contained.

- [ ] **Step 5: Final verification commands**

Run:

```bash
rtk pytest -q
rtk npm --prefix frontend test
rtk npm --prefix frontend run build
rtk git status --short
```

Expected: tests/build PASS; `git status --short` only shows intentional changes.

- [ ] **Step 6: Commit UI verification fixes**

If files changed during manual verification:

```bash
rtk git add <changed-files>
rtk git commit -m "fix(ui): 修复工作台验证问题"
```

If no files changed, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage: tasks cover backend API, SQLite persistence, dry-run runner, dashboard UI, task queue, task detail, videos, settings, conda, Docker, and verification.
- Type consistency: backend statuses use `pending/running/success/failed/skipped/cancelled`; frontend `Status` uses the same values.
- API consistency: frontend client paths match FastAPI route paths.
- Security consistency: settings page shows secret presence only; logs and settings do not expose key values.
- UI consistency: layout follows the observed dashboard with left sidebar and high-density cards.
