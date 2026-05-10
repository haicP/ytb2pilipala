# AI Workflow Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement real subtitle transcription and translation workflow for YouTube tasks using faster-whisper plus an OpenAI-compatible LLM, add `/assistant` prompt-template configuration, and update conda/Docker packaging so the feature runs locally and in containers.

**Architecture:** Keep the existing FastAPI + SQLite + task-step model. Add a dedicated assistant settings API backed by `app_settings`, reusable subtitle normalization utilities, a real AI workflow adapter for `extract_audio`/`transcribe`/`translate`/`generate_metadata`, and a generic processing runner that resumes from the first non-success step after download. The frontend `/assistant` route remains a dense configuration page, not a chat surface, and reuses the current settings-page interaction model.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, pytest, faster-whisper, openai, pysubs2, React 18, TypeScript, Vite, Vitest, Testing Library, Docker, conda.

---

## File Structure

Create or modify these files for this feature:

```text
backend/
  app/
    api/
      __init__.py                    # add assistant router
      assistant.py                   # prompt-template read/write API
      tasks.py                       # retry routing for post-download workflow
    config.py                        # whisper + LLM runtime settings
    repositories.py                  # generic app_settings helpers
    schemas.py                       # assistant settings request/response models
    runner/
      ai_adapter.py                  # real extract/transcribe/translate/metadata adapter
      llm.py                         # OpenAI-compatible translation + metadata clients
      processing.py                  # generic step runner for real workflow
      prompts.py                     # default prompt templates and merge helpers
      subtitles.py                   # subtitle probing, normalization, and SRT rendering
      download.py                    # hand off to processing runner after download
  tests/
    test_ai_adapter.py               # adapter behavior around whisper, reuse, and LLM fallback
    test_assistant_api.py            # assistant settings API contract
    test_processing_runner.py        # generic workflow runner behavior
    test_subtitles.py                # subtitle utility coverage
    test_download_runner.py          # post-download handoff assertion
    test_tasks_api.py                # retry semantics for translate-step failures
frontend/
  src/
    __tests__/
      AssistantPage.test.tsx         # prompt settings UI behavior
    api/
      client.ts                      # assistant settings client
      types.ts                       # assistant settings types
    components/
      AppShell.tsx                   # rename nav label to AI 配置
    pages/
      AssistantPage.tsx              # dense prompt-template configuration page
    styles.css                       # assistant-page layout and form styles
Dockerfile                           # runtime dependencies for whisper + LLM path
README.md                            # environment and verification docs
environment.yml                      # conda dependencies
pyproject.toml                       # Python package dependencies
```

Boundary decisions:

- Do **not** change workflow step names or ordering in `backend/app/domain.py`.
- Do **not** replace `DryRunAdapter` or `DryRunRunner`; add a parallel real workflow path instead.
- Keep `synthesize_voice`, `sync_preview`, `upload_video`, and `upload_subtitle` on the current dry-run/skip path for now.
- `/assistant` only manages prompt templates and dependency visibility; it must not grow chat state or conversation history.

---

### Task 1: Assistant Prompt Settings API

**Files:**
- Create: `backend/app/api/assistant.py`
- Create: `backend/app/runner/prompts.py`
- Create: `backend/tests/test_assistant_api.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/repositories.py`
- Modify: `backend/app/schemas.py`

- [ ] **Step 1: Write the failing assistant settings API tests**

Create `backend/tests/test_assistant_api.py`:

```python
from backend.app.runner.prompts import DEFAULT_ASSISTANT_PROMPTS


def test_get_assistant_settings_returns_defaults_when_db_empty(client):
    response = client.get("/api/assistant/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["postprocess_prompt"] == DEFAULT_ASSISTANT_PROMPTS["assistant_postprocess_prompt"]
    assert payload["translation_prompt"] == DEFAULT_ASSISTANT_PROMPTS["assistant_translation_prompt"]
    assert payload["metadata_prompt"] == DEFAULT_ASSISTANT_PROMPTS["assistant_metadata_prompt"]
    assert payload["defaults"] == {
        "postprocess_prompt": DEFAULT_ASSISTANT_PROMPTS["assistant_postprocess_prompt"],
        "translation_prompt": DEFAULT_ASSISTANT_PROMPTS["assistant_translation_prompt"],
        "metadata_prompt": DEFAULT_ASSISTANT_PROMPTS["assistant_metadata_prompt"],
    }
    assert payload["updated_at"] is None


def test_patch_assistant_settings_persists_new_templates(client):
    response = client.patch(
        "/api/assistant/settings",
        json={
            "postprocess_prompt": "后处理模板",
            "translation_prompt": "翻译模板",
            "metadata_prompt": "投稿模板",
        },
    )

    assert response.status_code == 200
    assert response.json()["postprocess_prompt"] == "后处理模板"
    assert response.json()["translation_prompt"] == "翻译模板"
    assert response.json()["metadata_prompt"] == "投稿模板"
    assert response.json()["updated_at"] is not None

    verify_response = client.get("/api/assistant/settings")
    assert verify_response.status_code == 200
    assert verify_response.json()["translation_prompt"] == "翻译模板"
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run:

```bash
pytest backend/tests/test_assistant_api.py -q
```

Expected: FAIL with `404 Not Found` for `/api/assistant/settings` and import errors until the new modules exist.

- [ ] **Step 3: Add prompt defaults, repository helpers, schemas, and routes**

Create `backend/app/runner/prompts.py`:

```python
from collections.abc import Mapping


DEFAULT_ASSISTANT_PROMPTS = {
    "assistant_postprocess_prompt": (
        "你负责整理 Whisper 转写结果。保留事实含义，清理明显口误、重复和噪声词，"
        "不要擅自改写技术术语或添加原文没有的信息。"
    ),
    "assistant_translation_prompt": (
        "你负责把字幕翻译为简体中文。保持原句含义、语气和信息密度，输出自然、可读、"
        "适合视频字幕的中文，不添加解释或注释。"
    ),
    "assistant_metadata_prompt": (
        "你负责根据视频标题、字幕摘要和翻译内容生成 B 站投稿信息。"
        "输出简体中文标题、简介、标签建议，避免夸张营销语气。"
    ),
}


def resolve_assistant_prompts(saved: Mapping[str, str]) -> dict[str, str]:
    return {
        key: saved.get(key, default_value)
        for key, default_value in DEFAULT_ASSISTANT_PROMPTS.items()
    }
```

Modify `backend/app/repositories.py` to add generic setting helpers near `update_metadata`:

```python
    def get_app_settings(self, keys: tuple[str, ...]) -> dict[str, str]:
        statement = select(AppSetting).where(AppSetting.key.in_(keys))
        rows = self.session.execute(statement).scalars().all()
        return {row.key: row.value for row in rows}

    def upsert_app_settings(self, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            setting = self.session.get(AppSetting, key)
            if setting is None:
                setting = AppSetting(key=key, value=value, updated_at=utc_now())
                self.session.add(setting)
            else:
                setting.value = value
                setting.updated_at = utc_now()
        self.session.commit()
        return self.get_app_settings(tuple(values))

    def latest_setting_timestamp(self, keys: tuple[str, ...]) -> datetime | None:
        statement = select(AppSetting).where(AppSetting.key.in_(keys)).order_by(AppSetting.updated_at.desc())
        row = self.session.execute(statement).scalars().first()
        return row.updated_at if row is not None else None
```

Modify `backend/app/schemas.py` to add assistant settings models:

```python
class AssistantSettingsPatchRequest(BaseModel):
    postprocess_prompt: str = Field(min_length=1, max_length=10_000)
    translation_prompt: str = Field(min_length=1, max_length=10_000)
    metadata_prompt: str = Field(min_length=1, max_length=10_000)


class AssistantSettingsResponse(BaseModel):
    postprocess_prompt: str
    translation_prompt: str
    metadata_prompt: str
    defaults: dict[str, str]
    updated_at: datetime | None
```

Create `backend/app/api/assistant.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.repositories import TaskRepository
from backend.app.runner.prompts import DEFAULT_ASSISTANT_PROMPTS, resolve_assistant_prompts
from backend.app.schemas import AssistantSettingsPatchRequest, AssistantSettingsResponse


router = APIRouter(prefix="/assistant", tags=["assistant"])

ASSISTANT_SETTING_KEYS = (
    "assistant_postprocess_prompt",
    "assistant_translation_prompt",
    "assistant_metadata_prompt",
)


def _response_from_saved(saved: dict[str, str], updated_at):
    resolved = resolve_assistant_prompts(saved)
    return AssistantSettingsResponse(
        postprocess_prompt=resolved["assistant_postprocess_prompt"],
        translation_prompt=resolved["assistant_translation_prompt"],
        metadata_prompt=resolved["assistant_metadata_prompt"],
        defaults={
            "postprocess_prompt": DEFAULT_ASSISTANT_PROMPTS["assistant_postprocess_prompt"],
            "translation_prompt": DEFAULT_ASSISTANT_PROMPTS["assistant_translation_prompt"],
            "metadata_prompt": DEFAULT_ASSISTANT_PROMPTS["assistant_metadata_prompt"],
        },
        updated_at=updated_at,
    )


@router.get("/settings", response_model=AssistantSettingsResponse)
def get_assistant_settings(db: Session = Depends(get_db_session)) -> AssistantSettingsResponse:
    repo = TaskRepository(db)
    saved = repo.get_app_settings(ASSISTANT_SETTING_KEYS)
    return _response_from_saved(saved, repo.latest_setting_timestamp(ASSISTANT_SETTING_KEYS))


@router.patch("/settings", response_model=AssistantSettingsResponse)
def patch_assistant_settings(
    payload: AssistantSettingsPatchRequest,
    db: Session = Depends(get_db_session),
) -> AssistantSettingsResponse:
    repo = TaskRepository(db)
    saved = repo.upsert_app_settings(
        {
            "assistant_postprocess_prompt": payload.postprocess_prompt.strip(),
            "assistant_translation_prompt": payload.translation_prompt.strip(),
            "assistant_metadata_prompt": payload.metadata_prompt.strip(),
        }
    )
    return _response_from_saved(saved, repo.latest_setting_timestamp(ASSISTANT_SETTING_KEYS))
```

Modify `backend/app/api/__init__.py`:

```python
from backend.app.api.assistant import router as assistant_router

api_router = APIRouter(prefix="/api")
api_router.include_router(assistant_router)
api_router.include_router(health_router)
api_router.include_router(system_router)
api_router.include_router(settings_router)
api_router.include_router(tasks_router)
api_router.include_router(videos_router)
```

- [ ] **Step 4: Run the assistant settings API tests to verify they pass**

Run:

```bash
pytest backend/tests/test_assistant_api.py -q
```

Expected: PASS with `2 passed`.

- [ ] **Step 5: Commit the assistant settings API slice**

Run:

```bash
git add backend/app/api/__init__.py backend/app/api/assistant.py backend/app/repositories.py backend/app/runner/prompts.py backend/app/schemas.py backend/tests/test_assistant_api.py
git commit -m "feat(assistant): 添加提示词配置接口"
```

---

### Task 2: Subtitle Probing, Normalization, And SRT Rendering

**Files:**
- Create: `backend/app/runner/subtitles.py`
- Create: `backend/tests/test_subtitles.py`

- [ ] **Step 1: Write the failing subtitle utility tests**

Create `backend/tests/test_subtitles.py`:

```python
from pathlib import Path

from backend.app.runner.subtitles import (
    TranscriptSegment,
    find_chinese_subtitle,
    normalize_subtitle_to_srt,
    write_segments_to_srt,
)


def test_find_chinese_subtitle_prefers_hans_variants(tmp_path):
    (tmp_path / "subtitle-source.en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    wanted = tmp_path / "subtitle-zh-Hans.ass"
    wanted.write_text(
        "[Script Info]\nTitle: test\n\n[Events]\nFormat: Layer, Start, End, Style, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,你好\n",
        encoding="utf-8",
    )

    detected = find_chinese_subtitle(tmp_path)

    assert detected == wanted


def test_normalize_subtitle_to_srt_converts_ass_to_utf8_srt(tmp_path):
    source = tmp_path / "subtitle-zh.ass"
    source.write_text(
        "[Script Info]\nTitle: test\n\n[Events]\nFormat: Layer, Start, End, Style, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.50,Default,字幕内容\n",
        encoding="utf-8",
    )
    output = tmp_path / "zh.srt"

    normalized = normalize_subtitle_to_srt(source, output)

    assert normalized == output
    text = output.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,500" in text
    assert "字幕内容" in text


def test_write_segments_to_srt_renders_expected_timestamps(tmp_path):
    output = tmp_path / "source.srt"

    write_segments_to_srt(
        [
            TranscriptSegment(start=0.0, end=1.25, text="Hello there."),
            TranscriptSegment(start=1.25, end=2.5, text="General Kenobi."),
        ],
        output,
    )

    assert output.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:01,250\n"
        "Hello there.\n\n"
        "2\n"
        "00:00:01,250 --> 00:00:02,500\n"
        "General Kenobi.\n"
    )
```

- [ ] **Step 2: Run the subtitle utility tests to verify they fail**

Run:

```bash
pytest backend/tests/test_subtitles.py -q
```

Expected: FAIL because `backend.app.runner.subtitles` does not exist yet.

- [ ] **Step 3: Implement subtitle discovery and normalization helpers**

Create `backend/app/runner/subtitles.py`:

```python
from dataclasses import dataclass
from pathlib import Path

import pysubs2


SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass"}
CHINESE_PREFIXES = ("zh-hans", "zh-cn", "zh-sg", "zh")


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


def find_chinese_subtitle(task_dir: Path) -> Path | None:
    candidates = sorted(path for path in task_dir.iterdir() if path.suffix.lower() in SUBTITLE_SUFFIXES)
    for prefix in CHINESE_PREFIXES:
        for path in candidates:
            stem = path.stem.lower().replace("_", "-")
            if stem == prefix or stem.startswith(f"{prefix}.") or stem.startswith(f"{prefix}-"):
                return path
    return None


def normalize_subtitle_to_srt(source_path: Path, output_path: Path) -> Path:
    subtitles = pysubs2.load(str(source_path))
    subtitles.save(str(output_path), format_="srt")
    return output_path


def _timestamp(seconds: float) -> str:
    total_milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def write_segments_to_srt(segments: list[TranscriptSegment], output_path: Path) -> Path:
    rendered = []
    for index, segment in enumerate(segments, start=1):
        rendered.append(
            f"{index}\n{_timestamp(segment.start)} --> {_timestamp(segment.end)}\n{segment.text.strip()}\n"
        )
    output_path.write_text("\n".join(rendered).strip() + "\n", encoding="utf-8")
    return output_path
```

- [ ] **Step 4: Run the subtitle utility tests to verify they pass**

Run:

```bash
pytest backend/tests/test_subtitles.py -q
```

Expected: PASS with `3 passed`.

- [ ] **Step 5: Commit the subtitle utility slice**

Run:

```bash
git add backend/app/runner/subtitles.py backend/tests/test_subtitles.py
git commit -m "feat(subtitle): 添加字幕探测与标准化工具"
```

---

### Task 3: AI Adapter For Extract, Transcribe, Translate, And Metadata

**Files:**
- Create: `backend/app/runner/ai_adapter.py`
- Create: `backend/app/runner/llm.py`
- Create: `backend/tests/test_ai_adapter.py`
- Modify: `backend/app/config.py`

- [ ] **Step 1: Write the failing AI adapter tests**

Create `backend/tests/test_ai_adapter.py`:

```python
import json
from pathlib import Path

from backend.app.domain import SourceType
from backend.app.repositories import TaskRepository
from backend.app.runner.ai_adapter import AiWorkflowAdapter, MetadataResult, TranscriptionResult
from backend.app.runner.subtitles import TranscriptSegment


class FakeTranscriber:
    def __init__(self):
        self.calls = 0

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        self.calls += 1
        return TranscriptionResult(
            language="en",
            segments=[
                TranscriptSegment(start=0.0, end=1.0, text="Hello"),
                TranscriptSegment(start=1.0, end=2.0, text="World"),
            ],
        )


class FakeTranslator:
    def __init__(self):
        self.calls = 0

    def translate_segments(self, segments, prompt: str) -> list[str]:
        self.calls += 1
        assert "简体中文" in prompt
        return ["你好", "世界"]


class FakeMetadataClient:
    def generate_metadata(self, *, title: str, translated_srt: str, prompt: str) -> MetadataResult:
        assert "投稿信息" in prompt
        return MetadataResult(
            title=f"【中文配音】{title}",
            description="自动生成简介",
            tags=["AI翻译", "中文字幕"],
            category="科技",
        )


def test_transcribe_uses_whisper_when_no_source_subtitle(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "audio.wav").write_bytes(b"wav")

    transcriber = FakeTranscriber()
    adapter = AiWorkflowAdapter(
        repo=repo,
        storage_root=tmp_path,
        transcriber=transcriber,
        translator=FakeTranslator(),
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "transcribe")

    assert result.success is True
    assert transcriber.calls == 1
    assert result.metadata["detected_source_language"] == "en"
    assert (task_dir / "source.srt").is_file()
    transcript_payload = json.loads((task_dir / "transcript.json").read_text(encoding="utf-8"))
    assert transcript_payload["language"] == "en"
    assert transcript_payload["segments"][0]["text"] == "Hello"


def test_translate_reuses_existing_local_chinese_subtitle_without_llm(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "subtitle-zh-Hans.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n现成字幕\n",
        encoding="utf-8",
    )

    translator = FakeTranslator()
    adapter = AiWorkflowAdapter(
        repo=repo,
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translator=translator,
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "translate")

    assert result.success is True
    assert translator.calls == 0
    assert result.metadata["translation_mode"] == "local_zh_reuse"
    assert (task_dir / "zh.srt").read_text(encoding="utf-8").count("现成字幕") == 1


def test_translate_falls_back_to_llm_and_writes_translation_json(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "source.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n2\n00:00:01,000 --> 00:00:02,000\nWorld\n",
        encoding="utf-8",
    )
    (task_dir / "transcript.json").write_text(
        json.dumps(
            {
                "language": "en",
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "Hello"},
                    {"start": 1.0, "end": 2.0, "text": "World"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    translator = FakeTranslator()
    adapter = AiWorkflowAdapter(
        repo=repo,
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translator=translator,
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "translate")

    assert result.success is True
    assert translator.calls == 1
    assert result.metadata["translation_mode"] == "llm"
    assert "你好" in (task_dir / "zh.srt").read_text(encoding="utf-8")
    translation_payload = json.loads((task_dir / "translation.json").read_text(encoding="utf-8"))
    assert translation_payload["segments"][1]["translated_text"] == "世界"


def test_generate_metadata_returns_submission_payload(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task.title = "demo"
    db_session.commit()
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "zh.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n中文字幕\n",
        encoding="utf-8",
    )

    adapter = AiWorkflowAdapter(
        repo=repo,
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translator=FakeTranslator(),
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "generate_metadata")

    assert result.success is True
    payload = result.metadata["submission_metadata"]
    assert payload["title"] == "【中文配音】demo"
    assert payload["tags"] == ["AI翻译", "中文字幕"]
```

- [ ] **Step 2: Run the AI adapter tests to verify they fail**

Run:

```bash
pytest backend/tests/test_ai_adapter.py -q
```

Expected: FAIL because `backend.app.runner.ai_adapter` and `backend.app.runner.llm` do not exist yet.

- [ ] **Step 3: Implement runtime settings, OpenAI clients, and the AI adapter**

Modify `backend/app/config.py`:

```python
class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./data/app.db"
    api2key_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    bilibili_credential_source: str = ""
    youtube_cookies_path: str = "./data/cookies.txt"
    whisper_model_size: str = "small"
    whisper_compute_type: str = "int8"
```

Create `backend/app/runner/llm.py`:

```python
import json

from openai import OpenAI

from backend.app.config import get_settings


class OpenAITranslationClient:
    def __init__(self):
        settings = get_settings()
        if not settings.api2key_base_url or not settings.llm_api_key:
            raise RuntimeError("缺少 API2KEY_BASE_URL 或 LLM_API_KEY，无法执行字幕翻译。")
        self.model = settings.llm_model
        self.client = OpenAI(base_url=settings.api2key_base_url, api_key=settings.llm_api_key)

    def translate_segments(self, segments: list[str], prompt: str) -> list[str]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps({"segments": segments}, ensure_ascii=False),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        translated = payload.get("segments", [])
        return [str(item) for item in translated]


class OpenAIMetadataClient:
    def __init__(self):
        settings = get_settings()
        if not settings.api2key_base_url or not settings.llm_api_key:
            raise RuntimeError("缺少 API2KEY_BASE_URL 或 LLM_API_KEY，无法生成投稿信息。")
        self.model = settings.llm_model
        self.client = OpenAI(base_url=settings.api2key_base_url, api_key=settings.llm_api_key)

    def generate_metadata(self, *, title: str, translated_srt: str, prompt: str) -> dict[str, object]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps({"title": title, "translated_srt": translated_srt}, ensure_ascii=False),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
```

Create `backend/app/runner/ai_adapter.py`:

```python
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from faster_whisper import WhisperModel

from backend.app.config import get_settings
from backend.app.runner.adapters import AdapterResult
from backend.app.runner.llm import OpenAIMetadataClient, OpenAITranslationClient
from backend.app.runner.prompts import resolve_assistant_prompts
from backend.app.runner.subtitles import (
    TranscriptSegment,
    find_chinese_subtitle,
    normalize_subtitle_to_srt,
    write_segments_to_srt,
)


@dataclass(frozen=True)
class TranscriptionResult:
    language: str
    segments: list[TranscriptSegment]


@dataclass(frozen=True)
class MetadataResult:
    title: str
    description: str
    tags: list[str]
    category: str


class FasterWhisperTranscriber:
    def __init__(self):
        settings = get_settings()
        self.model = WhisperModel(
            settings.whisper_model_size,
            compute_type=settings.whisper_compute_type,
        )

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        segments, info = self.model.transcribe(str(audio_path), vad_filter=True, beam_size=5)
        normalized = [
            TranscriptSegment(start=segment.start, end=segment.end, text=segment.text.strip())
            for segment in segments
            if segment.text.strip()
        ]
        return TranscriptionResult(language=info.language, segments=normalized)


class AiWorkflowAdapter:
    def __init__(
        self,
        repo,
        storage_root: Path | str = "data/artifacts",
        transcriber=None,
        translator=None,
        metadata_client=None,
    ):
        self.repo = repo
        self.storage_root = Path(storage_root)
        self.transcriber = transcriber or FasterWhisperTranscriber()
        self.translator = translator or OpenAITranslationClient()
        self.metadata_client = metadata_client or OpenAIMetadataClient()

    def execute(self, task, step_name: str) -> AdapterResult:
        handlers = {
            "extract_audio": self._extract_audio,
            "transcribe": self._transcribe,
            "translate": self._translate,
            "generate_metadata": self._generate_metadata,
        }
        handler = handlers.get(step_name)
        if handler is None:
            return AdapterResult(success=True, message=f"step {step_name} delegated to dry-run path")
        return handler(task)

    def _task_dir(self, task_id: int) -> Path:
        task_dir = self.storage_root / str(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def _load_prompts(self) -> dict[str, str]:
        saved = self.repo.get_app_settings(
            (
                "assistant_postprocess_prompt",
                "assistant_translation_prompt",
                "assistant_metadata_prompt",
            )
        )
        return resolve_assistant_prompts(saved)

    def _extract_audio(self, task) -> AdapterResult:
        task_dir = self._task_dir(task.id)
        audio_path = task_dir / "audio.wav"
        video_path = task_dir / "source.mp4"
        self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio_path),
            ],
            "提取音频失败",
        )
        return AdapterResult(
            success=True,
            message="音频已提取",
            artifacts=[("audio", str(audio_path))],
            metadata={"mode": "real"},
        )

    def _transcribe(self, task) -> AdapterResult:
        task_dir = self._task_dir(task.id)
        transcript = self.transcriber.transcribe(task_dir / "audio.wav")
        source_srt = write_segments_to_srt(transcript.segments, task_dir / "source.srt")
        (task_dir / "transcript.json").write_text(
            json.dumps(
                {
                    "language": transcript.language,
                    "segments": [asdict(segment) for segment in transcript.segments],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return AdapterResult(
            success=True,
            message="源字幕已生成",
            artifacts=[("subtitle_source", str(source_srt))],
            metadata={
                "mode": "real",
                "subtitle_source": "whisper",
                "detected_source_language": transcript.language,
            },
        )

    def _translate(self, task) -> AdapterResult:
        task_dir = self._task_dir(task.id)
        local_chinese = find_chinese_subtitle(task_dir)
        if local_chinese is not None:
            output = normalize_subtitle_to_srt(local_chinese, task_dir / "zh.srt")
            return AdapterResult(
                success=True,
                message="已复用现成简体中文字幕",
                artifacts=[("subtitle_translated", str(output))],
                metadata={"mode": "real", "translation_mode": "local_zh_reuse"},
            )

        transcript_payload = json.loads((task_dir / "transcript.json").read_text(encoding="utf-8"))
        prompts = self._load_prompts()
        source_segments = [
            TranscriptSegment(**segment)
            for segment in transcript_payload["segments"]
        ]
        translated_lines = self.translator.translate_segments(
            [segment.text for segment in source_segments],
            prompts["assistant_translation_prompt"],
        )
        translated_segments = [
            TranscriptSegment(start=segment.start, end=segment.end, text=translated_lines[index])
            for index, segment in enumerate(source_segments)
        ]
        zh_srt = write_segments_to_srt(translated_segments, task_dir / "zh.srt")
        (task_dir / "translation.json").write_text(
            json.dumps(
                {
                    "segments": [
                        {
                            "start": segment.start,
                            "end": segment.end,
                            "source_text": source_segments[index].text,
                            "translated_text": segment.text,
                        }
                        for index, segment in enumerate(translated_segments)
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return AdapterResult(
            success=True,
            message="中文字幕已生成",
            artifacts=[("subtitle_translated", str(zh_srt))],
            metadata={"mode": "real", "translation_mode": "llm"},
        )

    def _generate_metadata(self, task) -> AdapterResult:
        task_dir = self._task_dir(task.id)
        prompts = self._load_prompts()
        payload = self.metadata_client.generate_metadata(
            title=task.title,
            translated_srt=(task_dir / "zh.srt").read_text(encoding="utf-8"),
            prompt=prompts["assistant_metadata_prompt"],
        )
        return AdapterResult(
            success=True,
            message="投稿信息已生成",
            metadata={
                "mode": "real",
                "submission_metadata": {
                    "title": str(payload["title"]),
                    "description": str(payload["description"]),
                    "tags": [str(tag) for tag in payload["tags"]],
                    "category": str(payload.get("category", "科技")),
                },
            },
        )

    @staticmethod
    def _run_ffmpeg(command: list[str], failure_message: str) -> None:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg 不可用，无法继续后续媒体处理步骤。")
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip() or failure_message
            raise RuntimeError(f"{failure_message}：{detail[-800:]}")
```

- [ ] **Step 4: Run the AI adapter tests to verify they pass**

Run:

```bash
pytest backend/tests/test_ai_adapter.py -q
```

Expected: PASS with `4 passed`.

- [ ] **Step 5: Commit the AI adapter slice**

Run:

```bash
git add backend/app/config.py backend/app/runner/ai_adapter.py backend/app/runner/llm.py backend/tests/test_ai_adapter.py
git commit -m "feat(workflow): 添加字幕识别与翻译适配器"
```

---

### Task 4: Generic Processing Runner And Retry Routing

**Files:**
- Create: `backend/app/runner/processing.py`
- Create: `backend/tests/test_processing_runner.py`
- Modify: `backend/app/runner/download.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/tests/test_download_runner.py`
- Modify: `backend/tests/test_tasks_api.py`

- [ ] **Step 1: Write the failing runner and retry tests**

Create `backend/tests/test_processing_runner.py`:

```python
from backend.app.domain import SourceType, TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner.adapters import AdapterResult
from backend.app.runner.processing import WorkflowRunner


class FakeWorkflowAdapter:
    def execute(self, task, step_name: str):
        if step_name == "generate_metadata":
            return AdapterResult(
                success=True,
                message="metadata ready",
                metadata={
                    "submission_metadata": {
                        "title": "新的标题",
                        "description": "新的简介",
                        "tags": ["AI", "翻译"],
                        "category": "科技",
                    }
                },
            )
        return AdapterResult(success=True, message=f"{step_name} ok")


def test_workflow_runner_applies_submission_metadata_payload(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    for step in task.steps:
        if step.name in {"import", "download_video", "download_thumbnail"}:
            repo.update_step_status(step, TaskStatus.SUCCESS, 100)

    runner = WorkflowRunner(repo, adapter=FakeWorkflowAdapter())
    runner.run_task(task.id)
    loaded = repo.get_task(task.id)

    assert loaded is not None
    assert loaded.metadata_record.title == "新的标题"
    assert loaded.metadata_record.tags == "[\"AI\", \"翻译\"]"
```

Add a new test to `backend/tests/test_download_runner.py`:

```python
def test_run_download_task_hands_off_to_workflow_runner(db_session, monkeypatch, tmp_path):
    workflow_calls = []

    class FakeWorkflowRunner:
        def __init__(self, repo, adapter):
            self.repo = repo
            self.adapter = adapter

        def run_task(self, task_id: int) -> None:
            workflow_calls.append(task_id)

    monkeypatch.setattr(download_module, "WorkflowRunner", FakeWorkflowRunner)
```

Add a new test to `backend/tests/test_tasks_api.py`:

```python
def test_retry_failed_translate_task_restarts_processing_runner_only(client, db_session, monkeypatch):
    processing_calls = []
    download_calls = []

    class FakeWorkflowRunner:
        def __init__(self, repo, adapter):
            self.repo = repo
            self.adapter = adapter

        def run_task(self, task_id: int) -> None:
            processing_calls.append(task_id)

    monkeypatch.setattr("backend.app.api.tasks.WorkflowRunner", FakeWorkflowRunner)
    monkeypatch.setattr("backend.app.api.tasks.run_download_task", lambda task_id: download_calls.append(task_id))

    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/translate-retry")
    for step in task.steps:
        if step.name in {"import", "download_video", "download_thumbnail", "extract_audio", "transcribe"}:
            repo.update_step_status(step, TaskStatus.SUCCESS, 100)
        if step.name == "translate":
            repo.update_step_status(step, TaskStatus.FAILED, 100, "LLM timeout")
            repo.update_task_status(
                task,
                TaskStatus.FAILED,
                current_step="translate",
                progress=55,
                error_summary="LLM timeout",
            )

    response = client.post(f"/api/tasks/{task.id}/retry")

    assert response.status_code == 200
    assert processing_calls == [task.id]
    assert download_calls == []
```

- [ ] **Step 2: Run the runner and retry tests to verify they fail**

Run:

```bash
pytest backend/tests/test_processing_runner.py backend/tests/test_download_runner.py backend/tests/test_tasks_api.py -q
```

Expected: FAIL because `WorkflowRunner` does not exist and retry still routes through the download runner.

- [ ] **Step 3: Implement a generic processing runner and route retries correctly**

Create `backend/app/runner/processing.py`:

```python
import json

from backend.app.domain import TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner.workflow import calculate_task_progress


class WorkflowRunner:
    def __init__(self, repo: TaskRepository, adapter):
        self.repo = repo
        self.adapter = adapter

    def run_task(self, task_id: int) -> None:
        task = self.repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        self.repo.update_task_status(
            task,
            TaskStatus.RUNNING,
            current_step=task.current_step,
            progress=calculate_task_progress(task),
        )

        for step in sorted(task.steps, key=lambda item: item.order):
            if step.status in {TaskStatus.SUCCESS.value, TaskStatus.SKIPPED.value}:
                continue
            self.repo.update_step_status(step, TaskStatus.RUNNING, 10)
            self.repo.append_log(task.id, step.id, "info", f"开始执行：{step.label}")

            try:
                result = self.adapter.execute(task, step.name)
            except Exception as exc:
                message = f"workflow step {step.name} failed: {exc}"
                self.repo.update_step_status(step, TaskStatus.FAILED, 100, message)
                self.repo.update_task_status(
                    task,
                    TaskStatus.FAILED,
                    current_step=step.name,
                    progress=calculate_task_progress(task),
                    error_summary=message,
                )
                self.repo.append_log(task.id, step.id, "error", message)
                return

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

            submission_payload = result.metadata.get("submission_metadata")
            if submission_payload and task.metadata_record is not None:
                self.repo.update_metadata(
                    task_id=task.id,
                    title=str(submission_payload["title"]),
                    description=str(submission_payload["description"]),
                    tags=[str(tag) for tag in submission_payload["tags"]],
                    category=str(submission_payload["category"]),
                )

            step_status_value = str(result.metadata.get("step_status", TaskStatus.SUCCESS.value))
            step_status = TaskStatus(step_status_value)
            self.repo.update_step_status(step, step_status, 100)
            self.repo.append_log(task.id, step.id, "info", f"完成执行：{step.label}")
            self.repo.update_task_status(
                task,
                TaskStatus.RUNNING,
                current_step=step.name,
                progress=calculate_task_progress(task),
            )

        self.repo.update_task_status(task, TaskStatus.SUCCESS, progress=100)
        self.repo.append_log(task.id, None, "info", "真实工作流已完成")
```

Modify `backend/app/runner/download.py`:

```python
from backend.app.runner.ai_adapter import AiWorkflowAdapter
from backend.app.runner.processing import WorkflowRunner


def run_download_task(task_id: int) -> None:
    session = SessionLocal()
    try:
        repo = TaskRepository(session)
        DownloadRunner(repo).run_task(task_id)
        task = repo.get_task(task_id)
        if task is not None and task.status == TaskStatus.PENDING.value:
            WorkflowRunner(repo, adapter=AiWorkflowAdapter(repo)).run_task(task_id)
    finally:
        session.close()
```

Modify `backend/app/api/tasks.py`:

```python
from backend.app.runner.ai_adapter import AiWorkflowAdapter
from backend.app.runner.processing import WorkflowRunner

DOWNLOAD_PHASE_STEPS = {"import", "download_video", "download_thumbnail"}


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
    if task.status == TaskStatus.FAILED.value and failed_step_name is not None:
        for step in task.steps:
            if step.name == failed_step_name:
                step.retry_count += 1
            if step.status in {TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
                step.status = TaskStatus.PENDING.value
                step.progress = 0
                step.error_message = ""
                step.started_at = None
                step.finished_at = None
        task.current_step = failed_step_name
        task.status = TaskStatus.PENDING.value
        task.error_summary = ""
        task.progress = 0
        db.commit()
    elif task.status == TaskStatus.CANCELLED.value:
        for step in task.steps:
            if step.status == TaskStatus.CANCELLED.value:
                step.status = TaskStatus.PENDING.value
                step.progress = 0
                step.error_message = ""
                step.started_at = None
                step.finished_at = None
        task.status = TaskStatus.PENDING.value
        task.error_summary = ""
        task.progress = 0
        db.commit()

    if task.source_type == SourceType.YOUTUBE.value:
        if failed_step_name in DOWNLOAD_PHASE_STEPS or task.current_step in DOWNLOAD_PHASE_STEPS:
            DownloadRunner(repo).start(task_id)
            run_download_task(task_id)
        else:
            WorkflowRunner(repo, adapter=AiWorkflowAdapter(repo)).run_task(task_id)
    else:
        DryRunRunner(repo).run_task(task_id)
    return TaskResponse.from_model(_get_task_or_404(repo, task_id))
```

- [ ] **Step 4: Run the runner and retry tests to verify they pass**

Run:

```bash
pytest backend/tests/test_processing_runner.py backend/tests/test_download_runner.py backend/tests/test_tasks_api.py -q
```

Expected: PASS for the new runner and retry-path tests.

- [ ] **Step 5: Commit the workflow runner slice**

Run:

```bash
git add backend/app/api/tasks.py backend/app/runner/download.py backend/app/runner/processing.py backend/tests/test_processing_runner.py backend/tests/test_download_runner.py backend/tests/test_tasks_api.py
git commit -m "feat(workflow): 接入真实处理 runner"
```

---

### Task 5: Frontend Assistant Configuration Page

**Files:**
- Create: `frontend/src/__tests__/AssistantPage.test.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/pages/AssistantPage.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write the failing assistant page test**

Create `frontend/src/__tests__/AssistantPage.test.tsx`:

```tsx
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AssistantPage } from "../pages/AssistantPage";

const apiMock = vi.hoisted(() => ({
  assistantSettings: vi.fn(),
  settings: vi.fn(),
  updateAssistantSettings: vi.fn()
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock
}));

beforeEach(() => {
  apiMock.assistantSettings.mockResolvedValue({
    postprocess_prompt: "后处理模板",
    translation_prompt: "翻译模板",
    metadata_prompt: "投稿模板",
    defaults: {
      postprocess_prompt: "默认后处理模板",
      translation_prompt: "默认翻译模板",
      metadata_prompt: "默认投稿模板"
    },
    updated_at: "2026-05-04T00:30:00Z"
  });
  apiMock.settings.mockResolvedValue({
    dependencies: { yt_dlp: true, ffmpeg: true },
    config: { api2key_base_url: true, llm_key: true, bilibili_credential_source: false, youtube_cookies_file: true },
    settings: {}
  });
  apiMock.updateAssistantSettings.mockResolvedValue({
    postprocess_prompt: "新的后处理模板",
    translation_prompt: "新的翻译模板",
    metadata_prompt: "新的投稿模板",
    defaults: {
      postprocess_prompt: "默认后处理模板",
      translation_prompt: "默认翻译模板",
      metadata_prompt: "默认投稿模板"
    },
    updated_at: "2026-05-04T00:35:00Z"
  });
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("AssistantPage", () => {
  test("renders prompt editors and saves updated values", async () => {
    render(<AssistantPage />);

    expect(await screen.findByRole("heading", { name: "AI 配置" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("后处理模板")).toBeInTheDocument();
    expect(screen.getByDisplayValue("翻译模板")).toBeInTheDocument();
    expect(screen.getByDisplayValue("投稿模板")).toBeInTheDocument();
    expect(screen.getByText("LLM Key")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("字幕翻译提示词"), {
      target: { value: "新的翻译模板" }
    });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() =>
      expect(apiMock.updateAssistantSettings).toHaveBeenCalledWith({
        postprocess_prompt: "后处理模板",
        translation_prompt: "新的翻译模板",
        metadata_prompt: "投稿模板"
      })
    );
  });
});
```

- [ ] **Step 2: Run the assistant page test to verify it fails**

Run:

```bash
npm --prefix frontend test -- --run frontend/src/__tests__/AssistantPage.test.tsx
```

Expected: FAIL because the API client types and the page implementation do not exist yet.

- [ ] **Step 3: Implement assistant settings client, types, and page UI**

Modify `frontend/src/api/types.ts`:

```ts
export interface AssistantSettings {
  postprocess_prompt: string;
  translation_prompt: string;
  metadata_prompt: string;
  defaults: {
    postprocess_prompt: string;
    translation_prompt: string;
    metadata_prompt: string;
  };
  updated_at: string | null;
}

export interface AssistantSettingsUpdatePayload {
  postprocess_prompt: string;
  translation_prompt: string;
  metadata_prompt: string;
}
```

Modify `frontend/src/api/client.ts`:

```ts
import type {
  AssistantSettings,
  AssistantSettingsUpdatePayload,
  CreateTaskPayload,
  LogListResponse,
  MetadataUpdatePayload,
  SettingsSummary,
  SystemMetrics,
  Task,
  TaskListResponse
} from "./types";

export const apiClient = {
  assistantSettings: () => request<AssistantSettings>("/api/assistant/settings"),
  updateAssistantSettings: (payload: AssistantSettingsUpdatePayload) =>
    request<AssistantSettings>("/api/assistant/settings", {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
```

Modify `frontend/src/components/AppShell.tsx`:

```tsx
const navItems = [
  { key: "dashboard", label: "总览", href: "#/dashboard", icon: LayoutDashboard },
  { key: "assistant", label: "AI 配置", href: "#/assistant", icon: Bot },
  { key: "videos", label: "视频库", href: "#/videos", icon: Clapperboard },
  { key: "tasks", label: "任务", href: "#/tasks", icon: ListChecks },
  { key: "settings", label: "设置", href: "#/settings", icon: Settings }
] as const;
```

Replace `frontend/src/pages/AssistantPage.tsx`:

```tsx
import { RefreshCcw, Save } from "lucide-react";
import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type { AssistantSettings, SettingsSummary } from "../api/types";
import { Card } from "../components/Card";

const emptyAssistantSettings: AssistantSettings = {
  postprocess_prompt: "",
  translation_prompt: "",
  metadata_prompt: "",
  defaults: {
    postprocess_prompt: "",
    translation_prompt: "",
    metadata_prompt: ""
  },
  updated_at: null
};

const emptySystemSettings: SettingsSummary = {
  dependencies: {},
  config: {},
  settings: {}
};

export function AssistantPage() {
  const [settings, setSettings] = useState<AssistantSettings>(emptyAssistantSettings);
  const [systemSettings, setSystemSettings] = useState<SettingsSummary>(emptySystemSettings);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const [assistantSettings, summary] = await Promise.all([
          apiClient.assistantSettings(),
          apiClient.settings()
        ]);
        setSettings(assistantSettings);
        setSystemSettings(summary);
        setError("");
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "AI 配置加载失败");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  async function save() {
    setSaving(true);
    setMessage("");
    try {
      const updated = await apiClient.updateAssistantSettings({
        postprocess_prompt: settings.postprocess_prompt.trim(),
        translation_prompt: settings.translation_prompt.trim(),
        metadata_prompt: settings.metadata_prompt.trim()
      });
      setSettings(updated);
      setMessage("AI 配置已保存");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "AI 配置保存失败");
    } finally {
      setSaving(false);
    }
  }

  function resetToDefaults() {
    setSettings((current) => ({
      ...current,
      postprocess_prompt: current.defaults.postprocess_prompt,
      translation_prompt: current.defaults.translation_prompt,
      metadata_prompt: current.defaults.metadata_prompt
    }));
  }

  return (
    <div className="page">
      <Card>
        <div className="section-heading">
          <div>
            <span className="eyebrow">AI Configuration</span>
            <h1>AI 配置</h1>
          </div>
        </div>
        <p className="section-copy">该页面只管理提示词模板，不提供聊天会话。模板会影响转写后处理、字幕翻译和投稿信息生成。</p>
        <div className="assistant-status-grid">
          <div className="setting-kv">
            <span>api2key.base_url</span>
            <strong>{systemSettings.config.api2key_base_url ? "已配置" : "未配置"}</strong>
          </div>
          <div className="setting-kv">
            <span>LLM Key</span>
            <strong>{systemSettings.config.llm_key ? "已配置" : "未配置"}</strong>
          </div>
        </div>
      </Card>

      {error ? <div className="alert">AI 配置暂不可用：{error}</div> : null}
      {loading ? <p className="empty-state">加载 AI 配置...</p> : null}

      <div className="assistant-grid">
        <Card>
          <label className="assistant-field" htmlFor="assistant-postprocess">
            <span>转写后处理提示词</span>
            <textarea
              id="assistant-postprocess"
              className="textarea"
              rows={8}
              value={settings.postprocess_prompt}
              onChange={(event) => setSettings((current) => ({ ...current, postprocess_prompt: event.target.value }))}
            />
          </label>
        </Card>
        <Card>
          <label className="assistant-field" htmlFor="assistant-translation">
            <span>字幕翻译提示词</span>
            <textarea
              id="assistant-translation"
              className="textarea"
              rows={8}
              value={settings.translation_prompt}
              onChange={(event) => setSettings((current) => ({ ...current, translation_prompt: event.target.value }))}
            />
          </label>
        </Card>
        <Card>
          <label className="assistant-field" htmlFor="assistant-metadata">
            <span>投稿信息生成提示词</span>
            <textarea
              id="assistant-metadata"
              className="textarea"
              rows={8}
              value={settings.metadata_prompt}
              onChange={(event) => setSettings((current) => ({ ...current, metadata_prompt: event.target.value }))}
            />
          </label>
        </Card>
      </div>

      <Card>
        <div className="assistant-actions">
          <button className="icon-text-button" type="button" onClick={resetToDefaults}>
            <RefreshCcw size={14} aria-hidden="true" />
            <span>恢复默认</span>
          </button>
          <button className="button" type="button" disabled={saving} onClick={() => void save()}>
            <Save size={16} aria-hidden="true" />
            <span>{saving ? "保存中" : "保存配置"}</span>
          </button>
        </div>
        {message ? <p className="form-note">{message}</p> : null}
      </Card>
    </div>
  );
}
```

Append assistant styles to `frontend/src/styles.css`:

```css
.assistant-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.assistant-status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.assistant-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.assistant-field span {
  font-weight: 600;
}

.textarea {
  min-height: 180px;
  padding: 12px 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fff;
  color: inherit;
  resize: vertical;
}

.assistant-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

@media (max-width: 1024px) {
  .assistant-grid {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 4: Run the assistant page test to verify it passes**

Run:

```bash
npm --prefix frontend test -- --run frontend/src/__tests__/AssistantPage.test.tsx
```

Expected: PASS with `1 passed`.

- [ ] **Step 5: Commit the assistant page slice**

Run:

```bash
git add frontend/src/__tests__/AssistantPage.test.tsx frontend/src/api/client.ts frontend/src/api/types.ts frontend/src/components/AppShell.tsx frontend/src/pages/AssistantPage.tsx frontend/src/styles.css
git commit -m "feat(frontend): 添加 AI 配置页面"
```

---

### Task 6: Runtime Dependencies, Docker Packaging, And Documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `environment.yml`
- Modify: `Dockerfile`
- Modify: `README.md`

- [ ] **Step 1: Update the Python and conda dependency manifests**

Modify `pyproject.toml` dependencies:

```toml
[project]
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.30.0",
  "pydantic>=2.8.0",
  "pydantic-settings>=2.4.0",
  "sqlalchemy>=2.0.32",
  "python-multipart>=0.0.9",
  "psutil>=6.0.0",
  "faster-whisper>=1.1.0",
  "openai>=1.45.0",
  "pysubs2>=1.7.3",
]
```

Modify `environment.yml`:

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
      - yt-dlp-ejs
```

- [ ] **Step 2: Update the Docker runtime and project docs**

Modify `Dockerfile`:

```dockerfile
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=sqlite:///./data/app.db
ENV WHISPER_MODEL_SIZE=small
ENV WHISPER_COMPUTE_TYPE=int8

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir yt-dlp yt-dlp-ejs

COPY pyproject.toml ./
COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN pip install --no-cache-dir .
```

Update `README.md` sections:

```md
## 配置

复制 `.env.example` 为 `.env`，按需设置：

- `API2KEY_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`：默认 `gpt-4.1-mini`
- `WHISPER_MODEL_SIZE`：默认 `small`
- `WHISPER_COMPUTE_TYPE`：默认 `int8`
- `BILIBILI_CREDENTIAL_SOURCE`
- `YOUTUBE_COOKIES_PATH`

## AI 配置页面

打开 `http://127.0.0.1:5173/#/assistant` 可以配置：

- 转写后处理提示词
- 字幕翻译提示词
- 投稿信息生成提示词

## 验证命令

```bash
pytest -q
npm --prefix frontend test
npm --prefix frontend run build
docker build -t ytb2pilipala:local .
```
```

- [ ] **Step 3: Run backend, frontend, and Docker verification commands**

Run:

```bash
pytest -q
npm --prefix frontend test
npm --prefix frontend run build
docker build -t ytb2pilipala:local .
```

Expected:

- `pytest -q` exits `0`
- `npm --prefix frontend test` exits `0`
- `npm --prefix frontend run build` exits `0`
- `docker build -t ytb2pilipala:local .` exits `0`

- [ ] **Step 4: Commit the packaging slice**

Run:

```bash
git add pyproject.toml environment.yml Dockerfile README.md
git commit -m "chore(runtime): 补齐 AI 工作流依赖"
```

---

### Task 7: Browser Verification And Reference Dashboard Check

**Files:**
- Modify if needed after verification: `frontend/src/pages/AssistantPage.tsx`
- Modify if needed after verification: `frontend/src/styles.css`

- [ ] **Step 1: Start the backend and frontend locally**

Run:

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

Expected:

- FastAPI responds on `http://127.0.0.1:8000/api/health`
- Vite serves the app on `http://127.0.0.1:5173/#/assistant`

- [ ] **Step 2: Verify the assistant page in desktop and narrow widths**

Check in the in-app browser:

1. Open `http://127.0.0.1:5173/#/assistant`
2. Confirm the page loads three prompt editors plus dependency status
3. Confirm there is no overflow at 375px, 768px, and 1024px widths
4. Confirm save and restore-default interactions are visible and usable

Expected:

- No text overlap
- No horizontal scroll on mobile width
- No chat-style UI elements

- [ ] **Step 3: Retry the reference dashboard comparison once**

Run:

```bash
curl -I --max-time 5 http://127.0.0.1:8096/dashboard/
```

Expected:

- If the reference dashboard is available, compare `/assistant` density, card spacing, and control grouping against it and make one final CSS pass.
- If the reference dashboard is still unavailable, do **not** block release; report the absolute date `2026-05-04` and the concrete error (`connection refused`) in the final implementation summary.

- [ ] **Step 4: Commit any final UI polish after browser verification**

Run:

```bash
git add frontend/src/pages/AssistantPage.tsx frontend/src/styles.css
git commit -m "refactor(frontend): 收敛 AI 配置页工作台布局"
```
