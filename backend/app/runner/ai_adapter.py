import json
import subprocess
import wave
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pysubs2

from backend.app.config import get_settings
from backend.app.models import Task
from backend.app.runner.adapters import AdapterResult
from backend.app.runner.subtitles import (
    TranscriptSegment,
    TtsSentenceGroup,
    TtsTextRewriteExample,
    build_dubbing_plan,
    dump_dubbing_plan,
    find_chinese_subtitle,
    find_unprotected_english_fragments,
    group_segments_for_tts,
    merge_incomplete_sentence_segments,
    normalize_subtitle_to_srt,
    normalize_tts_request_text,
    normalize_tts_request_text_with_report,
    protected_tts_fragment_count,
    summarize_dubbing_plan,
    tts_text_ends_with_sentence_punctuation,
    write_segments_to_srt,
)
from backend.app.runner.tts import (
    VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES,
    SpeechSynthesisClient,
    VoiceCloneReference,
    build_voice_clone_reference,
    compress_wav_to_duration,
    default_speech_client,
    pcm16_duration_seconds,
    read_wav_pcm16,
    silence_pcm16,
    trim_pcm16,
    trim_pcm16_silence,
    write_pcm16_wav,
)

VOICE_CLONE_REFERENCE_INITIAL_SECONDS = 60.0
VOICE_CLONE_REFERENCE_MIN_SECONDS = 0.25
TTS_CONCURRENCY_MIN = 1
TTS_CONCURRENCY_MAX = 50
TTS_SILENCE_TRIM_THRESHOLD = 300
TTS_SILENCE_TRIM_PADDING_SECONDS = 0.08
TTS_COMPRESSION_WARNING_RATIO = 1.35
TTS_STRONG_COMPRESSION_RATIO = 2.5


ProgressCallback = Callable[[int], None]


@dataclass(frozen=True)
class TranscriptionResult:
    segments: list[TranscriptSegment]
    detected_source_language: str


@dataclass(frozen=True)
class MetadataResult:
    title: str
    description: str
    tags: list[str]
    category: str = "科技"


@dataclass(frozen=True)
class TtsTextRewriteResult:
    segments: list[TranscriptSegment]
    source: str
    detected_count: int
    rewritten_count: int
    unresolved_count: int
    protected_count: int
    warning_count: int
    rewrite_examples: tuple[TtsTextRewriteExample, ...]
    warnings: tuple[str, ...] = ()


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        raise NotImplementedError


class TranslationClient(Protocol):
    def translate_segments(
        self,
        segments: list[TranscriptSegment],
        target_language: str = "zh",
    ) -> list[TranscriptSegment]:
        raise NotImplementedError


class MetadataClient(Protocol):
    def generate_metadata(
        self,
        task: Task,
        transcript_segments: list[TranscriptSegment],
        translated_segments: list[TranscriptSegment],
    ) -> MetadataResult:
        raise NotImplementedError


class TtsTextRewriteClient(Protocol):
    def rewrite_segments(
        self,
        segments: list[TranscriptSegment],
    ) -> TtsTextRewriteResult:
        raise NotImplementedError


class FasterWhisperTranscriber:
    def __init__(self, model_size: str | None = None, compute_type: str | None = None):
        settings = get_settings()
        self.model_size = model_size if model_size is not None else settings.whisper_model_size
        self.compute_type = compute_type if compute_type is not None else settings.whisper_compute_type
        self.download_root = settings.hf_hub_cache.strip() or None
        self._model = None

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        segments, info = self._whisper_model().transcribe(str(audio_path))
        transcript_segments = [
            TranscriptSegment(start=float(segment.start), end=float(segment.end), text=segment.text.strip())
            for segment in segments
            if segment.text.strip()
        ]
        return TranscriptionResult(
            segments=transcript_segments,
            detected_source_language=str(getattr(info, "language", "") or ""),
        )

    def _whisper_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("faster_whisper package is required for transcription") from exc
            self._model = WhisperModel(
                self.model_size,
                compute_type=self.compute_type,
                download_root=self.download_root,
            )
        return self._model


class AiWorkflowAdapter:
    def __init__(
        self,
        storage_root: Path | str = "data/artifacts",
        transcriber: Transcriber | None = None,
        translation_client: TranslationClient | None = None,
        metadata_client: MetadataClient | None = None,
        tts_text_rewrite_client: TtsTextRewriteClient | None = None,
        speech_client: SpeechSynthesisClient | None = None,
        progress_callback: ProgressCallback | None = None,
        tts_concurrency: int | None = None,
    ):
        self.storage_root = Path(storage_root)
        self.transcriber = transcriber or FasterWhisperTranscriber()
        self.translation_client = translation_client or self._default_translation_client()
        self.metadata_client = metadata_client or self._default_metadata_client()
        self.tts_text_rewrite_client = (
            tts_text_rewrite_client or self._default_tts_text_rewrite_client()
        )
        self.speech_client = speech_client or self._default_speech_client()
        self.progress_callback = progress_callback
        self.tts_concurrency = tts_concurrency if tts_concurrency is not None else self._configured_tts_concurrency()

    def execute(self, task: Task, step_name: str) -> AdapterResult:
        if step_name == "extract_audio":
            return self._extract_audio(task)
        if step_name == "transcribe":
            return self._transcribe(task)
        if step_name == "translate":
            return self._translate(task)
        if step_name == "synthesize_voice":
            return self._synthesize_voice(task)
        if step_name == "sync_preview":
            return self._sync_preview(task)
        if step_name == "generate_metadata":
            return self._generate_metadata(task)
        return AdapterResult(
            success=True,
            message=f"AI adapter skipped unsupported step {step_name}",
            metadata={"step_status": "skipped"},
        )

    def _extract_audio(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task)
        task_dir.mkdir(parents=True, exist_ok=True)
        video_path = self._source_video_path(task, task_dir)
        audio_path = task_dir / "audio.wav"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(audio_path),
        ]
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip() or "ffmpeg 提取音频失败"
            raise RuntimeError(detail[-1000:])
        return AdapterResult(
            success=True,
            message="audio extracted",
            artifacts=[("audio", str(audio_path))],
            metadata={"extractor": "ffmpeg"},
        )

    def _transcribe(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task)
        audio_path = task_dir / "audio.wav"
        if not audio_path.is_file():
            raise RuntimeError(f"音频文件不存在：{audio_path}")

        result = self.transcriber.transcribe(audio_path)
        source_srt = write_segments_to_srt(result.segments, task_dir / "source.srt")
        transcript_json = task_dir / "transcript.json"
        self._write_json(
            transcript_json,
            {
                "detected_source_language": result.detected_source_language,
                "segments": self._dump_segments(result.segments),
            },
        )
        return AdapterResult(
            success=True,
            message="transcription completed",
            artifacts=[
                ("subtitle_source", str(source_srt)),
                ("transcript", str(transcript_json)),
            ],
            metadata={"detected_source_language": result.detected_source_language},
        )

    def _translate(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task)
        zh_srt = task_dir / "zh.srt"
        local_subtitle = find_chinese_subtitle(task_dir)
        if local_subtitle is not None:
            if local_subtitle.resolve() != zh_srt.resolve():
                normalize_subtitle_to_srt(local_subtitle, zh_srt)
            translated_segments = self._read_srt_segments(zh_srt)
            translation_json = task_dir / "translation.json"
            transcript_segments = self._read_segments(task_dir / "transcript.json")
            dubbing_plan_path = task_dir / "dubbing_plan.json"
            dubbing_plan_summary = self._write_dubbing_plan(
                dubbing_plan_path,
                source_segments=transcript_segments,
                translated_segments=translated_segments,
            )
            self._write_json(
                translation_json,
                {
                    "target_language": "zh",
                    "source": "local_zh_reuse",
                    "dubbing_plan_path": str(dubbing_plan_path),
                    "duration_fit_summary": dubbing_plan_summary,
                    "segments": self._dump_segments(translated_segments),
                },
            )
            return AdapterResult(
                success=True,
                message="local Chinese subtitle reused",
                artifacts=[
                    ("subtitle_translated", str(zh_srt)),
                    ("translation", str(translation_json)),
                    ("dubbing_plan", str(dubbing_plan_path)),
                ],
                metadata={
                    "translation_mode": "local_zh_reuse",
                    "dubbing_plan_segment_count": dubbing_plan_summary["segment_count"],
                    "dubbing_plan_warning_count": dubbing_plan_summary["warning_count"],
                },
            )

        transcript_segments = self._read_segments(task_dir / "transcript.json")
        translation_source_segments = merge_incomplete_sentence_segments(transcript_segments)
        translated_segments = self.translation_client.translate_segments(translation_source_segments, "zh")
        write_segments_to_srt(translated_segments, zh_srt)
        translation_json = task_dir / "translation.json"
        dubbing_plan_path = task_dir / "dubbing_plan.json"
        dubbing_plan_summary = self._write_dubbing_plan(
            dubbing_plan_path,
            source_segments=transcript_segments,
            translated_segments=translated_segments,
        )
        merged_segment_count = len(transcript_segments) - len(translation_source_segments)
        self._write_json(
            translation_json,
            {
                "target_language": "zh",
                "source_segment_count": len(transcript_segments),
                "translation_segment_count": len(translated_segments),
                "merged_segment_count": merged_segment_count,
                "segments_merged": merged_segment_count > 0,
                "dubbing_plan_path": str(dubbing_plan_path),
                "duration_fit_summary": dubbing_plan_summary,
                "segments": self._dump_segments(translated_segments),
            },
        )
        return AdapterResult(
            success=True,
            message="LLM translation completed",
            artifacts=[
                ("subtitle_translated", str(zh_srt)),
                ("translation", str(translation_json)),
                ("dubbing_plan", str(dubbing_plan_path)),
            ],
            metadata={
                "translation_mode": "llm",
                "source_segment_count": len(transcript_segments),
                "translation_segment_count": len(translated_segments),
                "merged_segment_count": merged_segment_count,
                "segments_merged": merged_segment_count > 0,
                "dubbing_plan_segment_count": dubbing_plan_summary["segment_count"],
                "dubbing_plan_warning_count": dubbing_plan_summary["warning_count"],
            },
        )

    def _generate_metadata(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task)
        transcript_segments = self._read_segments(task_dir / "transcript.json")
        translated_segments = self._read_segments(task_dir / "translation.json")
        metadata = self.metadata_client.generate_metadata(task, transcript_segments, translated_segments)
        payload = {
            "title": metadata.title,
            "description": metadata.description,
            "tags": metadata.tags,
            "category": metadata.category,
        }
        return AdapterResult(
            success=True,
            message="submission metadata generated",
            metadata={"submission_metadata": payload},
        )

    def _synthesize_voice(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task)
        translated_segments, tts_plan_source = self._read_tts_plan_segments(task_dir)
        rewrite_result = self._rewrite_tts_text_segments(translated_segments)
        translated_segments = rewrite_result.segments
        voice_reference = self._voice_clone_reference(task_dir) if self._uses_voice_clone() else None
        aligned = self._aligned_tts_pcm(
            task_dir,
            translated_segments,
            voice_reference,
            tts_plan_source=tts_plan_source,
            rewrite_result=rewrite_result,
        )
        if not aligned["pcm"]:
            raise RuntimeError("中文字幕内容为空，无法合成配音")

        voice_path = task_dir / "zh_voice.wav"
        write_pcm16_wav(
            voice_path,
            pcm_bytes=aligned["pcm"],
            sample_rate=self.speech_client.sample_rate,
        )
        artifacts = [("voiceover", str(voice_path))]
        metadata: dict[str, object] = {
            "tts_provider": getattr(self.speech_client, "tts_provider", ""),
            "tts_plan_source": aligned["plan_source"],
            "tts_segment_count": aligned["segment_count"],
            "tts_subtitle_segment_count": aligned["subtitle_segment_count"],
            "tts_sentence_group_count": aligned["sentence_group_count"],
            "tts_grouped_subtitle_segment_count": aligned["grouped_subtitle_segment_count"],
            "tts_sentence_grouped": aligned["sentence_grouped"],
            "tts_sample_rate": self.speech_client.sample_rate,
            "tts_timeline_aligned": True,
            "tts_segments_compressed": aligned["compressed_segments"],
            "tts_segments_trimmed": aligned["trimmed_segments"],
            "tts_alignment_warnings": aligned["warnings"],
            "tts_incomplete_sentence_group_count": aligned["incomplete_sentence_group_count"],
            "tts_request_text_normalized_count": aligned["request_text_normalized_count"],
            "tts_silence_trimmed_segments": aligned["silence_trimmed_segments"],
            "tts_silence_trimmed_seconds": aligned["silence_trimmed_seconds"],
            "tts_duration_fit_warning_count": aligned["duration_fit_warning_count"],
            "tts_max_compression_ratio": aligned["max_compression_ratio"],
            "tts_average_compression_ratio": aligned["average_compression_ratio"],
            "tts_strong_compression_warning_count": aligned["strong_compression_warning_count"],
            "tts_english_detected_count": aligned["english_detected_count"],
            "tts_english_rewritten_count": aligned["english_rewritten_count"],
            "tts_unresolved_english_count": aligned["unresolved_english_count"],
            "tts_protected_english_count": aligned["protected_count"],
            "tts_rewrite_examples": aligned["rewrite_examples"],
            "tts_rewrite_source": aligned["rewrite_source"],
            "tts_rewrite_warning_count": aligned["rewrite_warning_count"],
        }
        if voice_reference is not None:
            artifacts.insert(0, ("voice_clone_reference", str(voice_reference.path)))
            metadata.update(
                {
                    "tts_voice_clone_reference_path": str(voice_reference.path),
                    "tts_voice_clone_reference_bytes": voice_reference.file_size_bytes,
                    "tts_voice_clone_reference_base64_bytes": voice_reference.base64_size_bytes,
                    "tts_voice_clone_reference_duration_seconds": voice_reference.duration_seconds,
                    "tts_voice_clone_reference_truncated": voice_reference.truncated,
                    "tts_voice_clone_reference_mime_type": voice_reference.mime_type,
                }
            )
        return AdapterResult(
            success=True,
            message="voice synthesized",
            artifacts=artifacts,
            metadata=metadata,
        )

    def _sync_preview(self, task: Task) -> AdapterResult:
        task_dir = self._task_dir(task)
        video_path = self._source_video_path(task, task_dir)
        voice_path = task_dir / "zh_voice.wav"
        if not voice_path.is_file():
            raise RuntimeError(f"配音文件不存在：{voice_path}")
        preview_path = task_dir / "preview.mp4"
        command = [
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
        ]
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip() or "ffmpeg 生成预览视频失败"
            raise RuntimeError(detail[-1000:])
        return AdapterResult(
            success=True,
            message="preview synchronized",
            artifacts=[("preview", str(preview_path))],
            metadata={"preview_generator": "ffmpeg"},
        )

    def _task_dir(self, task: Task) -> Path:
        return self.storage_root / str(task.id)

    def _source_video_path(self, task: Task, task_dir: Path) -> Path:
        for artifact in task.artifacts:
            if artifact.artifact_type == "video":
                artifact_path = Path(artifact.path)
                if artifact_path.is_file():
                    return artifact_path
                candidate = Path.cwd() / artifact_path
                if candidate.is_file():
                    return candidate

        candidates = [
            path
            for path in task_dir.glob("source.*")
            if path.suffix.lower() not in {".json", ".srt", ".ass", ".vtt", ".jpg", ".png", ".webp"}
        ]
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime)
        raise RuntimeError(f"未找到源视频文件：{task_dir / 'source.*'}")

    def _read_segments(self, path: Path) -> list[TranscriptSegment]:
        if not path.is_file():
            raise RuntimeError(f"缺少字幕段落文件：{path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} must contain valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must contain a JSON object")
        raw_segments = payload.get("segments")
        if not isinstance(raw_segments, list):
            raise ValueError(f"{path} must include a segments array")
        return [
            self._segment_from_json_item(path, index, item)
            for index, item in enumerate(raw_segments)
        ]

    def _read_tts_plan_segments(self, task_dir: Path) -> tuple[list[TranscriptSegment], str]:
        dubbing_plan_path = task_dir / "dubbing_plan.json"
        if dubbing_plan_path.is_file():
            return self._read_dubbing_plan_segments(dubbing_plan_path), "dubbing_plan"
        return self._read_segments(task_dir / "translation.json"), "translation_json"

    def _read_dubbing_plan_segments(self, path: Path) -> list[TranscriptSegment]:
        if not path.is_file():
            raise RuntimeError(f"缺少配音计划文件：{path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} must contain valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must contain a JSON object")
        raw_segments = payload.get("segments")
        if not isinstance(raw_segments, list):
            raise ValueError(f"{path} must include a segments array")

        segments: list[TranscriptSegment] = []
        for index, item in enumerate(raw_segments):
            if not isinstance(item, dict):
                raise ValueError(f"{path} segment {index} must be an object")
            try:
                segments.append(
                    TranscriptSegment(
                        start=float(item["start"]),
                        end=float(item["end"]),
                        text=str(item["zh_text"]),
                        tts_text=(
                            str(item["tts_text"])
                            if "tts_text" in item and item["tts_text"] is not None
                            else None
                        ),
                    )
                )
            except KeyError as exc:
                raise ValueError(f"{path} segment {index} missing {exc.args[0]}") from exc
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path} segment {index} has invalid start/end/zh_text") from exc
        return segments

    def _segment_from_json_item(self, path: Path, index: int, item: object) -> TranscriptSegment:
        if not isinstance(item, dict):
            raise ValueError(f"{path} segment {index} must be an object")
        try:
            return TranscriptSegment(
                start=float(item["start"]),
                end=float(item["end"]),
                text=str(item["text"]),
                tts_text=(
                    str(item["tts_text"])
                    if "tts_text" in item and item["tts_text"] is not None
                    else None
                ),
            )
        except KeyError as exc:
            raise ValueError(f"{path} segment {index} missing {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path} segment {index} has invalid start/end/text") from exc

    def _read_srt_segments(self, path: Path) -> list[TranscriptSegment]:
        subtitles = pysubs2.load(str(path), encoding="utf-8")
        return [
            TranscriptSegment(
                start=line.start / 1000,
                end=line.end / 1000,
                text=line.plaintext.strip(),
            )
            for line in subtitles
            if line.plaintext.strip()
        ]

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _dump_segments(self, segments: list[TranscriptSegment]) -> list[dict[str, object]]:
        return [{"start": segment.start, "end": segment.end, "text": segment.text} for segment in segments]

    def _write_dubbing_plan(
        self,
        path: Path,
        *,
        source_segments: list[TranscriptSegment],
        translated_segments: list[TranscriptSegment],
    ) -> dict[str, object]:
        rewrite_result = self._rewrite_tts_text_segments(translated_segments)
        plan = build_dubbing_plan(source_segments, rewrite_result.segments)
        summary = summarize_dubbing_plan(plan)
        self._write_json(
            path,
            {
                "target_language": "zh",
                "segments": dump_dubbing_plan(plan),
                "summary": summary,
                "tts_rewrite_summary": _tts_rewrite_summary(rewrite_result),
            },
        )
        return {**summary, "tts_rewrite_summary": _tts_rewrite_summary(rewrite_result)}

    def _rewrite_tts_text_segments(
        self,
        segments: list[TranscriptSegment],
    ) -> TtsTextRewriteResult:
        if not _segments_need_tts_rewrite(segments):
            return _local_tts_text_rewrite_result(segments, source="none")

        try:
            return self.tts_text_rewrite_client.rewrite_segments(segments)
        except Exception as exc:
            warning = f"LLM TTS rewrite failed: {_short_text(str(exc), max_length=120)}"
            return _local_tts_text_rewrite_result(
                segments,
                source="local_fallback",
                warnings=(warning,),
            )

    def _aligned_tts_pcm(
        self,
        task_dir: Path,
        segments: list[TranscriptSegment],
        voice_reference: VoiceCloneReference | None = None,
        *,
        tts_plan_source: str = "translation_json",
        rewrite_result: TtsTextRewriteResult | None = None,
    ) -> dict[str, object]:
        sample_rate = self.speech_client.sample_rate
        timeline = bytearray()
        current_time = 0.0
        synthesized_count = 0
        compressed_segments = 0
        trimmed_segments = 0
        silence_trimmed_segments = 0
        silence_trimmed_seconds = 0.0
        duration_fit_warning_count = 0
        strong_compression_warning_count = 0
        compression_ratios: list[float] = []
        warnings: list[str] = []
        tts_groups = group_segments_for_tts(segments)
        incomplete_sentence_group_count = sum(
            1 for group in tts_groups if not tts_text_ends_with_sentence_punctuation(group.text)
        )
        request_text_normalized_count = sum(
            1
            for group in tts_groups
            if _tts_request_text_without_period(group) != _raw_tts_group_text(group, segments)
        )
        english_report = _tts_english_report(tts_groups, segments, rewrite_result)
        warnings.extend(english_report["warnings"])
        if english_report["unresolved_count"]:
            warnings.append(
                "TTS text contains "
                f"{english_report['unresolved_count']} "
                "unresolved English fragments after normalization"
            )
        subtitle_segment_count = len([segment for segment in segments if segment.text.strip()])
        raw_pcm_by_index = self._synthesize_segments_concurrently(tts_groups, voice_reference)

        for index, group in enumerate(tts_groups):
            if group.start > current_time:
                timeline.extend(silence_pcm16(group.start - current_time, sample_rate))
                current_time = group.start

            raw_pcm = raw_pcm_by_index[index]
            trimmed_pcm = trim_pcm16_silence(
                raw_pcm,
                sample_rate,
                threshold=TTS_SILENCE_TRIM_THRESHOLD,
                padding_seconds=TTS_SILENCE_TRIM_PADDING_SECONDS,
            )
            raw_duration = pcm16_duration_seconds(raw_pcm, sample_rate)
            trimmed_duration = pcm16_duration_seconds(trimmed_pcm, sample_rate)
            if trimmed_duration < raw_duration:
                raw_pcm = trimmed_pcm
                silence_trimmed_segments += 1
                silence_trimmed_seconds += raw_duration - trimmed_duration
                warnings.append(
                    f"TTS group {index} silence trimmed from "
                    f"{raw_duration:.3f}s to {trimmed_duration:.3f}s"
                )
            segment_duration = max(0.0, group.end - group.start)
            raw_duration = pcm16_duration_seconds(raw_pcm, sample_rate)
            if raw_duration > segment_duration and segment_duration > 0:
                compression_ratio = raw_duration / segment_duration
                temp_source_path = self._task_dir_path_for_segment(task_dir=task_dir, index=index)
                write_pcm16_wav(temp_source_path, raw_pcm, sample_rate=sample_rate)
                compressed_path = compress_wav_to_duration(temp_source_path, segment_duration)
                aligned_pcm, compressed_rate = read_wav_pcm16(compressed_path)
                if compressed_rate != sample_rate:
                    raise RuntimeError(
                        f"压缩后的配音采样率异常：期望 {sample_rate}，实际 {compressed_rate}"
                    )
                aligned_pcm = trim_pcm16(aligned_pcm, segment_duration, sample_rate)
                if temp_source_path.exists():
                    temp_source_path.unlink()
                if compressed_path.exists():
                    compressed_path.unlink()
                compressed_segments += 1
                compression_ratios.append(compression_ratio)
                warnings.append(
                    f"TTS group {index} compressed from "
                    f"{raw_duration:.3f}s to {segment_duration:.3f}s"
                )
                if compression_ratio >= TTS_COMPRESSION_WARNING_RATIO:
                    duration_fit_warning_count += 1
                    warnings.append(
                        f"TTS group {index} duration fit warning at {compression_ratio:.2f}x"
                    )
                if compression_ratio >= TTS_STRONG_COMPRESSION_RATIO:
                    strong_compression_warning_count += 1
                    warnings.append(
                        f"TTS group {index} strongly compressed at {compression_ratio:.2f}x"
                    )
            else:
                aligned_pcm = trim_pcm16(raw_pcm, segment_duration, sample_rate)
                if raw_duration > segment_duration:
                    trimmed_segments += 1
                    warnings.append(
                        f"TTS group {index} trimmed from "
                        f"{raw_duration:.3f}s to {segment_duration:.3f}s"
                    )
            aligned_duration = pcm16_duration_seconds(aligned_pcm, sample_rate)
            timeline.extend(aligned_pcm)
            current_time += aligned_duration

            if current_time < group.end:
                timeline.extend(silence_pcm16(group.end - current_time, sample_rate))
                current_time = group.end
            else:
                current_time = group.end

            synthesized_count += 1

        grouped_subtitle_segment_count = sum(
            len(group.source_indexes)
            for group in tts_groups
            if len(group.source_indexes) > 1
        )
        if synthesized_count == 0:
            return {
                "pcm": b"",
                "segment_count": 0,
                "subtitle_segment_count": subtitle_segment_count,
                "sentence_group_count": 0,
                "grouped_subtitle_segment_count": 0,
                "sentence_grouped": False,
                "compressed_segments": 0,
                "trimmed_segments": 0,
                "incomplete_sentence_group_count": 0,
                "request_text_normalized_count": 0,
                "silence_trimmed_segments": 0,
                "silence_trimmed_seconds": 0.0,
                "duration_fit_warning_count": 0,
                "max_compression_ratio": 0.0,
                "average_compression_ratio": 0.0,
                "strong_compression_warning_count": 0,
                "english_detected_count": 0,
                "english_rewritten_count": 0,
                "unresolved_english_count": 0,
                "protected_count": 0,
                "rewrite_examples": [],
                "rewrite_source": "none",
                "rewrite_warning_count": 0,
                "plan_source": tts_plan_source,
                "warnings": [],
            }
        return {
            "pcm": bytes(timeline),
            "segment_count": synthesized_count,
            "subtitle_segment_count": subtitle_segment_count,
            "sentence_group_count": len(tts_groups),
            "grouped_subtitle_segment_count": grouped_subtitle_segment_count,
            "sentence_grouped": grouped_subtitle_segment_count > 0,
            "compressed_segments": compressed_segments,
            "trimmed_segments": trimmed_segments,
            "incomplete_sentence_group_count": incomplete_sentence_group_count,
            "request_text_normalized_count": request_text_normalized_count,
            "silence_trimmed_segments": silence_trimmed_segments,
            "silence_trimmed_seconds": round(silence_trimmed_seconds, 3),
            "duration_fit_warning_count": duration_fit_warning_count,
            "max_compression_ratio": round(max(compression_ratios), 3) if compression_ratios else 0.0,
            "average_compression_ratio": (
                round(sum(compression_ratios) / len(compression_ratios), 3) if compression_ratios else 0.0
            ),
            "strong_compression_warning_count": strong_compression_warning_count,
            "english_detected_count": english_report["detected_count"],
            "english_rewritten_count": english_report["rewritten_count"],
            "unresolved_english_count": english_report["unresolved_count"],
            "protected_count": english_report["protected_count"],
            "rewrite_examples": english_report["examples"],
            "rewrite_source": english_report["source"],
            "rewrite_warning_count": english_report["warning_count"],
            "plan_source": tts_plan_source,
            "warnings": warnings,
        }

    def _synthesize_segments_concurrently(
        self,
        groups: list[TtsSentenceGroup],
        voice_reference: VoiceCloneReference | None,
    ) -> dict[int, bytes]:
        if not groups:
            return {}

        max_workers = min(_clamp_tts_concurrency(self.tts_concurrency), len(groups))
        completed_count = 0
        raw_pcm_by_index: dict[int, bytes] = {}
        future_to_group: dict[Future[bytes], tuple[int, TtsSentenceGroup]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for index, group in enumerate(groups):
                future = executor.submit(
                    self._synthesize_segment_pcm,
                    _tts_request_text(group),
                    voice_reference,
                )
                future_to_group[future] = (index, group)

            for future in as_completed(future_to_group):
                index, group = future_to_group[future]
                try:
                    raw_pcm_by_index[index] = future.result()
                except Exception as exc:
                    for other_future in future_to_group:
                        if other_future is not future:
                            other_future.cancel()
                    raise RuntimeError(
                        f"TTS group {index} failed for subtitle indexes "
                        f"{_format_source_indexes(group.source_indexes)} and text "
                        f"'{_short_text(group.text)}': {exc}"
                    ) from exc
                completed_count += 1
                self._notify_tts_progress(completed_count, len(groups))

        return raw_pcm_by_index

    def _synthesize_segment_pcm(
        self,
        text: str,
        voice_reference: VoiceCloneReference | None,
    ) -> bytes:
        if voice_reference is None:
            return self.speech_client.synthesize_pcm16(text)
        return self.speech_client.synthesize_pcm16(text, voice_reference=voice_reference)

    def _notify_tts_progress(self, completed_count: int, total_count: int) -> None:
        if self.progress_callback is None or total_count <= 0:
            return
        progress = min(99, max(10, round(completed_count / total_count * 100)))
        self.progress_callback(progress)

    def _task_dir_path_for_segment(self, task_dir: Path, index: int) -> Path:
        return task_dir / f"tts-segment-{index}.wav"

    def _uses_voice_clone(self) -> bool:
        return bool(getattr(self.speech_client, "is_voice_clone_model", False))

    @staticmethod
    def _configured_tts_concurrency() -> int:
        settings = get_settings()
        saved_settings = _saved_ai_tts_settings()
        for value in (
            saved_settings.get("tts_concurrency", ""),
            saved_settings.get("mimo_tts_concurrency", ""),
            str(settings.tts_concurrency or ""),
            str(settings.mimo_tts_concurrency or ""),
        ):
            parsed = _try_parse_tts_concurrency(value)
            if parsed is not None:
                return parsed
        return TTS_CONCURRENCY_MIN

    def _voice_clone_reference(self, task_dir: Path) -> VoiceCloneReference:
        audio_path = task_dir / "audio.wav"
        if not audio_path.is_file():
            raise RuntimeError(f"音频文件不存在：{audio_path}")

        reference_path = task_dir / "voice_clone_reference.wav"
        source_segments = self._reference_segments(task_dir)
        truncated = self._write_voice_clone_reference(
            source_path=audio_path,
            output_path=reference_path,
            segments=source_segments,
            max_duration_seconds=VOICE_CLONE_REFERENCE_INITIAL_SECONDS,
        )
        reference = build_voice_clone_reference(reference_path, truncated=truncated)
        if reference.base64_size_bytes <= VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES:
            return reference
        return self._shrink_voice_clone_reference(
            source_path=audio_path,
            output_path=reference_path,
            segments=source_segments,
            reference=reference,
        )

    def _reference_segments(self, task_dir: Path) -> list[TranscriptSegment]:
        transcript_path = task_dir / "transcript.json"
        if not transcript_path.is_file():
            return []
        try:
            return self._read_segments(transcript_path)
        except (RuntimeError, ValueError):
            return []

    def _shrink_voice_clone_reference(
        self,
        *,
        source_path: Path,
        output_path: Path,
        segments: list[TranscriptSegment],
        reference: VoiceCloneReference,
    ) -> VoiceCloneReference:
        current_duration = max(reference.duration_seconds, VOICE_CLONE_REFERENCE_MIN_SECONDS)
        for _ in range(8):
            shrink_ratio = VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES / max(reference.base64_size_bytes, 1)
            next_duration = current_duration * shrink_ratio * 0.95
            if next_duration >= current_duration:
                next_duration = current_duration * 0.9
            next_duration = max(VOICE_CLONE_REFERENCE_MIN_SECONDS, next_duration)
            self._write_voice_clone_reference(
                source_path=source_path,
                output_path=output_path,
                segments=segments,
                max_duration_seconds=next_duration,
            )
            reference = build_voice_clone_reference(output_path, truncated=True)
            if reference.base64_size_bytes <= VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES:
                return reference
            current_duration = next_duration

        raise RuntimeError(
            "声音样本 Base64 字符串超过本地上传阈值："
            f"{reference.base64_size_bytes} bytes，限制为 {VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES} bytes。"
        )

    def _write_voice_clone_reference(
        self,
        *,
        source_path: Path,
        output_path: Path,
        segments: list[TranscriptSegment],
        max_duration_seconds: float,
    ) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        max_duration_seconds = max(VOICE_CLONE_REFERENCE_MIN_SECONDS, max_duration_seconds)
        with wave.open(str(source_path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            frame_rate = source.getframerate()
            total_frames = source.getnframes()
            if sample_width != 2:
                raise RuntimeError("声音样本仅支持 PCM16 WAV 音频。")
            max_frames = max(1, round(max_duration_seconds * frame_rate))
            written_frames = 0
            truncated = False

            with wave.open(str(output_path), "wb") as target:
                target.setnchannels(channels)
                target.setsampwidth(sample_width)
                target.setframerate(frame_rate)
                for segment in sorted(segments, key=lambda item: item.start):
                    if written_frames >= max_frames:
                        truncated = True
                        break
                    start_frame = max(0, min(total_frames, round(segment.start * frame_rate)))
                    end_frame = max(start_frame, min(total_frames, round(segment.end * frame_rate)))
                    frame_count = end_frame - start_frame
                    if frame_count <= 0:
                        continue
                    available_frames = max_frames - written_frames
                    read_frames = min(frame_count, available_frames)
                    if read_frames < frame_count:
                        truncated = True
                    source.setpos(start_frame)
                    target.writeframes(source.readframes(read_frames))
                    written_frames += read_frames

                if written_frames == 0:
                    source.setpos(0)
                    read_frames = min(total_frames, max_frames)
                    if read_frames <= 0:
                        raise RuntimeError("原视频音频为空，无法生成 voiceclone 声音样本。")
                    target.writeframes(source.readframes(read_frames))
                    written_frames = read_frames
                    truncated = total_frames > read_frames
                elif self._has_remaining_reference_audio(segments, frame_rate, total_frames, written_frames):
                    truncated = True

        return truncated

    @staticmethod
    def _has_remaining_reference_audio(
        segments: list[TranscriptSegment],
        frame_rate: int,
        total_frames: int,
        written_frames: int,
    ) -> bool:
        total_segment_frames = 0
        for segment in segments:
            start_frame = max(0, min(total_frames, round(segment.start * frame_rate)))
            end_frame = max(start_frame, min(total_frames, round(segment.end * frame_rate)))
            total_segment_frames += end_frame - start_frame
        return total_segment_frames > written_frames

    def _default_translation_client(self) -> TranslationClient:
        from backend.app.runner.llm import OpenAITranslationClient

        return OpenAITranslationClient()

    def _default_metadata_client(self) -> MetadataClient:
        from backend.app.runner.llm import OpenAIMetadataClient

        return OpenAIMetadataClient()

    def _default_tts_text_rewrite_client(self) -> TtsTextRewriteClient:
        from backend.app.runner.llm import OpenAITtsPhoneticRewriteClient

        return OpenAITtsPhoneticRewriteClient()

    def _default_speech_client(self) -> SpeechSynthesisClient:
        return default_speech_client()


def _saved_ai_tts_settings() -> dict[str, str]:
    from backend.app.database import SessionLocal
    from backend.app.repositories import TaskRepository

    session = SessionLocal()
    try:
        return TaskRepository(session).get_app_settings(("tts_concurrency", "mimo_tts_concurrency"))
    finally:
        session.close()


def _parse_tts_concurrency(value: str, default: int) -> int:
    parsed = _try_parse_tts_concurrency(value)
    if parsed is not None:
        return parsed
    parsed_default = _try_parse_tts_concurrency(str(default))
    if parsed_default is not None:
        return parsed_default
    return TTS_CONCURRENCY_MIN


def _try_parse_tts_concurrency(value: str) -> int | None:
    try:
        concurrency = int(value)
    except (TypeError, ValueError):
        return None
    if concurrency < TTS_CONCURRENCY_MIN or concurrency > TTS_CONCURRENCY_MAX:
        return None
    return _clamp_tts_concurrency(concurrency)


def _clamp_tts_concurrency(value: int) -> int:
    return max(TTS_CONCURRENCY_MIN, min(TTS_CONCURRENCY_MAX, value))


def _short_text(text: str, max_length: int = 40) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length]}..."


def _format_source_indexes(indexes: tuple[int, ...]) -> str:
    if not indexes:
        return "[]"
    if len(indexes) == 1:
        return f"[{indexes[0]}]"
    return f"[{indexes[0]}..{indexes[-1]}]"


def _raw_tts_group_text(group: TtsSentenceGroup, segments: list[TranscriptSegment]) -> str:
    return " ".join(
        segments[index].text.strip()
        for index in group.source_indexes
        if segments[index].text.strip()
    )


def _tts_request_text_without_period(group: TtsSentenceGroup) -> str:
    if group.tts_text:
        return " ".join(group.tts_text.split())
    return normalize_tts_request_text(group.text)


def _tts_request_text(group: TtsSentenceGroup) -> str:
    text = _tts_request_text_without_period(group)
    if text and not tts_text_ends_with_sentence_punctuation(text):
        return f"{text}。"
    return text


def _tts_english_report(
    groups: list[TtsSentenceGroup],
    segments: list[TranscriptSegment],
    rewrite_result: TtsTextRewriteResult | None = None,
) -> dict[str, object]:
    if rewrite_result is not None:
        return {
            "detected_count": rewrite_result.detected_count,
            "rewritten_count": rewrite_result.rewritten_count,
            "unresolved_count": rewrite_result.unresolved_count,
            "protected_count": rewrite_result.protected_count,
            "warning_count": rewrite_result.warning_count,
            "source": rewrite_result.source,
            "warnings": list(rewrite_result.warnings),
            "examples": [
                {
                    "original": example.original,
                    "replacement": example.replacement,
                    "resolved": example.resolved,
                }
                for example in rewrite_result.rewrite_examples
            ],
        }

    detected_count = 0
    rewritten_count = 0
    unresolved_count = 0
    protected_count = 0
    examples: list[TtsTextRewriteExample] = []
    for group in groups:
        report = normalize_tts_request_text_with_report(
            _raw_tts_group_text(group, segments) or group.text
        )
        detected_count += report.detected_count
        rewritten_count += report.rewritten_count
        unresolved_count += report.unresolved_count
        protected_count += report.protected_count
        for example in report.rewrite_examples:
            if example not in examples:
                examples.append(example)
            if len(examples) >= 5:
                break
    return {
        "detected_count": detected_count,
        "rewritten_count": rewritten_count,
        "unresolved_count": unresolved_count,
        "protected_count": protected_count,
        "warning_count": unresolved_count,
        "source": "local",
        "warnings": [],
        "examples": [
            {
                "original": example.original,
                "replacement": example.replacement,
                "resolved": example.resolved,
            }
            for example in examples
        ],
    }


def _segments_need_tts_rewrite(segments: list[TranscriptSegment]) -> bool:
    return any(
        segment.tts_text is None and find_unprotected_english_fragments(segment.text)
        for segment in segments
    )


def _tts_segment_base_text(segment: TranscriptSegment) -> str:
    return segment.tts_text if segment.tts_text is not None else segment.text


def _local_tts_text_rewrite_result(
    segments: list[TranscriptSegment],
    *,
    source: str,
    warnings: tuple[str, ...] = (),
) -> TtsTextRewriteResult:
    rewritten_segments: list[TranscriptSegment] = []
    detected_count = 0
    rewritten_count = 0
    unresolved_count = 0
    protected_count = 0
    examples: list[TtsTextRewriteExample] = []

    for segment in segments:
        if segment.tts_text is not None:
            text = " ".join(segment.tts_text.split())
            report = _existing_tts_text_report(text)
        else:
            report = normalize_tts_request_text_with_report(segment.text)
            text = report.text
        rewritten_segments.append(
            TranscriptSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text,
                tts_text=text,
            )
        )
        detected_count += report.detected_count
        rewritten_count += report.rewritten_count
        unresolved_count += report.unresolved_count
        protected_count += report.protected_count
        for example in report.rewrite_examples:
            if example not in examples:
                examples.append(example)
            if len(examples) >= 5:
                break

    warning_count = unresolved_count + len(warnings)
    return TtsTextRewriteResult(
        segments=rewritten_segments,
        source=source,
        detected_count=detected_count,
        rewritten_count=rewritten_count,
        unresolved_count=unresolved_count,
        protected_count=protected_count,
        warning_count=warning_count,
        rewrite_examples=tuple(examples),
        warnings=warnings,
    )


def _existing_tts_text_report(text: str) -> object:
    protected_count = protected_tts_fragment_count(text)
    unresolved_fragments = find_unprotected_english_fragments(text)
    examples = tuple(
        TtsTextRewriteExample(
            original=fragment,
            replacement=fragment,
            resolved=False,
        )
        for fragment in unresolved_fragments[:5]
    )
    return TtsTextRewriteResult(
        segments=[],
        source="existing",
        detected_count=protected_count + len(unresolved_fragments),
        rewritten_count=0,
        unresolved_count=len(unresolved_fragments),
        protected_count=protected_count,
        warning_count=len(unresolved_fragments),
        rewrite_examples=examples,
    )


def _tts_rewrite_summary(result: TtsTextRewriteResult) -> dict[str, object]:
    return {
        "source": result.source,
        "detected_count": result.detected_count,
        "rewritten_count": result.rewritten_count,
        "unresolved_count": result.unresolved_count,
        "protected_count": result.protected_count,
        "warning_count": result.warning_count,
        "rewrite_examples": [
            {
                "original": example.original,
                "replacement": example.replacement,
                "resolved": example.resolved,
            }
            for example in result.rewrite_examples
        ],
        "warnings": list(result.warnings),
    }
