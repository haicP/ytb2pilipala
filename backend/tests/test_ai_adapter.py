import json
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

from backend.app.domain import SourceType
from backend.app.repositories import TaskRepository
from backend.app.runner.ai_adapter import (
    AiWorkflowAdapter,
    FasterWhisperTranscriber,
    MetadataResult,
    TranscriptionResult,
    TtsTextRewriteResult,
    _parse_tts_concurrency,
)
from backend.app.runner.subtitles import (
    TranscriptSegment,
    TtsTextRewriteExample,
    normalize_tts_request_text_with_report,
)
from backend.app.runner.tts import (
    VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES,
    SpeechSynthesisClient,
)


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio_path):
        self.calls.append(audio_path)
        return TranscriptionResult(
            segments=[TranscriptSegment(start=0.0, end=1.5, text="Hello world")],
            detected_source_language="en",
        )


class FakeTranslationClient:
    def __init__(self):
        self.calls = []

    def translate_segments(self, segments, target_language="zh"):
        self.calls.append((segments, target_language))
        return [
            TranscriptSegment(start=segment.start, end=segment.end, text="你好，世界")
            for segment in segments
        ]


class FakeMetadataClient:
    def __init__(self):
        self.calls = []

    def generate_metadata(self, task, transcript_segments, translated_segments):
        self.calls.append((task, transcript_segments, translated_segments))
        return MetadataResult(
            title="【中文配音】Hello world",
            description="中文简介",
            tags=["YouTube", "中文配音"],
            category="科技",
        )


class FakeTtsTextRewriteClient:
    def __init__(self, replacements: dict[str, str] | None = None, fail: bool = False):
        self.replacements = replacements or {}
        self.fail = fail
        self.calls = []

    def rewrite_segments(self, segments):
        self.calls.append(segments)
        if self.fail:
            raise RuntimeError("rewrite unavailable")

        rewritten_segments = []
        examples = []
        detected_count = 0
        rewritten_count = 0
        unresolved_count = 0
        protected_count = 0
        warnings = []
        for index, segment in enumerate(segments):
            text = segment.tts_text if segment.tts_text is not None else segment.text
            fallback_tts_text = normalize_tts_request_text_with_report(text).text
            tts_text = self.replacements.get(text, fallback_tts_text)
            report = normalize_tts_request_text_with_report(text)
            unresolved = normalize_tts_request_text_with_report(tts_text).unresolved_count
            detected_count += report.detected_count
            protected_count += report.protected_count
            unresolved_count += unresolved
            if unresolved:
                warnings.append(f"LLM TTS rewrite left English fragments in segment {index}")
            for example in report.rewrite_examples:
                replacement = self._replacement_for_example(example.original, example.replacement)
                resolved = replacement != example.original
                if resolved:
                    rewritten_count += 1
                if len(examples) < 5:
                    examples.append(
                        TtsTextRewriteExample(
                            original=example.original,
                            replacement=replacement,
                            resolved=resolved,
                        )
                    )
            rewritten_segments.append(
                TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                    tts_text=tts_text,
                )
            )
        return TtsTextRewriteResult(
            segments=rewritten_segments,
            source="llm_phonetic",
            detected_count=detected_count,
            rewritten_count=rewritten_count,
            unresolved_count=unresolved_count,
            protected_count=protected_count,
            warning_count=unresolved_count,
            rewrite_examples=tuple(examples),
            warnings=tuple(warnings),
        )

    def _replacement_for_example(self, original, fallback):
        for source, replacement in self.replacements.items():
            if original in source and original not in replacement:
                return replacement
        return fallback


class FakeSpeechSynthesisClient(SpeechSynthesisClient):
    sample_rate = 24000
    is_voice_clone_model = False
    tts_provider = "mimo_v2_5_tts"

    def __init__(self):
        self.calls = []

    def synthesize_pcm16(self, text: str, voice_reference=None) -> bytes:
        self.calls.append((text, voice_reference))
        return bytes.fromhex("0000010002000300")


class FakeVoiceCloneSpeechClient(FakeSpeechSynthesisClient):
    is_voice_clone_model = True


class FakeOpenAISpeechSynthesisClient(FakeSpeechSynthesisClient):
    tts_provider = "openai"


class BlockingSpeechSynthesisClient(FakeSpeechSynthesisClient):
    def __init__(self, release_event: threading.Event):
        super().__init__()
        self.release_event = release_event
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def synthesize_pcm16(self, text: str, voice_reference=None) -> bytes:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.calls.append((text, voice_reference))
            self.release_event.wait(timeout=3)
            return bytes.fromhex("0000010002000300")
        finally:
            with self.lock:
                self.active -= 1


class FailingSpeechSynthesisClient(FakeSpeechSynthesisClient):
    def synthesize_pcm16(self, text: str, voice_reference=None) -> bytes:
        self.calls.append((text, voice_reference))
        if "失败" in text:
            raise RuntimeError("TTS service unavailable")
        time.sleep(0.05)
        return super().synthesize_pcm16(text, voice_reference)


def _write_translation(task_dir: Path, segments: list[dict[str, object]]) -> None:
    (task_dir / "translation.json").write_text(
        json.dumps(
            {
                "target_language": "zh",
                "segments": segments,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _ai_adapter(
    tmp_path: Path,
    speech_client: SpeechSynthesisClient,
    **kwargs,
) -> AiWorkflowAdapter:
    return AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
        tts_text_rewrite_client=kwargs.pop("tts_text_rewrite_client", FakeTtsTextRewriteClient()),
        speech_client=speech_client,
        **kwargs,
    )


def test_faster_whisper_transcriber_uses_configured_hf_cache(monkeypatch, tmp_path):
    hf_cache = tmp_path / "huggingface" / "hub"

    class FakeWhisperModel:
        def __init__(self, model_size, compute_type, download_root):
            self.model_size = model_size
            self.compute_type = compute_type
            self.download_root = download_root

    monkeypatch.setattr(
        "backend.app.runner.ai_adapter.get_settings",
        lambda: SimpleNamespace(hf_hub_cache=str(hf_cache)),
    )

    transcriber = FasterWhisperTranscriber(model_size="small", compute_type="int8")
    import sys

    fake_module = SimpleNamespace(WhisperModel=FakeWhisperModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    model = transcriber._whisper_model()

    assert model.model_size == "small"
    assert model.compute_type == "int8"
    assert model.download_root == str(hf_cache)


def test_parse_tts_concurrency_falls_back_to_default_when_invalid():
    assert _parse_tts_concurrency("", 10) == 10
    assert _parse_tts_concurrency("8", 10) == 8
    assert _parse_tts_concurrency("0", 10) == 10
    assert _parse_tts_concurrency("51", 10) == 10
    assert _parse_tts_concurrency("bad", 10) == 10


def test_configured_tts_concurrency_prefers_saved_value_and_falls_back(monkeypatch):
    monkeypatch.setattr(
        "backend.app.runner.ai_adapter.get_settings",
        lambda: SimpleNamespace(tts_concurrency=7, mimo_tts_concurrency=6),
    )
    monkeypatch.setattr(
        "backend.app.runner.ai_adapter._saved_ai_tts_settings",
        lambda: {"tts_concurrency": "12", "mimo_tts_concurrency": "11"},
    )

    assert AiWorkflowAdapter._configured_tts_concurrency() == 12

    monkeypatch.setattr(
        "backend.app.runner.ai_adapter._saved_ai_tts_settings",
        lambda: {"tts_concurrency": "bad", "mimo_tts_concurrency": "11"},
    )

    assert AiWorkflowAdapter._configured_tts_concurrency() == 11

    monkeypatch.setattr(
        "backend.app.runner.ai_adapter._saved_ai_tts_settings",
        lambda: {"tts_concurrency": "bad", "mimo_tts_concurrency": "bad"},
    )

    assert AiWorkflowAdapter._configured_tts_concurrency() == 7


def test_transcribe_calls_whisper_without_source_subtitle_and_writes_artifacts(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    (task_dir / "audio.wav").write_bytes(b"audio")
    transcriber = FakeTranscriber()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=transcriber,
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "transcribe")

    assert result.success is True
    assert transcriber.calls == [task_dir / "audio.wav"]
    assert (task_dir / "source.srt").read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,500\nHello world\n\n"
    )
    transcript = json.loads((task_dir / "transcript.json").read_text(encoding="utf-8"))
    assert transcript["detected_source_language"] == "en"
    assert transcript["segments"] == [{"start": 0.0, "end": 1.5, "text": "Hello world"}]
    assert ("subtitle_source", str(task_dir / "source.srt")) in result.artifacts
    assert ("transcript", str(task_dir / "transcript.json")) in result.artifacts
    assert result.metadata["detected_source_language"] == "en"


def test_translate_reuses_local_simplified_chinese_subtitle_without_llm(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    (task_dir / "transcript.json").write_text(
        json.dumps(
            {
                "detected_source_language": "en",
                "segments": [{"start": 0.0, "end": 1.5, "text": "Hello world"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (task_dir / "demo.zh-Hans.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,500\n本地中文字幕\n\n",
        encoding="utf-8",
    )
    translation_client = FakeTranslationClient()
    metadata_client = FakeMetadataClient()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=translation_client,
        metadata_client=metadata_client,
    )

    result = adapter.execute(task, "translate")

    assert result.success is True
    assert translation_client.calls == []
    assert (task_dir / "zh.srt").read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,500\n本地中文字幕\n\n"
    )
    translation = json.loads((task_dir / "translation.json").read_text(encoding="utf-8"))
    assert translation["target_language"] == "zh"
    assert translation["source"] == "local_zh_reuse"
    assert translation["dubbing_plan_path"] == str(task_dir / "dubbing_plan.json")
    assert translation["duration_fit_summary"]["segment_count"] == 1
    assert translation["segments"] == [{"start": 0.0, "end": 1.5, "text": "本地中文字幕"}]
    dubbing_plan = json.loads((task_dir / "dubbing_plan.json").read_text(encoding="utf-8"))
    assert dubbing_plan["segments"] == [
        {
            "id": 0,
            "source_indexes": [0],
            "start": 0.0,
            "end": 1.5,
            "duration": 1.5,
            "source_text": "Hello world",
            "zh_text": "本地中文字幕",
            "tts_text": "本地中文字幕",
            "estimated_cps": 4.0,
            "fit_level": "ok",
        }
    ]
    assert result.artifacts == [
        ("subtitle_translated", str(task_dir / "zh.srt")),
        ("translation", str(task_dir / "translation.json")),
        ("dubbing_plan", str(task_dir / "dubbing_plan.json")),
    ]
    assert result.metadata["translation_mode"] == "local_zh_reuse"
    assert result.metadata["dubbing_plan_segment_count"] == 1

    metadata_result = adapter.execute(task, "generate_metadata")

    assert metadata_result.success is True
    assert metadata_client.calls == [
        (
            task,
            [TranscriptSegment(start=0.0, end=1.5, text="Hello world")],
            [TranscriptSegment(start=0.0, end=1.5, text="本地中文字幕")],
        )
    ]


def test_translate_uses_llm_when_local_simplified_chinese_subtitle_is_missing(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    (task_dir / "transcript.json").write_text(
        json.dumps(
            {
                "detected_source_language": "en",
                "segments": [{"start": 0.0, "end": 1.5, "text": "Hello world"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    translation_client = FakeTranslationClient()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=translation_client,
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "translate")

    assert result.success is True
    assert translation_client.calls == [([TranscriptSegment(start=0.0, end=1.5, text="Hello world")], "zh")]
    assert (task_dir / "zh.srt").read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,500\n你好，世界\n\n"
    )
    translation = json.loads((task_dir / "translation.json").read_text(encoding="utf-8"))
    assert translation["target_language"] == "zh"
    assert translation["dubbing_plan_path"] == str(task_dir / "dubbing_plan.json")
    assert translation["segments"] == [{"start": 0.0, "end": 1.5, "text": "你好，世界"}]
    assert ("subtitle_translated", str(task_dir / "zh.srt")) in result.artifacts
    assert ("translation", str(task_dir / "translation.json")) in result.artifacts
    assert ("dubbing_plan", str(task_dir / "dubbing_plan.json")) in result.artifacts
    assert result.metadata["translation_mode"] == "llm"


def test_translate_merges_incomplete_source_segments_before_llm(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-merge")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    (task_dir / "transcript.json").write_text(
        json.dumps(
            {
                "detected_source_language": "en",
                "segments": [
                    {
                        "start": 20.92,
                        "end": 24.64,
                        "text": "I'm going to show you it reading and replying to real emails, building",
                    },
                    {
                        "start": 24.64,
                        "end": 28.12,
                        "text": "a real website from scratch, running daily automated tasks on a timer",
                    },
                    {
                        "start": 28.16,
                        "end": 33.04,
                        "text": "and controlling my computer live, clicking, browsing, typing, completely on its own.",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    translation_client = FakeTranslationClient()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=translation_client,
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "translate")

    merged_source = [
        TranscriptSegment(
            start=20.92,
            end=33.04,
            text=(
                "I'm going to show you it reading and replying to real emails, building "
                "a real website from scratch, running daily automated tasks on a timer "
                "and controlling my computer live, clicking, browsing, typing, completely on its own."
            ),
        )
    ]
    assert translation_client.calls == [(merged_source, "zh")]
    translation = json.loads((task_dir / "translation.json").read_text(encoding="utf-8"))
    assert translation["source_segment_count"] == 3
    assert translation["translation_segment_count"] == 1
    assert translation["merged_segment_count"] == 2
    assert translation["segments_merged"] is True
    assert translation["segments"] == [
        {"start": 20.92, "end": 33.04, "text": "你好，世界"}
    ]
    dubbing_plan = json.loads((task_dir / "dubbing_plan.json").read_text(encoding="utf-8"))
    assert dubbing_plan["segments"][0]["source_indexes"] == [0, 1, 2]
    assert dubbing_plan["segments"][0]["source_text"] == (
        "I'm going to show you it reading and replying to real emails, building "
        "a real website from scratch, running daily automated tasks on a timer "
        "and controlling my computer live, clicking, browsing, typing, completely on its own."
    )
    assert (task_dir / "zh.srt").read_text(encoding="utf-8") == (
        "1\n00:00:20,920 --> 00:00:33,040\n你好，世界\n\n"
    )
    assert result.metadata["segments_merged"] is True


def test_generate_metadata_returns_submission_metadata_payload(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    (task_dir / "transcript.json").write_text(
        json.dumps(
            {
                "detected_source_language": "en",
                "segments": [{"start": 0.0, "end": 1.5, "text": "Hello world"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (task_dir / "translation.json").write_text(
        json.dumps(
            {
                "target_language": "zh",
                "segments": [{"start": 0.0, "end": 1.5, "text": "你好，世界"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    metadata_client = FakeMetadataClient()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=metadata_client,
    )

    result = adapter.execute(task, "generate_metadata")

    assert result.success is True
    assert metadata_client.calls == [
        (
            task,
            [TranscriptSegment(start=0.0, end=1.5, text="Hello world")],
            [TranscriptSegment(start=0.0, end=1.5, text="你好，世界")],
        )
    ]
    assert result.metadata["submission_metadata"] == {
        "title": "【中文配音】Hello world",
        "description": "中文简介",
        "tags": ["YouTube", "中文配音"],
        "category": "科技",
    }


def test_synthesize_voice_calls_tts_and_writes_voice_artifact(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(
        task_dir,
        [
            {"start": 0.0, "end": 1.5, "text": "第一句中文字幕。"},
            {"start": 1.5, "end": 3.0, "text": "第二句中文字幕。"},
        ],
    )
    speech_client = FakeSpeechSynthesisClient()
    adapter = _ai_adapter(tmp_path, speech_client)

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert [call[0] for call in speech_client.calls] == ["第一句中文字幕。", "第二句中文字幕。"]
    assert result.artifacts == [("voiceover", str(task_dir / "zh_voice.wav"))]
    assert result.metadata["tts_provider"] == "mimo_v2_5_tts"
    assert result.metadata["tts_plan_source"] == "translation_json"
    assert result.metadata["tts_segment_count"] == 2
    assert result.metadata["tts_subtitle_segment_count"] == 2
    assert result.metadata["tts_sentence_group_count"] == 2
    assert result.metadata["tts_grouped_subtitle_segment_count"] == 0
    assert result.metadata["tts_sentence_grouped"] is False
    assert result.metadata["tts_timeline_aligned"] is True
    assert result.metadata["tts_duration_fit_warning_count"] == 0
    assert result.metadata["tts_max_compression_ratio"] == 0.0
    assert result.metadata["tts_average_compression_ratio"] == 0.0
    with wave.open(str(task_dir / "zh_voice.wav"), "rb") as handle:
        assert handle.getframerate() == 24000
        assert handle.getnframes() == 72_000


def test_synthesize_voice_reports_openai_provider_without_voiceclone(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-openai")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(task_dir, [{"start": 0.0, "end": 1.5, "text": "第一句中文字幕。"}])
    speech_client = FakeOpenAISpeechSynthesisClient()
    adapter = _ai_adapter(tmp_path, speech_client)

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert result.artifacts == [("voiceover", str(task_dir / "zh_voice.wav"))]
    assert result.metadata["tts_provider"] == "openai"
    assert "tts_voice_clone_reference_path" not in result.metadata
    assert speech_client.calls == [("第一句中文字幕。", None)]


def test_synthesize_voice_prefers_dubbing_plan_over_translation_json(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-dubbing-plan")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(task_dir, [{"start": 0.0, "end": 1.0, "text": "旧译文。"}])
    (task_dir / "dubbing_plan.json").write_text(
        json.dumps(
            {
                "target_language": "zh",
                "segments": [
                    {
                        "id": 0,
                        "source_indexes": [0],
                        "start": 0.0,
                        "end": 1.0,
                        "duration": 1.0,
                        "source_text": "New text.",
                        "zh_text": "配音计划文本。",
                        "tts_text": "实际发给配音的文本。",
                        "estimated_cps": 7.0,
                        "fit_level": "ok",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    speech_client = FakeSpeechSynthesisClient()
    adapter = _ai_adapter(tmp_path, speech_client)

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert [call[0] for call in speech_client.calls] == ["实际发给配音的文本。"]
    assert result.metadata["tts_plan_source"] == "dubbing_plan"


def test_synthesize_voice_groups_split_subtitle_sentence_for_tts(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-sentence-group")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(
        task_dir,
        [
            {"start": 20.92, "end": 24.64, "text": "我会给你演示它如何阅读并回复真实邮件，构建"},
            {"start": 24.64, "end": 28.12, "text": "一个从零开始的真实网站，按计时器运行每日自动任务，"},
            {"start": 28.16, "end": 33.04, "text": "以及实时控制我的电脑，点击、浏览、打字，完全自主完成。"},
        ],
    )
    speech_client = FakeSpeechSynthesisClient()
    adapter = _ai_adapter(tmp_path, speech_client)

    result = adapter.execute(task, "synthesize_voice")

    assert [call[0] for call in speech_client.calls] == [
        (
            "我会给你演示它如何阅读并回复真实邮件，构建"
            "一个从零开始的真实网站，按计时器运行每日自动任务，"
            "以及实时控制我的电脑，点击、浏览、打字，完全自主完成。"
        )
    ]
    assert result.metadata["tts_segment_count"] == 1
    assert result.metadata["tts_subtitle_segment_count"] == 3
    assert result.metadata["tts_sentence_group_count"] == 1
    assert result.metadata["tts_grouped_subtitle_segment_count"] == 3
    assert result.metadata["tts_sentence_grouped"] is True
    with wave.open(str(task_dir / "zh_voice.wav"), "rb") as handle:
        assert handle.getframerate() == 24000
        assert handle.getnframes() == 792_960


def test_synthesize_voice_groups_reused_local_chinese_subtitle(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-reused-subtitle-tts")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    (task_dir / "transcript.json").write_text(
        json.dumps(
            {
                "detected_source_language": "en",
                "segments": [{"start": 0.0, "end": 3.0, "text": "source text"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (task_dir / "demo.zh-Hans.srt").write_text(
        (
            "1\n00:00:00,000 --> 00:00:01,000\n我会演示它如何构建\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\n一个真实网站，\n\n"
            "3\n00:00:02,000 --> 00:00:03,000\n并自动运行任务。\n\n"
        ),
        encoding="utf-8",
    )
    speech_client = FakeSpeechSynthesisClient()
    adapter = _ai_adapter(tmp_path, speech_client)

    translate_result = adapter.execute(task, "translate")
    synthesize_result = adapter.execute(task, "synthesize_voice")

    assert translate_result.metadata["translation_mode"] == "local_zh_reuse"
    assert [call[0] for call in speech_client.calls] == [
        "我会演示它如何构建一个真实网站，并自动运行任务。"
    ]
    assert synthesize_result.metadata["tts_plan_source"] == "dubbing_plan"
    assert synthesize_result.metadata["tts_segment_count"] == 1
    assert synthesize_result.metadata["tts_subtitle_segment_count"] == 1
    assert synthesize_result.metadata["tts_sentence_grouped"] is False


def test_synthesize_voice_calls_tts_concurrently_and_keeps_timeline_order(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-concurrent")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(
        task_dir,
        [
            {"start": 0.0, "end": 1.0, "text": "第一句。"},
            {"start": 1.0, "end": 2.0, "text": "第二句。"},
            {"start": 2.0, "end": 3.0, "text": "第三句。"},
        ],
    )
    release_event = threading.Event()
    speech_client = BlockingSpeechSynthesisClient(release_event)
    progress_updates: list[int] = []
    adapter = _ai_adapter(
        tmp_path,
        speech_client,
        tts_concurrency=2,
        progress_callback=progress_updates.append,
    )

    result_holder = {}

    def run_adapter():
        result_holder["result"] = adapter.execute(task, "synthesize_voice")

    worker = threading.Thread(target=run_adapter)
    worker.start()
    try:
        deadline = time.monotonic() + 2
        while speech_client.max_active < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert speech_client.max_active == 2
        release_event.set()
        worker.join(timeout=3)
    finally:
        release_event.set()
        worker.join(timeout=3)

    assert result_holder["result"].success is True
    assert len(speech_client.calls) == 3
    assert progress_updates[-1] == 99
    with wave.open(str(task_dir / "zh_voice.wav"), "rb") as handle:
        assert handle.getframerate() == 24000
        assert handle.getnframes() == 72_000


def test_synthesize_voice_failure_reports_segment_and_does_not_write_voice_artifact(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-fail")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(
        task_dir,
        [
            {"start": 0.0, "end": 1.0, "text": "正常片段"},
            {"start": 1.0, "end": 2.0, "text": "失败片段。"},
        ],
    )
    speech_client = FailingSpeechSynthesisClient()
    adapter = _ai_adapter(tmp_path, speech_client, tts_concurrency=2)

    try:
        adapter.execute(task, "synthesize_voice")
    except RuntimeError as exc:
        assert "TTS group 0 failed" in str(exc)
        assert "[0..1]" in str(exc)
        assert "失败片段" in str(exc)
        assert "TTS service unavailable" in str(exc)
    else:
        raise AssertionError("expected synthesize_voice to fail")

    assert not (task_dir / "zh_voice.wav").exists()


def test_synthesize_voice_inserts_silence_to_match_subtitle_timeline(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    (task_dir / "translation.json").write_text(
        json.dumps(
            {
                "target_language": "zh",
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "第一句"},
                    {"start": 2.0, "end": 3.0, "text": "第二句"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    speech_client = FakeSpeechSynthesisClient()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
        speech_client=speech_client,
    )

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert len(speech_client.calls) == 2
    assert [call[0] for call in speech_client.calls] == ["第一句。", "第二句。"]
    with wave.open(str(task_dir / "zh_voice.wav"), "rb") as handle:
        assert handle.getframerate() == 24000
        assert handle.getnframes() == 72_000
        pcm = handle.readframes(handle.getnframes())
    first_segment_bytes = 4 * 2
    gap_start = first_segment_bytes
    gap_length = 24_000 * 2 - first_segment_bytes
    middle_gap = pcm[gap_start : gap_start + gap_length]
    assert middle_gap == b"\x00" * gap_length


def test_synthesize_voice_appends_period_for_incomplete_tts_group(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-incomplete-tts")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(
        task_dir,
        [
            {"start": 0.0, "end": 1.0, "text": "比如 openclaw 或者 Hermes，你实际上可以让"},
            {"start": 2.0, "end": 3.0, "text": "另一句。"},
        ],
    )
    speech_client = FakeSpeechSynthesisClient()
    adapter = _ai_adapter(tmp_path, speech_client)

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert [call[0] for call in speech_client.calls] == [
        "比如欧喷克劳或者赫尔墨斯，你实际上可以让。",
        "另一句。",
    ]
    assert result.metadata["tts_incomplete_sentence_group_count"] == 1


def test_synthesize_voice_rewrites_english_for_legacy_translation_json(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-legacy-english")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(
        task_dir,
        [
            {"start": 0.0, "end": 2.0, "text": "使用 OpenAI API 生成 SRT。"},
            {"start": 2.0, "end": 3.0, "text": "打开 Flux。"},
        ],
    )
    speech_client = FakeSpeechSynthesisClient()
    rewrite_client = FakeTtsTextRewriteClient(
        {
            "使用 OpenAI API 生成 SRT。": "使用欧喷诶艾诶屁艾生成艾丝阿提。",
            "打开 Flux。": "打开福拉克斯。",
        }
    )
    adapter = _ai_adapter(tmp_path, speech_client, tts_text_rewrite_client=rewrite_client)

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert [call[0] for call in speech_client.calls] == [
        "使用欧喷诶艾诶屁艾生成艾丝阿提。",
        "打开福拉克斯。",
    ]
    assert rewrite_client.calls == [
        [
            TranscriptSegment(start=0.0, end=2.0, text="使用 OpenAI API 生成 SRT。"),
            TranscriptSegment(start=2.0, end=3.0, text="打开 Flux。"),
        ]
    ]
    assert result.metadata["tts_english_detected_count"] == 4
    assert result.metadata["tts_english_rewritten_count"] == 4
    assert result.metadata["tts_unresolved_english_count"] == 0
    assert result.metadata["tts_rewrite_source"] == "llm_phonetic"
    assert result.metadata["tts_rewrite_examples"][:3] == [
        {"original": "OpenAI", "replacement": "使用欧喷诶艾诶屁艾生成艾丝阿提。", "resolved": True},
        {"original": "API", "replacement": "使用欧喷诶艾诶屁艾生成艾丝阿提。", "resolved": True},
        {"original": "SRT", "replacement": "使用欧喷诶艾诶屁艾生成艾丝阿提。", "resolved": True},
    ]
    assert result.metadata["tts_alignment_warnings"] == []


def test_synthesize_voice_allows_llm_residual_english_after_rewrite(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-residual-english")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(
        task_dir,
        [{"start": 0.0, "end": 1.0, "text": "打开 Flux。"}],
    )
    speech_client = FakeSpeechSynthesisClient()
    rewrite_client = FakeTtsTextRewriteClient({"打开 Flux。": "打开 Flux。"})
    adapter = _ai_adapter(tmp_path, speech_client, tts_text_rewrite_client=rewrite_client)

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert [call[0] for call in speech_client.calls] == ["打开 Flux。"]
    assert result.metadata["tts_unresolved_english_count"] == 1
    assert result.metadata["tts_rewrite_warning_count"] == 1
    assert any(
        "unresolved English fragments" in warning
        for warning in result.metadata["tts_alignment_warnings"]
    )


def test_synthesize_voice_trims_returned_silence_before_alignment(db_session, tmp_path):
    class SilentPaddingSpeechClient(FakeSpeechSynthesisClient):
        def synthesize_pcm16(self, text: str, voice_reference=None) -> bytes:
            self.calls.append((text, voice_reference))
            leading = b"\x00\x00" * 12_000
            speech = bytes.fromhex("1027") * 12_000
            trailing = b"\x00\x00" * 12_000
            return leading + speech + trailing

    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-trim-silence")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    _write_translation(task_dir, [{"start": 0.0, "end": 1.0, "text": "带静音片段。"}])
    speech_client = SilentPaddingSpeechClient()
    adapter = _ai_adapter(tmp_path, speech_client)

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert result.metadata["tts_silence_trimmed_segments"] == 1
    assert result.metadata["tts_silence_trimmed_seconds"] == 0.84
    assert result.metadata["tts_segments_compressed"] == 0
    with wave.open(str(task_dir / "zh_voice.wav"), "rb") as handle:
        assert handle.getframerate() == 24000
        assert handle.getnframes() == 24_000


def test_synthesize_voice_compresses_segment_when_tts_audio_exceeds_subtitle_duration(db_session, tmp_path):
    class LongSpeechClient(FakeSpeechSynthesisClient):
        def synthesize_pcm16(self, text: str, voice_reference=None) -> bytes:
            self.calls.append((text, voice_reference))
            # 1.5s PCM16 mono @24kHz
            return bytes.fromhex("0100") * 36_000

    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    (task_dir / "translation.json").write_text(
        json.dumps(
            {
                "target_language": "zh",
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "超长片段"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    speech_client = LongSpeechClient()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
        speech_client=speech_client,
    )

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert [call[0] for call in speech_client.calls] == ["超长片段。"]
    with wave.open(str(task_dir / "zh_voice.wav"), "rb") as handle:
        assert handle.getframerate() == 24000
        assert handle.getnframes() == 24_000
    assert result.metadata["tts_segment_count"] == 1
    assert result.metadata["tts_timeline_aligned"] is True
    assert result.metadata["tts_segments_compressed"] == 1
    assert result.metadata["tts_segments_trimmed"] == 0
    assert result.metadata["tts_duration_fit_warning_count"] == 1
    assert result.metadata["tts_max_compression_ratio"] == 1.5
    assert result.metadata["tts_average_compression_ratio"] == 1.5
    assert result.metadata["tts_strong_compression_warning_count"] == 0
    assert result.metadata["tts_alignment_warnings"] == [
        "TTS group 0 compressed from 1.500s to 1.000s",
        "TTS group 0 duration fit warning at 1.50x",
    ]


def test_synthesize_voice_generates_voiceclone_reference_artifact(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    with wave.open(str(task_dir / "audio.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x01\x00" * 48_000)
    (task_dir / "transcript.json").write_text(
        json.dumps(
            {
                "detected_source_language": "en",
                "segments": [
                    {"start": 0.5, "end": 1.0, "text": "Hello"},
                    {"start": 2.0, "end": 2.5, "text": "World"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (task_dir / "translation.json").write_text(
        json.dumps(
            {
                "target_language": "zh",
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "第一句"},
                    {"start": 1.0, "end": 2.0, "text": "第二句"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    speech_client = FakeVoiceCloneSpeechClient()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
        speech_client=speech_client,
    )

    result = adapter.execute(task, "synthesize_voice")

    assert result.success is True
    assert result.artifacts == [
        ("voice_clone_reference", str(task_dir / "voice_clone_reference.wav")),
        ("voiceover", str(task_dir / "zh_voice.wav")),
    ]
    assert [call[0] for call in speech_client.calls] == ["第一句第二句。"]
    reference = speech_client.calls[0][1]
    assert reference.data_uri.startswith("data:audio/wav;base64,")
    assert reference.base64_size_bytes == len(reference.base64_audio.encode("ascii"))
    assert reference.base64_size_bytes <= VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES
    assert result.metadata["tts_voice_clone_reference_path"] == str(task_dir / "voice_clone_reference.wav")
    assert result.metadata["tts_voice_clone_reference_base64_bytes"] == reference.base64_size_bytes
    assert result.metadata["tts_voice_clone_reference_truncated"] is False
    with wave.open(str(task_dir / "voice_clone_reference.wav"), "rb") as handle:
        assert handle.getframerate() == 16000
        assert handle.getnframes() == 16_000


def test_synthesize_voice_truncates_oversized_voiceclone_reference(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.runner.ai_adapter.VOICE_CLONE_REFERENCE_INITIAL_SECONDS", 2.0)
    monkeypatch.setattr("backend.app.runner.ai_adapter.VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES", 12_000)
    monkeypatch.setattr("backend.app.runner.tts.VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES", 12_000)
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    with wave.open(str(task_dir / "audio.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x01\x00" * 64_000)
    (task_dir / "transcript.json").write_text(
        json.dumps(
            {
                "detected_source_language": "en",
                "segments": [{"start": 0.0, "end": 4.0, "text": "Long speech"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (task_dir / "translation.json").write_text(
        json.dumps(
            {
                "target_language": "zh",
                "segments": [{"start": 0.0, "end": 1.0, "text": "一句话"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    speech_client = FakeVoiceCloneSpeechClient()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
        speech_client=speech_client,
    )

    result = adapter.execute(task, "synthesize_voice")

    reference = speech_client.calls[0][1]
    assert reference.base64_size_bytes <= 12_000
    assert reference.truncated is True
    assert result.metadata["tts_voice_clone_reference_truncated"] is True
    assert result.metadata["tts_voice_clone_reference_base64_bytes"] <= 12_000


def test_synthesize_voice_raises_when_voiceclone_reference_remains_oversized(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.runner.ai_adapter.VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES", 1)
    monkeypatch.setattr("backend.app.runner.tts.VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES", 1)
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    with wave.open(str(task_dir / "audio.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x01\x00" * 16_000)
    (task_dir / "translation.json").write_text(
        json.dumps(
            {
                "target_language": "zh",
                "segments": [{"start": 0.0, "end": 1.0, "text": "一句话"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    speech_client = FakeVoiceCloneSpeechClient()
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
        speech_client=speech_client,
    )

    try:
        adapter.execute(task, "synthesize_voice")
    except RuntimeError as exc:
        assert "声音样本 Base64 字符串超过本地上传阈值" in str(exc)
    else:
        raise AssertionError("expected oversized voiceclone reference to fail")
    assert speech_client.calls == []


def test_sync_preview_runs_ffmpeg_and_returns_preview_artifact(db_session, tmp_path, monkeypatch):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    video_path = task_dir / "source.mp4"
    voice_path = task_dir / "zh_voice.wav"
    video_path.write_bytes(b"video")
    voice_path.write_bytes(b"voice")
    calls = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)
        Path(command[-1]).write_bytes(b"preview")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("backend.app.runner.ai_adapter.subprocess.run", fake_run)
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "sync_preview")

    assert result.success is True
    assert calls == [
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
            str(task_dir / "preview.mp4"),
        ]
    ]
    assert result.artifacts == [("preview", str(task_dir / "preview.mp4"))]
    assert result.metadata["preview_generator"] == "ffmpeg"


def test_execute_marks_unknown_step_as_skipped(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "upload_video")

    assert result.success is True
    assert result.message == "AI adapter skipped unsupported step upload_video"
    assert result.artifacts == []
    assert result.metadata["step_status"] == "skipped"


def test_extract_audio_runs_ffmpeg_and_returns_audio_artifact(db_session, tmp_path, monkeypatch):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir(parents=True)
    video_path = task_dir / "source.mp4"
    video_path.write_bytes(b"video")
    calls = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)
        Path(command[-1]).write_bytes(b"audio")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("backend.app.runner.ai_adapter.subprocess.run", fake_run)
    adapter = AiWorkflowAdapter(
        storage_root=tmp_path,
        transcriber=FakeTranscriber(),
        translation_client=FakeTranslationClient(),
        metadata_client=FakeMetadataClient(),
    )

    result = adapter.execute(task, "extract_audio")

    assert result.success is True
    assert calls == [
        [
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
            str(task_dir / "audio.wav"),
        ]
    ]
    assert (task_dir / "audio.wav").read_bytes() == b"audio"
    assert result.artifacts == [("audio", str(task_dir / "audio.wav"))]
    assert result.metadata["extractor"] == "ffmpeg"
