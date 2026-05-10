import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.domain import TaskStatus
from backend.app.models import Task
from backend.app.repositories import TaskRepository
from backend.app.runner.ai_adapter import AiWorkflowAdapter
from backend.app.runner.processing import WorkflowRunner
from backend.app.runner.workflow import calculate_task_progress


@dataclass(frozen=True)
class DownloadResult:
    video_path: str
    thumbnail_path: str
    metadata: dict[str, object] = field(default_factory=dict)


class Downloader(Protocol):
    def download(self, task: Task) -> DownloadResult:
        raise NotImplementedError


class YtDlpDownloader:
    def __init__(
        self,
        storage_root: Path | str = "data/artifacts",
        cookies_path: Path | str | None = None,
    ):
        self.storage_root = Path(storage_root)
        settings = get_settings()
        self.cookies_path = Path(cookies_path or settings.youtube_cookies_path)

    def download(self, task: Task) -> DownloadResult:
        self._validate_runtime_dependencies()
        task_dir = self.storage_root / str(task.id)
        task_dir.mkdir(parents=True, exist_ok=True)
        output_template = task_dir / "source.%(ext)s"

        command = [
            "yt-dlp",
            "--no-playlist",
            "--write-thumbnail",
            "--convert-thumbnails",
            "jpg",
            "--recode-video",
            "mp4",
            "--paths",
            str(task_dir),
            "-o",
            output_template.name,
            task.input,
        ]
        if self.cookies_path.is_file():
            command.extend(["--cookies", str(self.cookies_path)])
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip() or "yt-dlp 下载失败"
            raise RuntimeError(self._format_download_error(detail))

        video_path = _newest_matching(task_dir, "source.mp4")
        thumbnail_path = _newest_matching(task_dir, "source.jpg")
        return DownloadResult(
            video_path=str(video_path),
            thumbnail_path=str(thumbnail_path),
            metadata={"downloader": "yt-dlp"},
        )

    @staticmethod
    def _validate_runtime_dependencies() -> None:
        if shutil.which("yt-dlp") is None:
            raise RuntimeError("yt-dlp 不可用，请先安装或修复 yt-dlp 可执行文件。")

        js_runtimes = ("node", "deno", "bun", "qjs", "quickjs")
        if not any(shutil.which(binary) for binary in js_runtimes):
            raise RuntimeError(
                "缺少可用的 JavaScript 运行时。请安装 Node.js（推荐）或其它受支持运行时，"
                "以便 yt-dlp 处理 YouTube challenge。"
            )

    @staticmethod
    def _format_download_error(detail: str) -> str:
        lowered = detail.lower()
        auth_markers = (
            "sign in to confirm",
            "use --cookies-from-browser or --cookies",
            "cookies are no longer valid",
            "for the authentication",
        )
        if any(marker in lowered for marker in auth_markers):
            return (
                "YouTube 认证失效或缺少有效登录态。"
                "请更新可用的 `cookies.txt`，或重新导出浏览器登录 cookies 后重试。"
                f" 原始错误：{detail[-600:]}"
            )

        challenge_markers = (
            "n challenge solving failed",
            "supported javascript runtime",
            "challenge solver script distribution",
            "only images are available for download",
            "requested format is not available",
        )
        if any(marker in lowered for marker in challenge_markers):
            return (
                "YouTube 挑战校验失败，当前环境无法解析真实视频格式。"
                "请确认容器或本机已安装可用的 Node.js，并更新 yt-dlp 及 challenge solver"
                "（例如 `pip install -U yt-dlp yt-dlp-ejs` 或等效环境安装）后重试。"
                f" 原始错误：{detail[-600:]}"
            )
        return detail[-1000:]


def _newest_matching(
    directory: Path,
    pattern: str,
    excluded_suffixes: set[str] | None = None,
) -> Path:
    excluded_suffixes = excluded_suffixes or set()
    candidates = [
        path
        for path in directory.glob(pattern)
        if path.is_file() and path.suffix.lower() not in excluded_suffixes
    ]
    if not candidates:
        raise RuntimeError(f"未找到下载产物：{directory / pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


class DownloadRunner:
    def __init__(self, repo: TaskRepository, downloader: Downloader | None = None):
        self.repo = repo
        self.downloader = downloader or YtDlpDownloader()

    def start(self, task_id: int) -> None:
        task = self._get_task(task_id)
        import_step = self._step(task, "import")
        download_step = self._step(task, "download_video")

        self.repo.update_step_status(import_step, TaskStatus.RUNNING, 50)
        self.repo.append_log(task.id, import_step.id, "info", "导入任务完成，准备下载视频")
        self.repo.update_step_status(import_step, TaskStatus.SUCCESS, 100)
        self.repo.update_step_status(download_step, TaskStatus.RUNNING, 10)
        self.repo.append_log(task.id, download_step.id, "info", "开始下载视频")
        self.repo.update_task_status(
            task,
            TaskStatus.RUNNING,
            current_step="download_video",
            progress=calculate_task_progress(task),
        )

    def run_task(self, task_id: int) -> None:
        task = self._get_task(task_id)
        download_step = self._step(task, "download_video")
        thumbnail_step = self._step(task, "download_thumbnail")

        try:
            result = self.downloader.download(task)
        except Exception as exc:
            message = f"下载视频失败：{exc}"
            self.repo.update_step_status(download_step, TaskStatus.FAILED, 100, message)
            self.repo.update_task_status(
                task,
                TaskStatus.FAILED,
                current_step="download_video",
                progress=calculate_task_progress(task),
                error_summary=message,
            )
            self.repo.append_log(task.id, download_step.id, "error", message)
            return

        self.repo.add_artifact(
            task.id,
            download_step.id,
            "video",
            result.video_path,
            result.metadata,
        )
        self.repo.update_step_status(download_step, TaskStatus.SUCCESS, 100)
        if thumbnail_step.status == TaskStatus.SKIPPED.value:
            self.repo.append_log(task.id, thumbnail_step.id, "info", "按本次提交设置跳过下载缩略图")
        else:
            self.repo.update_step_status(thumbnail_step, TaskStatus.RUNNING, 50)
            self.repo.add_artifact(
                task.id,
                thumbnail_step.id,
                "thumbnail",
                result.thumbnail_path,
                result.metadata,
            )
            self.repo.update_step_status(thumbnail_step, TaskStatus.SUCCESS, 100)
            self.repo.append_log(task.id, thumbnail_step.id, "info", "下载视频与缩略图完成")
        self.repo.update_task_status(
            task,
            TaskStatus.PENDING,
            current_step="extract_audio",
            progress=calculate_task_progress(task),
        )

    def _get_task(self, task_id: int) -> Task:
        task = self.repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        return task

    @staticmethod
    def _step(task: Task, step_name: str):
        for step in task.steps:
            if step.name == step_name:
                return step
        raise ValueError(f"Step {step_name} not found for task {task.id}")


def run_download_task(task_id: int) -> None:
    session = SessionLocal()
    try:
        repo = TaskRepository(session)
        DownloadRunner(repo).run_task(task_id)
        task = repo.get_task(task_id)
        if task is not None and task.status == TaskStatus.PENDING.value:
            WorkflowRunner(repo, adapter=AiWorkflowAdapter()).run_task(task_id)
    finally:
        session.close()
