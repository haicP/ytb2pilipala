import pytest

from backend.app.runner.subtitles import (
    DubbingPlanSegment,
    TranscriptSegment,
    TtsSentenceGroup,
    build_dubbing_plan,
    dump_dubbing_plan,
    estimate_tts_cps,
    find_chinese_subtitle,
    group_segments_for_tts,
    merge_incomplete_sentence_segments,
    normalize_subtitle_to_srt,
    normalize_tts_request_text,
    normalize_tts_request_text_with_report,
    write_segments_to_srt,
)


def test_find_chinese_subtitle_prefers_simplified_chinese_prefix(tmp_path):
    generic_zh = tmp_path / "demo.zh.srt"
    english = tmp_path / "demo.en.srt"
    simplified = tmp_path / "demo.zh-Hans.ass"
    generic_zh.write_text("generic zh", encoding="utf-8")
    english.write_text("english", encoding="utf-8")
    simplified.write_text("simplified", encoding="utf-8")

    assert find_chinese_subtitle(tmp_path) == simplified


def test_find_chinese_subtitle_handles_hyphen_separated_language_tag(tmp_path):
    generic_zh = tmp_path / "subtitle.zh.srt"
    simplified = tmp_path / "subtitle-zh-Hans.ass"
    generic_zh.write_text("generic zh", encoding="utf-8")
    simplified.write_text("simplified", encoding="utf-8")

    assert find_chinese_subtitle(tmp_path) == simplified


def test_find_chinese_subtitle_ignores_non_simplified_chinese_tags(tmp_path):
    for filename in ("subtitle.zh-Hant.ass", "subtitle.zh-TW.srt", "subtitle.zhx.vtt"):
        (tmp_path / filename).write_text("not simplified", encoding="utf-8")

    assert find_chinese_subtitle(tmp_path) is None


def test_normalize_subtitle_to_srt_converts_ass_to_utf8_srt(tmp_path):
    source = tmp_path / "demo.zh-Hans.ass"
    output = tmp_path / "normalized.srt"
    source.write_text(
        "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding",
                "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
                "0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1",
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
                "Effect, Text",
                "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,你好，世界",
            ]
        ),
        encoding="utf-8",
    )

    result = normalize_subtitle_to_srt(source, output)

    assert result == output
    assert output.read_text(encoding="utf-8") == (
        "1\n00:00:01,000 --> 00:00:02,500\n你好，世界\n\n"
    )


def test_write_segments_to_srt_uses_stable_timestamp_format(tmp_path):
    output = tmp_path / "segments.srt"
    segments = [
        TranscriptSegment(start=1.25, end=65.5, text="第一行"),
        TranscriptSegment(start=3661.005, end=3662.125, text="second line"),
    ]

    result = write_segments_to_srt(segments, output)

    assert result == output
    assert output.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:01,250 --> 00:01:05,500\n"
        "第一行\n"
        "\n"
        "2\n"
        "01:01:01,005 --> 01:01:02,125\n"
        "second line\n"
        "\n"
    )


def test_write_segments_to_srt_rejects_negative_timestamps(tmp_path):
    output = tmp_path / "segments.srt"
    segments = [TranscriptSegment(start=-0.1, end=1.0, text="bad start")]

    with pytest.raises(ValueError, match="start must be non-negative"):
        write_segments_to_srt(segments, output)


def test_write_segments_to_srt_rejects_end_before_start(tmp_path):
    output = tmp_path / "segments.srt"
    segments = [TranscriptSegment(start=2.0, end=1.0, text="bad range")]

    with pytest.raises(ValueError, match="end must be greater than or equal to start"):
        write_segments_to_srt(segments, output)


def test_merge_incomplete_sentence_segments_merges_adjacent_unfinished_sentence():
    segments = [
        TranscriptSegment(start=20.92, end=24.64, text="I'm going to show you real emails, building"),
        TranscriptSegment(start=24.64, end=28.12, text="a real website from scratch, running daily tasks"),
        TranscriptSegment(start=28.16, end=33.04, text="and controlling my computer live."),
    ]

    merged = merge_incomplete_sentence_segments(segments)

    assert merged == [
        TranscriptSegment(
            start=20.92,
            end=33.04,
            text=(
                "I'm going to show you real emails, building "
                "a real website from scratch, running daily tasks "
                "and controlling my computer live."
            ),
        )
    ]


def test_merge_incomplete_sentence_segments_keeps_completed_sentences_separate():
    segments = [
        TranscriptSegment(start=0.0, end=1.0, text="This is done."),
        TranscriptSegment(start=1.0, end=2.0, text="Next sentence."),
    ]

    assert merge_incomplete_sentence_segments(segments) == segments


def test_merge_incomplete_sentence_segments_respects_gap_duration_and_length_limits():
    assert merge_incomplete_sentence_segments(
        [
            TranscriptSegment(start=0.0, end=1.0, text="unfinished"),
            TranscriptSegment(start=1.5, end=2.0, text="too far"),
        ]
    ) == [
        TranscriptSegment(start=0.0, end=1.0, text="unfinished"),
        TranscriptSegment(start=1.5, end=2.0, text="too far"),
    ]
    assert merge_incomplete_sentence_segments(
        [
            TranscriptSegment(start=0.0, end=10.0, text="unfinished"),
            TranscriptSegment(start=10.0, end=15.1, text="too long"),
        ]
    ) == [
        TranscriptSegment(start=0.0, end=10.0, text="unfinished"),
        TranscriptSegment(start=10.0, end=15.1, text="too long"),
    ]
    assert merge_incomplete_sentence_segments(
        [
            TranscriptSegment(start=0.0, end=1.0, text="x" * 349),
            TranscriptSegment(start=1.0, end=2.0, text="yy"),
        ]
    ) == [
        TranscriptSegment(start=0.0, end=1.0, text="x" * 349),
        TranscriptSegment(start=1.0, end=2.0, text="yy"),
    ]


def test_group_segments_for_tts_preserves_source_indexes_for_split_sentence():
    segments = [
        TranscriptSegment(start=20.92, end=24.64, text="我会给你演示它如何阅读并回复真实邮件，构建"),
        TranscriptSegment(start=24.64, end=28.12, text="一个从零开始的真实网站，按计时器运行每日自动任务，"),
        TranscriptSegment(start=28.16, end=33.04, text="以及实时控制我的电脑，点击、浏览、打字，完全自主完成。"),
    ]

    groups = group_segments_for_tts(segments)

    assert groups == [
        TtsSentenceGroup(
            start=20.92,
            end=33.04,
            text=(
                "我会给你演示它如何阅读并回复真实邮件，构建"
                "一个从零开始的真实网站，按计时器运行每日自动任务，"
                "以及实时控制我的电脑，点击、浏览、打字，完全自主完成。"
            ),
            source_indexes=(0, 1, 2),
            tts_text=(
                "我会给你演示它如何阅读并回复真实邮件，构建"
                "一个从零开始的真实网站，按计时器运行每日自动任务，"
                "以及实时控制我的电脑，点击、浏览、打字，完全自主完成。"
            ),
        )
    ]


def test_group_segments_for_tts_respects_sentence_boundaries_and_limits():
    assert group_segments_for_tts(
        [
            TranscriptSegment(start=0.0, end=1.0, text="第一句。"),
            TranscriptSegment(start=1.0, end=2.0, text="第二句。"),
        ]
    ) == [
        TtsSentenceGroup(
            start=0.0,
            end=1.0,
            text="第一句。",
            source_indexes=(0,),
            tts_text="第一句。",
        ),
        TtsSentenceGroup(
            start=1.0,
            end=2.0,
            text="第二句。",
            source_indexes=(1,),
            tts_text="第二句。",
        ),
    ]
    assert group_segments_for_tts(
        [
            TranscriptSegment(start=0.0, end=1.0, text="未完成"),
            TranscriptSegment(start=1.5, end=2.0, text="间隔太远。"),
            TranscriptSegment(start=2.0, end=22.1, text="时长太长"),
        ]
    ) == [
        TtsSentenceGroup(
            start=0.0,
            end=2.0,
            text="未完成间隔太远。",
            source_indexes=(0, 1),
            tts_text="未完成间隔太远。",
        ),
        TtsSentenceGroup(
            start=2.0,
            end=22.1,
            text="时长太长",
            source_indexes=(2,),
            tts_text="时长太长",
        ),
    ]


def test_group_segments_for_tts_uses_wider_gap_than_translation_merge():
    segments = [
        TranscriptSegment(start=0.0, end=1.0, text="把这个打开"),
        TranscriptSegment(start=1.56, end=2.0, text="在我的浏览器里。"),
        TranscriptSegment(start=3.0, end=4.0, text="你实际上可以让"),
        TranscriptSegment(start=4.72, end=5.0, text="Codex 帮你设置好。"),
    ]

    assert merge_incomplete_sentence_segments(segments) == segments
    assert group_segments_for_tts(segments) == [
        TtsSentenceGroup(
            start=0.0,
            end=2.0,
            text="把这个打开在我的浏览器里。",
            source_indexes=(0, 1),
            tts_text="把这个打开在我的浏览器里。",
        ),
        TtsSentenceGroup(
            start=3.0,
            end=5.0,
            text="你实际上可以让 Codex 帮你设置好。",
            source_indexes=(2, 3),
            tts_text="你实际上可以让扣德艾克斯帮你设置好。",
        ),
    ]


def test_normalize_tts_request_text_rewrites_english_fragments_for_chinese_speech():
    assert (
        normalize_tts_request_text("使用 OpenAI API 生成 SRT")
        == "使用欧喷诶艾诶屁艾生成艾丝阿提"
    )
    assert normalize_tts_request_text("打开 YouTube/Bilibili") == "打开优兔、哔哩哔哩"


def test_normalize_tts_request_text_protects_urls_email_and_code_fragments():
    text = "访问 https://example.com，联系 test@example.com，运行 `npm run build`。"

    report = normalize_tts_request_text_with_report(text)

    assert report.text == "访问 https://example.com，联系 test@example.com，运行 `npm run build`。"
    assert report.detected_count == 3
    assert report.protected_count == 3
    assert report.rewritten_count == 0
    assert report.unresolved_count == 0


def test_normalize_tts_request_text_keeps_cjk_cleanup_and_marks_unknown_english():
    assert (
        normalize_tts_request_text("构建 一个真实网站， 以及实时控制")
        == "构建一个真实网站，以及实时控制"
    )
    report = normalize_tts_request_text_with_report("使用 Codex 生成 Flux news")
    assert report.text == "使用扣德艾克斯生成 Flux 纽斯"
    assert report.detected_count == 3
    assert report.rewritten_count == 2
    assert report.unresolved_count == 1
    assert any(
        example.original == "Flux" and example.resolved is False
        for example in report.rewrite_examples
    )


def test_estimate_tts_cps_ignores_chinese_punctuation_and_spaces():
    assert estimate_tts_cps("你好， 世界。", 1.0) == 4.0
    assert estimate_tts_cps("Codex 生成 AI news。", 2.0) == 6.5
    assert estimate_tts_cps("非空文本", 0.0) == 0.0


def test_build_dubbing_plan_merges_split_chinese_sentence_and_maps_source_indexes():
    source_segments = [
        TranscriptSegment(start=0.0, end=1.0, text="This tool reads"),
        TranscriptSegment(start=1.0, end=2.0, text="and replies to email."),
        TranscriptSegment(start=2.5, end=3.0, text="Next sentence."),
    ]
    translated_segments = [
        TranscriptSegment(start=0.0, end=1.0, text="这个工具会读取"),
        TranscriptSegment(start=1.0, end=2.0, text="并回复邮件。"),
        TranscriptSegment(start=2.5, end=3.0, text="下一句。"),
    ]

    plan = build_dubbing_plan(source_segments, translated_segments)

    assert plan == [
        DubbingPlanSegment(
            id=0,
            source_indexes=(0, 1),
            start=0.0,
            end=2.0,
            source_text="This tool reads and replies to email.",
            zh_text="这个工具会读取并回复邮件。",
            tts_text="这个工具会读取并回复邮件。",
            estimated_cps=6.0,
            fit_level="ok",
        ),
        DubbingPlanSegment(
            id=1,
            source_indexes=(2,),
            start=2.5,
            end=3.0,
            source_text="Next sentence.",
            zh_text="下一句。",
            tts_text="下一句。",
            estimated_cps=6.0,
            fit_level="ok",
        ),
    ]


def test_build_dubbing_plan_marks_fast_segments_and_skips_empty_text():
    plan = build_dubbing_plan(
        [TranscriptSegment(start=0.0, end=1.0, text="Long source text")],
        [
            TranscriptSegment(start=0.0, end=1.0, text="这是一个明显太长无法自然读完的中文配音片段。"),
            TranscriptSegment(start=1.0, end=2.0, text="   "),
        ],
    )

    assert len(plan) == 1
    assert plan[0].fit_level == "warning"
    assert plan[0].estimated_cps > 7.0
    assert dump_dubbing_plan(plan)[0] == {
        "id": 0,
        "source_indexes": [0],
        "start": 0.0,
        "end": 1.0,
        "duration": 1.0,
        "source_text": "Long source text",
        "zh_text": "这是一个明显太长无法自然读完的中文配音片段。",
        "tts_text": "这是一个明显太长无法自然读完的中文配音片段。",
        "estimated_cps": plan[0].estimated_cps,
        "fit_level": "warning",
    }


def test_build_dubbing_plan_keeps_subtitle_text_and_adds_tts_text():
    plan = build_dubbing_plan(
        [TranscriptSegment(start=0.0, end=2.0, text="Use OpenAI API.")],
        [TranscriptSegment(start=0.0, end=2.0, text="使用 OpenAI API 生成 SRT。")],
    )

    assert plan[0].zh_text == "使用 OpenAI API 生成 SRT。"
    assert plan[0].tts_text == "使用欧喷诶艾诶屁艾生成艾丝阿提。"
    assert dump_dubbing_plan(plan)[0]["tts_text"] == "使用欧喷诶艾诶屁艾生成艾丝阿提。"
