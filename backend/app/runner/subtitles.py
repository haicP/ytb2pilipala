import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pysubs2


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    tts_text: str | None = None


@dataclass(frozen=True)
class TtsSentenceGroup:
    start: float
    end: float
    text: str
    source_indexes: tuple[int, ...]
    tts_text: str | None = None


@dataclass(frozen=True)
class DubbingPlanSegment:
    id: int
    source_indexes: tuple[int, ...]
    start: float
    end: float
    source_text: str
    zh_text: str
    tts_text: str
    estimated_cps: float
    fit_level: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class TtsTextRewriteExample:
    original: str
    replacement: str
    resolved: bool


@dataclass(frozen=True)
class TtsTextNormalizationReport:
    text: str
    detected_count: int
    rewritten_count: int
    unresolved_count: int
    protected_count: int
    rewrite_examples: tuple[TtsTextRewriteExample, ...]


SUPPORTED_SUBTITLE_EXTENSIONS = {".ass", ".srt", ".vtt"}
CHINESE_SUBTITLE_PREFIXES = ("zh-hans", "zh-cn", "zh-sg", "zh")
LANGUAGE_TAG_PATTERN = re.compile(r"(?<![a-z0-9])zh(?:-[a-z0-9]+)?(?![a-z0-9])")
SENTENCE_END_PATTERN = re.compile(r"[.!?。？！…]+[\"')\]}”’）】》」』]*$")
DUBBING_PLAN_WARNING_CPS = 7.0
SEMANTIC_MERGE_MAX_GAP_SECONDS = 0.35
SEMANTIC_MERGE_MAX_DURATION_SECONDS = 15.0
SEMANTIC_MERGE_MAX_TEXT_LENGTH = 350
TTS_GROUP_MAX_GAP_SECONDS = 0.8
TTS_GROUP_MAX_DURATION_SECONDS = 20.0
TTS_GROUP_MAX_TEXT_LENGTH = 500
CJK_OR_PUNCTUATION_PATTERN = (
    r"\u3400-\u4dbf"
    r"\u4e00-\u9fff"
    r"\uf900-\ufaff"
    r"\u3000-\u303f"
    r"\uff00-\uffef"
    r"，。？！；：、“”‘’（）《》【】"
)
CJK_BOUNDARY_SPACE_PATTERN = re.compile(
    rf"([{CJK_OR_PUNCTUATION_PATTERN}])\s+([{CJK_OR_PUNCTUATION_PATTERN}])"
)
CJK_CHARACTER_PATTERN = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
CJK_SLASH_PATTERN = re.compile(
    rf"([{CJK_CHARACTER_PATTERN}])\s*/\s*([{CJK_CHARACTER_PATTERN}])"
)
SPEAKABLE_PUNCTUATION_PATTERN = re.compile(
    r"[\s，。？！；：、、“”‘’（）《》【】…,.!?;:\"'()\[\]{}<>/\\|-]+"
)
URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)[^\s，。？！；：、“”‘’（）《》【】]+")
EMAIL_PATTERN = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
BACKTICK_CODE_PATTERN = re.compile(r"`[^`]+`")
VERSION_PATTERN = re.compile(r"(?i)\b(?:v|version)\s*\d+(?:\.\d+)+(?:[-_.]?[a-z0-9]+)*\b")
ENGLISH_FRAGMENT_PATTERN = re.compile(r"(?i)\b[a-z][a-z0-9]*(?:[-_+.][a-z0-9]+)*\b")
PROTECTED_TTS_FRAGMENT_PATTERNS = (BACKTICK_CODE_PATTERN, URL_PATTERN, EMAIL_PATTERN)
PROTECTED_TTS_PLACEHOLDER_PATTERN = re.compile(r"\ue000(\d+)\ue001")
TTS_REWRITE_EXAMPLE_LIMIT = 5
TTS_TERM_REPLACEMENTS = {
    "ai": "诶艾",
    "api": "诶屁艾",
    "apis": "诶屁艾",
    "asr": "诶艾丝阿",
    "bilibili": "哔哩哔哩",
    "codex": "扣德艾克斯",
    "docker": "刀客",
    "fastapi": "法斯特诶屁艾",
    "ffmpeg": "艾弗艾弗艾姆佩格",
    "github": "代码托管平台",
    "gpt": "基屁替",
    "hermes": "赫尔墨斯",
    "json": "杰森",
    "llm": "艾勒艾勒艾姆",
    "mimo": "米墨",
    "news": "纽斯",
    "openai": "欧喷诶艾",
    "openclaw": "欧喷克劳",
    "python": "派森",
    "react": "瑞艾克特",
    "srt": "艾丝阿提",
    "tts": "替替艾斯",
    "url": "优阿艾勒",
    "urls": "优阿艾勒",
    "vite": "维特",
    "whisper": "威斯珀",
    "youtube": "优兔",
    "yt-dlp": "歪踢迪艾勒屁",
}


def find_chinese_subtitle(task_dir: Path) -> Path | None:
    candidates = [
        path
        for path in task_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUBTITLE_EXTENSIONS
    ]

    ranked = [
        (priority, path.name.lower(), path)
        for path in candidates
        if (priority := _chinese_subtitle_priority(path)) is not None
    ]
    if not ranked:
        return None

    return min(ranked)[2]


def normalize_subtitle_to_srt(source_path: Path, output_path: Path) -> Path:
    subtitles = pysubs2.load(str(source_path), encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subtitles.save(str(output_path), format_="srt", encoding="utf-8")
    return output_path


def write_segments_to_srt(segments: list[TranscriptSegment], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    for index, segment in enumerate(segments, start=1):
        _validate_segment_timeline(segment)
        lines.extend(
            [
                str(index),
                f"{_timestamp(segment.start)} --> {_timestamp(segment.end)}",
                segment.text,
                "",
            ]
        )

    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return output_path


def merge_incomplete_sentence_segments(
    segments: list[TranscriptSegment],
    *,
    max_gap_seconds: float = SEMANTIC_MERGE_MAX_GAP_SECONDS,
    max_duration_seconds: float = SEMANTIC_MERGE_MAX_DURATION_SECONDS,
    max_text_length: int = SEMANTIC_MERGE_MAX_TEXT_LENGTH,
) -> list[TranscriptSegment]:
    merged: list[TranscriptSegment] = []
    current: TranscriptSegment | None = None

    for segment in segments:
        _validate_segment_timeline(segment)
        text = _normalize_segment_text(segment.text)
        if not text:
            continue
        normalized_segment = TranscriptSegment(start=segment.start, end=segment.end, text=text)
        if current is None:
            current = normalized_segment
            continue

        if _should_merge_segments(
            current,
            normalized_segment,
            max_gap_seconds=max_gap_seconds,
            max_duration_seconds=max_duration_seconds,
            max_text_length=max_text_length,
        ):
            current = TranscriptSegment(
                start=current.start,
                end=normalized_segment.end,
                text=f"{current.text} {normalized_segment.text}",
            )
            continue

        merged.append(current)
        current = normalized_segment

    if current is not None:
        merged.append(current)
    return merged


def group_segments_for_tts(
    segments: list[TranscriptSegment],
    *,
    max_gap_seconds: float = TTS_GROUP_MAX_GAP_SECONDS,
    max_duration_seconds: float = TTS_GROUP_MAX_DURATION_SECONDS,
    max_text_length: int = TTS_GROUP_MAX_TEXT_LENGTH,
) -> list[TtsSentenceGroup]:
    groups: list[TtsSentenceGroup] = []
    current: TtsSentenceGroup | None = None

    for index, segment in enumerate(segments):
        _validate_segment_timeline(segment)
        text = _normalize_segment_text(segment.text)
        if not text:
            continue
        next_group = TtsSentenceGroup(
            start=segment.start,
            end=segment.end,
            text=text,
            source_indexes=(index,),
            tts_text=_normalize_existing_tts_text(segment.tts_text)
            if segment.tts_text is not None
            else normalize_tts_request_text(text),
        )
        if current is None:
            current = next_group
            continue

        if _should_merge_tts_groups(
            current,
            next_group,
            max_gap_seconds=max_gap_seconds,
            max_duration_seconds=max_duration_seconds,
            max_text_length=max_text_length,
        ):
            joined_text = _join_tts_text(current.text, next_group.text)
            current = TtsSentenceGroup(
                start=current.start,
                end=next_group.end,
                text=joined_text,
                source_indexes=(*current.source_indexes, *next_group.source_indexes),
                tts_text=_join_tts_request_text(
                    current.tts_text or current.text,
                    next_group.tts_text or next_group.text,
                ),
            )
            continue

        groups.append(_with_tts_text(current))
        current = next_group

    if current is not None:
        groups.append(_with_tts_text(current))
    return groups


def build_dubbing_plan(
    source_segments: list[TranscriptSegment],
    translated_segments: list[TranscriptSegment],
) -> list[DubbingPlanSegment]:
    source_segments = _normalized_valid_segments(source_segments)
    tts_groups = group_segments_for_tts(translated_segments)
    plan: list[DubbingPlanSegment] = []

    for group in tts_groups:
        zh_text = _normalize_display_tts_text(group.text)
        tts_text = (
            _normalize_existing_tts_text(group.tts_text)
            if group.tts_text is not None
            else normalize_tts_request_text(group.text)
        )
        if not zh_text:
            continue

        source_indexes = _source_indexes_for_time_range(source_segments, group.start, group.end)
        if not source_indexes:
            source_indexes = group.source_indexes
        source_text = _source_text_for_indexes(source_segments, source_indexes)
        duration = max(0.0, group.end - group.start)
        estimated_cps = estimate_tts_cps(tts_text, duration)
        fit_level = "warning" if duration <= 0 or estimated_cps > DUBBING_PLAN_WARNING_CPS else "ok"
        plan.append(
            DubbingPlanSegment(
                id=len(plan),
                source_indexes=source_indexes,
                start=group.start,
                end=group.end,
                source_text=source_text,
                zh_text=zh_text,
                tts_text=tts_text,
                estimated_cps=estimated_cps,
                fit_level=fit_level,
            )
        )

    return plan


def dump_dubbing_plan(plan: list[DubbingPlanSegment]) -> list[dict[str, object]]:
    return [
        {
            "id": segment.id,
            "source_indexes": list(segment.source_indexes),
            "start": segment.start,
            "end": segment.end,
            "duration": segment.duration,
            "source_text": segment.source_text,
            "zh_text": segment.zh_text,
            "tts_text": segment.tts_text,
            "estimated_cps": segment.estimated_cps,
            "fit_level": segment.fit_level,
        }
        for segment in plan
    ]


def summarize_dubbing_plan(plan: list[DubbingPlanSegment]) -> dict[str, object]:
    if not plan:
        return {
            "segment_count": 0,
            "warning_count": 0,
            "max_estimated_cps": 0.0,
            "average_estimated_cps": 0.0,
        }

    cps_values = [segment.estimated_cps for segment in plan]
    return {
        "segment_count": len(plan),
        "warning_count": sum(1 for segment in plan if segment.fit_level != "ok"),
        "max_estimated_cps": round(max(cps_values), 2),
        "average_estimated_cps": round(sum(cps_values) / len(cps_values), 2),
    }


def estimate_tts_cps(text: str, duration_seconds: float) -> float:
    if duration_seconds <= 0:
        return 0.0
    return round(_speakable_unit_count(text) / duration_seconds, 2)


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _normalize_segment_text(text: str) -> str:
    return " ".join(text.split())


def normalize_tts_request_text(text: str) -> str:
    return normalize_tts_request_text_with_report(text).text


def normalize_tts_request_text_with_report(text: str) -> TtsTextNormalizationReport:
    normalized = _normalize_display_tts_text(text)
    examples: list[TtsTextRewriteExample] = []
    detected_count = 0
    rewritten_count = 0
    unresolved_count = 0
    protected_count = 0

    normalized, protected_fragments = protect_tts_text_fragments(normalized)
    protected_count = len(protected_fragments)
    detected_count += protected_count
    for fragment in protected_fragments:
        _append_rewrite_example(examples, fragment, fragment, True)

    normalized, stats = _replace_special_tts_fragments(
        normalized,
        VERSION_PATTERN,
        _replace_version_text,
        examples,
    )
    detected_count += stats[0]
    rewritten_count += stats[1]
    unresolved_count += stats[2]

    def replace_english(match: re.Match[str]) -> str:
        nonlocal detected_count, rewritten_count, unresolved_count
        original = match.group(0)
        detected_count += 1
        replacement = _english_tts_replacement(original)
        resolved = replacement != original
        if resolved:
            rewritten_count += 1
        else:
            unresolved_count += 1
        _append_rewrite_example(examples, original, replacement, resolved)
        return replacement

    normalized = ENGLISH_FRAGMENT_PATTERN.sub(replace_english, normalized)
    normalized = _cleanup_tts_punctuation_spacing(normalized)
    normalized = restore_tts_text_fragments(normalized, protected_fragments)
    return TtsTextNormalizationReport(
        text=normalized,
        detected_count=detected_count,
        rewritten_count=rewritten_count,
        unresolved_count=unresolved_count,
        protected_count=protected_count,
        rewrite_examples=tuple(examples),
    )


def _normalize_display_tts_text(text: str) -> str:
    normalized = _normalize_segment_text(text)
    normalized = CJK_SLASH_PATTERN.sub(r"\1、\2", normalized)
    while True:
        cleaned = CJK_BOUNDARY_SPACE_PATTERN.sub(r"\1\2", normalized)
        if cleaned == normalized:
            return cleaned
        normalized = cleaned


def tts_text_ends_with_sentence_punctuation(text: str) -> bool:
    return _ends_with_sentence_punctuation(text)


def _join_tts_text(current_text: str, next_text: str) -> str:
    return _normalize_display_tts_text(f"{current_text} {next_text}")


def _join_tts_request_text(current_text: str, next_text: str) -> str:
    return _normalize_existing_tts_text(f"{current_text} {next_text}")


def _with_tts_text(group: TtsSentenceGroup) -> TtsSentenceGroup:
    return TtsSentenceGroup(
        start=group.start,
        end=group.end,
        text=_normalize_display_tts_text(group.text),
        source_indexes=group.source_indexes,
        tts_text=_normalize_existing_tts_text(group.tts_text)
        if group.tts_text is not None
        else normalize_tts_request_text(group.text),
    )


def _replace_special_tts_fragments(
    text: str,
    pattern: re.Pattern[str],
    replacement: str | Callable[[re.Match[str]], str],
    examples: list[TtsTextRewriteExample],
) -> tuple[str, tuple[int, int, int]]:
    detected_count = 0
    rewritten_count = 0
    unresolved_count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal detected_count, rewritten_count
        detected_count += 1
        rewritten_count += 1
        original = match.group(0)
        replacement_text = replacement(match) if callable(replacement) else replacement
        _append_rewrite_example(examples, original, replacement_text, True)
        return replacement_text

    return pattern.sub(replace, text), (detected_count, rewritten_count, unresolved_count)


def _replace_version_text(match: re.Match[str]) -> str:
    value = re.sub(r"(?i)^version\s*", "", match.group(0))
    value = re.sub(r"(?i)^v", "", value)
    return f"版本{value}"


def _english_tts_replacement(original: str) -> str:
    return TTS_TERM_REPLACEMENTS.get(original.lower(), original)


def _normalize_existing_tts_text(text: str) -> str:
    return _normalize_display_tts_text(text)


def protect_tts_text_fragments(text: str) -> tuple[str, tuple[str, ...]]:
    spans = _protected_tts_fragment_spans(text)
    if not spans:
        return text, ()

    fragments: list[str] = []
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(text[cursor:start])
        pieces.append(f"\ue000{len(fragments)}\ue001")
        fragments.append(text[start:end])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), tuple(fragments)


def restore_tts_text_fragments(text: str, fragments: tuple[str, ...]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if 0 <= index < len(fragments):
            return fragments[index]
        return match.group(0)

    return PROTECTED_TTS_PLACEHOLDER_PATTERN.sub(replace, text)


def find_unprotected_english_fragments(text: str) -> tuple[str, ...]:
    protected_text, _ = protect_tts_text_fragments(text)
    return tuple(match.group(0) for match in ENGLISH_FRAGMENT_PATTERN.finditer(protected_text))


def protected_tts_fragment_count(text: str) -> int:
    return len(protect_tts_text_fragments(text)[1])


def _protected_tts_fragment_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in PROTECTED_TTS_FRAGMENT_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            overlaps_existing = any(
                start < existing_end and end > existing_start
                for existing_start, existing_end in spans
            )
            if overlaps_existing:
                continue
            spans.append((start, end))
    return sorted(spans)


def _append_rewrite_example(
    examples: list[TtsTextRewriteExample],
    original: str,
    replacement: str,
    resolved: bool,
) -> None:
    if len(examples) >= TTS_REWRITE_EXAMPLE_LIMIT:
        return
    example = TtsTextRewriteExample(original=original, replacement=replacement, resolved=resolved)
    if example not in examples:
        examples.append(example)


def _cleanup_tts_punctuation_spacing(text: str) -> str:
    text = re.sub(r"\s*([，。？！；：、])\s*", r"\1", text)
    text = CJK_SLASH_PATTERN.sub(r"\1、\2", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([，。？！；：、]){2,}", r"\1", text)
    while True:
        cleaned = CJK_BOUNDARY_SPACE_PATTERN.sub(r"\1\2", text)
        if cleaned == text:
            return cleaned
        text = cleaned


def _should_merge_segments(
    current: TranscriptSegment,
    next_segment: TranscriptSegment,
    *,
    max_gap_seconds: float,
    max_duration_seconds: float,
    max_text_length: int,
) -> bool:
    if _ends_with_sentence_punctuation(current.text):
        return False
    if next_segment.start - current.end > max_gap_seconds:
        return False
    if next_segment.end - current.start > max_duration_seconds:
        return False
    if len(f"{current.text} {next_segment.text}") > max_text_length:
        return False
    return True


def _should_merge_tts_groups(
    current: TtsSentenceGroup,
    next_group: TtsSentenceGroup,
    *,
    max_gap_seconds: float,
    max_duration_seconds: float,
    max_text_length: int,
) -> bool:
    if _ends_with_sentence_punctuation(current.text):
        return False
    if next_group.start - current.end > max_gap_seconds:
        return False
    if next_group.end - current.start > max_duration_seconds:
        return False
    if len(f"{current.text} {next_group.text}") > max_text_length:
        return False
    return True


def _ends_with_sentence_punctuation(text: str) -> bool:
    return SENTENCE_END_PATTERN.search(text.strip()) is not None


def _normalized_valid_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    normalized: list[TranscriptSegment] = []
    for segment in segments:
        _validate_segment_timeline(segment)
        text = _normalize_segment_text(segment.text)
        if text:
            normalized.append(TranscriptSegment(start=segment.start, end=segment.end, text=text))
    return normalized


def _source_indexes_for_time_range(
    source_segments: list[TranscriptSegment],
    start: float,
    end: float,
) -> tuple[int, ...]:
    indexes = [
        index
        for index, segment in enumerate(source_segments)
        if segment.start < end and segment.end > start
    ]
    return tuple(indexes)


def _source_text_for_indexes(
    source_segments: list[TranscriptSegment],
    indexes: tuple[int, ...],
) -> str:
    if not source_segments:
        return ""
    texts = [
        source_segments[index].text.strip()
        for index in indexes
        if 0 <= index < len(source_segments) and source_segments[index].text.strip()
    ]
    return " ".join(texts)


def _speakable_unit_count(text: str) -> int:
    return len(SPEAKABLE_PUNCTUATION_PATTERN.sub("", text))


def _chinese_subtitle_priority(path: Path) -> int | None:
    stem = path.stem.lower()
    tags = LANGUAGE_TAG_PATTERN.findall(stem.replace("_", "-"))

    for priority, prefix in enumerate(CHINESE_SUBTITLE_PREFIXES):
        if prefix in tags:
            return priority

    return None


def _validate_segment_timeline(segment: TranscriptSegment) -> None:
    if segment.start < 0:
        raise ValueError("segment start must be non-negative")
    if segment.end < segment.start:
        raise ValueError("segment end must be greater than or equal to start")
