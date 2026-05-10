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

MANUAL_UPLOAD_STEP_NAMES = frozenset(
    {
        StepName.UPLOAD_VIDEO.value,
        StepName.UPLOAD_SUBTITLE.value,
    }
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
