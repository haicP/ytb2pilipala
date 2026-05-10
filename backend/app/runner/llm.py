import json
from typing import Any

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models import Task
from backend.app.repositories import TaskRepository
from backend.app.runner.ai_adapter import MetadataResult, TtsTextRewriteResult
from backend.app.runner.prompts import DEFAULT_TRANSLATION_PROMPT
from backend.app.runner.subtitles import (
    TranscriptSegment,
    TtsTextRewriteExample,
    find_unprotected_english_fragments,
    protected_tts_fragment_count,
)


def _assistant_llm_settings() -> dict[str, str]:
    session = SessionLocal()
    try:
        repo = TaskRepository(session)
        return repo.get_app_settings(
            (
                "assistant_base_url",
                "assistant_api_key",
                "assistant_model_id",
                "assistant_translation_prompt",
            )
        )
    finally:
        session.close()


class OpenAITranslationClient:
    batch_size = 50
    max_batch_attempts = 2

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        settings = get_settings()
        assistant_settings = _assistant_llm_settings()
        self.base_url = (
            base_url
            if base_url is not None
            else assistant_settings.get("assistant_base_url", "") or settings.api2key_base_url
        )
        self.api_key = (
            api_key
            if api_key is not None
            else assistant_settings.get("assistant_api_key", "") or settings.llm_api_key
        )
        self.model = (
            model
            if model is not None
            else assistant_settings.get("assistant_model_id", "") or settings.llm_model
        )
        self.translation_prompt = (
            assistant_settings.get("assistant_translation_prompt", "") or DEFAULT_TRANSLATION_PROMPT
        )
        self._client = None

    def translate_segments(
        self,
        segments: list[TranscriptSegment],
        target_language: str = "zh",
    ) -> list[TranscriptSegment]:
        result: list[TranscriptSegment] = []
        for batch_start in range(0, len(segments), self.batch_size):
            batch_segments = segments[batch_start : batch_start + self.batch_size]
            translated_batch = self._translate_batch(batch_segments, target_language)
            result.extend(translated_batch)
        return result

    def _translate_batch(
        self,
        segments: list[TranscriptSegment],
        target_language: str,
    ) -> list[TranscriptSegment]:
        payload = [
            {"index": index, "start": segment.start, "end": segment.end, "text": segment.text}
            for index, segment in enumerate(segments)
        ]

        last_error: ValueError | None = None
        for _attempt in range(self.max_batch_attempts):
            content = self._complete_translation_json(
                [
                    {
                        "role": "system",
                        "content": (
                            f"{self.translation_prompt}\n\n"
                            "Return JSON only with a `segments` array. "
                            "Preserve index, start, and end values."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"target_language": target_language, "segments": payload},
                            ensure_ascii=False,
                        ),
                    },
                ]
            )
            try:
                return self._segments_from_response(segments, content)
            except ValueError as exc:
                last_error = exc

        if last_error is None:
            raise ValueError("LLM translation batch failed without error details")
        raise last_error

    def _complete_translation_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return self._complete_stream_json(messages)

    def _segments_from_response(
        self,
        source_segments: list[TranscriptSegment],
        content: dict[str, Any],
    ) -> list[TranscriptSegment]:
        translated = content.get("segments")
        if not isinstance(translated, list):
            raise ValueError("LLM translation response must include a segments array")

        by_index: dict[int, dict[str, Any]] = {}
        for item in translated:
            if isinstance(item, dict) and isinstance(item.get("index"), int):
                by_index[item["index"]] = item

        result: list[TranscriptSegment] = []
        for index, source in enumerate(source_segments):
            item = by_index.get(index)
            text = item.get("text") if item else None
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"LLM translation response missing text for segment {index}")
            result.append(TranscriptSegment(start=source.start, end=source.end, text=text.strip()))
        return result

    def _complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        response = self._openai().chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM response is empty")
        return json.loads(content)

    def _complete_stream_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        stream = self._openai().chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            stream=True,
        )
        content_parts: list[str] = []
        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            for choice in choices:
                delta = getattr(choice, "delta", None)
                content = self._stream_delta_content(delta)
                if content:
                    content_parts.append(content)

        content = "".join(content_parts)
        if not content:
            raise ValueError("LLM streaming response is empty")
        return json.loads(content)

    def _stream_delta_content(self, delta: object) -> str:
        content = (
            delta.get("content")
            if isinstance(delta, dict)
            else getattr(delta, "content", None)
        )
        if isinstance(content, str):
            return content
        return ""

    def _openai(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("LLM_API_KEY is required for OpenAI compatible LLM calls")
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "openai package is required for OpenAI compatible LLM calls"
                ) from exc

            kwargs: dict[str, str] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client


class OpenAITtsPhoneticRewriteClient(OpenAITranslationClient):
    def rewrite_segments(
        self,
        segments: list[TranscriptSegment],
    ) -> TtsTextRewriteResult:
        rewritten_segments: list[TranscriptSegment] = []
        examples: list[TtsTextRewriteExample] = []
        detected_count = 0
        rewritten_count = 0
        unresolved_count = 0
        protected_count = 0
        warnings: list[str] = []

        for batch_start in range(0, len(segments), self.batch_size):
            batch_segments = segments[batch_start : batch_start + self.batch_size]
            batch_result = self._rewrite_batch(batch_segments)
            rewritten_segments.extend(batch_result.segments)
            detected_count += batch_result.detected_count
            rewritten_count += batch_result.rewritten_count
            unresolved_count += batch_result.unresolved_count
            protected_count += batch_result.protected_count
            warnings.extend(batch_result.warnings)
            for example in batch_result.rewrite_examples:
                if example not in examples:
                    examples.append(example)
                if len(examples) >= 5:
                    break

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

    def _rewrite_batch(
        self,
        segments: list[TranscriptSegment],
    ) -> TtsTextRewriteResult:
        payload = [
            {
                "index": index,
                "text": segment.tts_text if segment.tts_text is not None else segment.text,
            }
            for index, segment in enumerate(segments)
        ]
        content = self._complete_tts_rewrite_json(
            [
                {
                    "role": "system",
                    "content": (
                        "你是中文 TTS 口播文本清理器。Return JSON only with a "
                        "`segments` array. Preserve every input index.\n"
                        "任务：识别中文文本中夹杂的英文词、英文缩写、品牌名、产品名、"
                        "未知英文术语，并把它们替换成相同或接近读音的中文。\n"
                        "规则：只改英文片段，不改中文语义；URL、邮箱地址、反引号包裹的"
                        "代码片段必须原样保留；不要把 URL、邮箱、代码改成中文类别名。"
                        "如果无法确定标准译名，也要给中文近似音译。\n"
                        "示例：API -> 诶屁艾；SRT -> 艾丝阿提；"
                        "OpenAI -> 欧喷诶艾；YouTube -> 优兔。\n"
                        "每个输出项包含 index、tts_text、replacements；"
                        "replacements 每项包含 original 和 replacement。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"segments": payload}, ensure_ascii=False),
                },
            ]
        )
        return self._tts_rewrite_segments_from_response(segments, content)

    def _complete_tts_rewrite_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return self._complete_stream_json(messages)

    def _tts_rewrite_segments_from_response(
        self,
        source_segments: list[TranscriptSegment],
        content: dict[str, Any],
    ) -> TtsTextRewriteResult:
        rewritten = content.get("segments")
        if not isinstance(rewritten, list):
            raise ValueError("LLM TTS rewrite response must include a segments array")

        by_index: dict[int, dict[str, Any]] = {}
        for item in rewritten:
            if isinstance(item, dict) and isinstance(item.get("index"), int):
                by_index[item["index"]] = item

        result: list[TranscriptSegment] = []
        examples: list[TtsTextRewriteExample] = []
        detected_count = 0
        rewritten_count = 0
        unresolved_count = 0
        protected_count = 0
        warnings: list[str] = []

        for index, source in enumerate(source_segments):
            item = by_index.get(index)
            tts_text = item.get("tts_text") if item else None
            if not isinstance(tts_text, str) or not tts_text.strip():
                raise ValueError(f"LLM TTS rewrite response missing tts_text for segment {index}")

            base_text = source.tts_text if source.tts_text is not None else source.text
            segment_protected_count = protected_tts_fragment_count(base_text)
            segment_detected = len(find_unprotected_english_fragments(base_text))
            segment_unresolved = len(find_unprotected_english_fragments(tts_text))
            protected_count += segment_protected_count
            detected_count += segment_detected + segment_protected_count
            unresolved_count += segment_unresolved

            replacements = item.get("replacements", []) if item else []
            segment_rewritten_count = _append_tts_rewrite_examples(examples, replacements)
            rewritten_count += segment_rewritten_count
            if segment_unresolved:
                warnings.append(
                    "LLM TTS rewrite left "
                    f"{segment_unresolved} English fragments in segment {index}"
                )

            result.append(
                TranscriptSegment(
                    start=source.start,
                    end=source.end,
                    text=source.text,
                    tts_text=tts_text.strip(),
                )
            )

        return TtsTextRewriteResult(
            segments=result,
            source="llm_phonetic",
            detected_count=detected_count,
            rewritten_count=rewritten_count,
            unresolved_count=unresolved_count,
            protected_count=protected_count,
            warning_count=unresolved_count,
            rewrite_examples=tuple(examples),
            warnings=tuple(warnings),
        )


class OpenAIMetadataClient(OpenAITranslationClient):
    def generate_metadata(
        self,
        task: Task,
        transcript_segments: list[TranscriptSegment],
        translated_segments: list[TranscriptSegment],
    ) -> MetadataResult:
        content = self._complete_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Generate Bilibili submission metadata. Return JSON only with "
                        "title, description, tags, and category."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": {
                                "title": task.title,
                                "source_type": task.source_type,
                                "input": task.input,
                            },
                            "source_segments": [
                                segment.__dict__ for segment in transcript_segments
                            ],
                            "translated_segments": [
                                segment.__dict__ for segment in translated_segments
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        tags = content.get("tags", [])
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        if not isinstance(tags, list):
            tags = []
        return MetadataResult(
            title=str(content.get("title") or task.title),
            description=str(content.get("description") or ""),
            tags=[str(tag) for tag in tags],
            category=str(content.get("category") or "科技"),
        )


def _append_tts_rewrite_examples(
    examples: list[TtsTextRewriteExample],
    replacements: Any,
) -> int:
    if not isinstance(replacements, list):
        return 0

    rewritten_count = 0
    for replacement_item in replacements:
        if not isinstance(replacement_item, dict):
            continue
        original = replacement_item.get("original")
        replacement = replacement_item.get("replacement")
        if not isinstance(original, str) or not original:
            continue
        if not isinstance(replacement, str) or not replacement:
            continue
        if original == replacement:
            continue
        rewritten_count += 1
        example = TtsTextRewriteExample(
            original=original,
            replacement=replacement,
            resolved=True,
        )
        if len(examples) < 5 and example not in examples:
            examples.append(example)
    return rewritten_count
