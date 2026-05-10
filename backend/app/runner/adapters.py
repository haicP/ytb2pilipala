import shutil
import subprocess
import textwrap
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from backend.app.config import get_settings
from backend.app.models import Task


@dataclass(frozen=True)
class AdapterResult:
    success: bool
    message: str
    artifacts: list[tuple[str, str]] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


class WorkflowAdapter(Protocol):
    def execute(self, task: Task, step_name: str) -> AdapterResult:
        raise NotImplementedError


class DryRunAdapter:
    def __init__(
        self,
        storage_root: Path | str = "data/artifacts",
        prefer_video_subtitles: bool = True,
    ):
        self.storage_root = Path(storage_root)
        self.prefer_video_subtitles = prefer_video_subtitles

    def execute(self, task: Task, step_name: str) -> AdapterResult:
        handlers = {
            "download_video": self._download_video,
            "download_thumbnail": self._download_thumbnail,
            "extract_audio": self._extract_audio,
            "transcribe": self._transcribe,
            "translate": self._translate,
            "synthesize_voice": self._synthesize_voice,
            "sync_preview": self._sync_preview,
            "generate_metadata": self._generate_metadata,
            "upload_video": self._skip_upload_video,
            "upload_subtitle": self._skip_upload_subtitle,
        }
        handler = handlers.get(step_name)
        if handler is None:
            return AdapterResult(
                success=True,
                message=f"dry-run step {step_name} completed",
                metadata={"mode": "dry-run"},
            )
        return handler(task)

    def _download_video(self, task: Task) -> AdapterResult:
        video_path = self._ensure_source_video(task.id)
        return AdapterResult(
            success=True,
            message="dry-run 视频已准备",
            artifacts=[("video", str(video_path))],
            metadata={"mode": "dry-run"},
        )

    def _download_thumbnail(self, task: Task) -> AdapterResult:
        thumbnail_path = self._ensure_thumbnail(task.id)
        return AdapterResult(
            success=True,
            message="dry-run 缩略图已准备",
            artifacts=[("thumbnail", str(thumbnail_path))],
            metadata={"mode": "dry-run"},
        )

    def _extract_audio(self, task: Task) -> AdapterResult:
        audio_path = self._ensure_audio(task.id)
        return AdapterResult(
            success=True,
            message="dry-run 音频已提取",
            artifacts=[("audio", str(audio_path))],
            metadata={"mode": "dry-run"},
        )

    def _transcribe(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task.id)
        subtitle_path = task_dir / "source.srt"
        downloaded_path = self._download_youtube_subtitle(
            task=task,
            task_dir=task_dir,
            language_selector="en-orig,en,en-US,en-GB",
            filename_prefix="subtitle-source",
            output_name="source.srt",
        )
        if downloaded_path is None:
            subtitle_path.write_text(
                textwrap.dedent(
                    f"""\
                    1
                    00:00:00,000 --> 00:00:02,500
                    Dry-run transcript for task {task.id}.

                    2
                    00:00:02,500 --> 00:00:05,000
                    Subtitle generation executed on the backend.
                    """
                ),
                encoding="utf-8",
            )
        return AdapterResult(
            success=True,
            message="源字幕已生成",
            artifacts=[("subtitle_source", str(subtitle_path))],
            metadata={
                "mode": "yt-dlp-auto-sub" if downloaded_path is not None else "dry-run",
            },
        )

    def _translate(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task.id)
        translated_path = task_dir / "zh.srt"
        downloaded_path = self._download_youtube_subtitle(
            task=task,
            task_dir=task_dir,
            language_selector="zh-Hans,zh-CN,zh-SG,zh",
            filename_prefix="subtitle-zh",
            output_name="zh.srt",
        )
        if downloaded_path is None:
            translated_path.write_text(
                textwrap.dedent(
                    f"""\
                    1
                    00:00:00,000 --> 00:00:02,500
                    任务 {task.id} 的 dry-run 中文字幕。

                    2
                    00:00:02,500 --> 00:00:05,000
                    该字幕文件由后端流程实际生成。
                    """
                ),
                encoding="utf-8",
            )
        return AdapterResult(
            success=True,
            message="中文字幕已生成",
            artifacts=[("subtitle_translated", str(translated_path))],
            metadata={
                "mode": "yt-dlp-auto-sub" if downloaded_path is not None else "dry-run",
            },
        )

    def _synthesize_voice(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task.id)
        voice_path = task_dir / "zh_voice.wav"
        self._write_silence_wav(voice_path, duration_seconds=5)
        return AdapterResult(
            success=True,
            message="dry-run 配音已生成",
            artifacts=[("voiceover", str(voice_path))],
            metadata={"mode": "dry-run"},
        )

    def _sync_preview(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task.id)
        preview_path = task_dir / "preview.mp4"
        video_path = self._ensure_source_video(task.id)
        voice_path = task_dir / "zh_voice.wav"
        if not voice_path.exists():
            self._write_silence_wav(voice_path, duration_seconds=5)
        self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-i",
                str(voice_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(preview_path),
            ],
            "生成预览视频失败",
        )
        return AdapterResult(
            success=True,
            message="dry-run 预览视频已生成",
            artifacts=[("preview", str(preview_path))],
            metadata={"mode": "dry-run"},
        )

    @staticmethod
    def _generate_metadata(task: Task) -> AdapterResult:
        return AdapterResult(
            success=True,
            message=f"dry-run metadata prepared for task {task.id}",
            metadata={"mode": "dry-run"},
        )

    @staticmethod
    def _skip_upload_video(task: Task) -> AdapterResult:
        return AdapterResult(
            success=True,
            message=f"dry-run upload_video skipped for task {task.id}",
            metadata={
                "mode": "dry-run",
                "step_status": "skipped",
                "skip_reason": "B 站上传尚未接入，当前步骤仅完成本地处理产物生成。",
            },
        )

    @staticmethod
    def _skip_upload_subtitle(task: Task) -> AdapterResult:
        return AdapterResult(
            success=True,
            message=f"dry-run upload_subtitle skipped for task {task.id}",
            metadata={
                "mode": "dry-run",
                "step_status": "skipped",
                "skip_reason": "B 站字幕上传尚未接入，当前步骤仅完成本地字幕产物生成。",
            },
        )

    def _task_dir(self, task_id: int) -> Path:
        task_dir = self.storage_root / str(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def _ensure_source_video(self, task_id: int) -> Path:
        task_dir = self._task_dir(task_id)
        video_candidates = [
            task_dir / f"source{suffix}"
            for suffix in (".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v")
        ]
        video_path = next((path for path in video_candidates if path.is_file()), None)
        if video_path is not None:
            return video_path

        fallback_path = task_dir / "source.mp4"
        self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=1280x720:rate=24",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-t",
                "5",
                "-shortest",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                str(fallback_path),
            ],
            "生成占位视频失败",
        )
        return fallback_path

    def _ensure_thumbnail(self, task_id: int) -> Path:
        task_dir = self._task_dir(task_id)
        thumbnail_path = task_dir / "source.jpg"
        if thumbnail_path.exists():
            return thumbnail_path

        video_path = self._ensure_source_video(task_id)
        self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                str(thumbnail_path),
            ],
            "生成缩略图失败",
        )
        return thumbnail_path

    def _ensure_audio(self, task_id: int) -> Path:
        task_dir = self._task_dir(task_id)
        audio_path = task_dir / "audio.wav"
        if audio_path.exists():
            return audio_path

        video_path = self._ensure_source_video(task_id)
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
        return audio_path

    def _download_youtube_subtitle(
        self,
        task: Task,
        task_dir: Path,
        language_selector: str,
        filename_prefix: str,
        output_name: str,
    ) -> Path | None:
        if not self.prefer_video_subtitles or task.source_type != "youtube":
            return None

        settings = get_settings()
        output_template = task_dir / f"{filename_prefix}.%(ext)s"
        command = [
            "yt-dlp",
            "--no-playlist",
            "--skip-download",
            "--write-auto-subs",
            "--write-subs",
            "--sub-langs",
            language_selector,
            "--sub-format",
            "srt",
            "--convert-subs",
            "srt",
            "--js-runtimes",
            "node",
            "--paths",
            str(task_dir),
            "-o",
            str(output_template),
            task.input,
        ]
        cookies_path = Path(settings.youtube_cookies_path)
        if cookies_path.is_file():
            command.extend(["--cookies", str(cookies_path)])
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            return None

        candidates = sorted(task_dir.glob(f"{filename_prefix}*.srt"))
        if not candidates:
            return None

        source_path = candidates[0]
        target_path = task_dir / output_name
        source_path.replace(target_path)
        for extra_path in candidates[1:]:
            if extra_path.exists():
                extra_path.unlink()
        return target_path

    @staticmethod
    def _newest_matching(
        directory: Path,
        pattern: str,
        excluded_suffixes: set[str] | None = None,
    ) -> Path | None:
        excluded_suffixes = excluded_suffixes or set()
        candidates = [
            path
            for path in directory.glob(pattern)
            if path.is_file() and path.suffix.lower() not in excluded_suffixes
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _write_silence_wav(path: Path, duration_seconds: int, sample_rate: int = 16_000) -> None:
        frame_count = duration_seconds * sample_rate
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * frame_count)

    @staticmethod
    def _run_ffmpeg(command: list[str], failure_message: str) -> None:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg 不可用，无法继续后续媒体处理步骤。")

        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode == 0:
            return

        detail = process.stderr.strip() or process.stdout.strip() or failure_message
        raise RuntimeError(f"{failure_message}：{detail[-800:]}")
