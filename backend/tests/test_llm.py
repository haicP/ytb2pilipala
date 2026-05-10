import json
from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker

from backend.app.models import AppSetting, utc_now
from backend.app.runner.llm import OpenAITranslationClient, OpenAITtsPhoneticRewriteClient
from backend.app.runner.prompts import DEFAULT_TRANSLATION_PROMPT
from backend.app.runner.subtitles import TranscriptSegment


class StubTranslationClient(OpenAITranslationClient):
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.system_prompts = []
        self.base_url = "https://api.example.com/v1"
        self.api_key = "sk-test"
        self.model = "gpt-test"
        self.translation_prompt = DEFAULT_TRANSLATION_PROMPT
        self._client = object()

    def _complete_translation_json(self, messages):
        self.system_prompts.append(messages[0]["content"])
        user_payload = json.loads(messages[1]["content"])
        self.calls.append(user_payload)
        if not self._responses:
            raise AssertionError("unexpected extra LLM call")
        return self._responses.pop(0)


class StubTtsRewriteClient(OpenAITtsPhoneticRewriteClient):
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.system_prompts = []
        self.batch_size = 50
        self.base_url = "https://api.example.com/v1"
        self.api_key = "sk-test"
        self.model = "gpt-test"
        self.translation_prompt = DEFAULT_TRANSLATION_PROMPT
        self._client = object()

    def _complete_tts_rewrite_json(self, messages):
        self.system_prompts.append(messages[0]["content"])
        user_payload = json.loads(messages[1]["content"])
        self.calls.append(user_payload)
        if not self._responses:
            raise AssertionError("unexpected extra LLM call")
        return self._responses.pop(0)


def _segments(count: int) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            start=float(index),
            end=float(index) + 0.8,
            text=f"segment-{index}",
        )
        for index in range(count)
    ]


def test_translate_segments_batches_large_payloads():
    segments = _segments(55)
    responses = [
        {
            "segments": [
                {"index": index, "start": segment.start, "end": segment.end, "text": f"ZH-{index}"}
                for index, segment in enumerate(segments[:50])
            ]
        },
        {
            "segments": [
                {
                    "index": index,
                    "start": segment.start,
                    "end": segment.end,
                    "text": f"ZH-{50 + index}",
                }
                for index, segment in enumerate(segments[50:])
            ]
        },
    ]
    client = StubTranslationClient(responses)

    translated = client.translate_segments(segments, "zh")

    assert len(client.calls) == 2
    assert len(client.calls[0]["segments"]) == 50
    assert len(client.calls[1]["segments"]) == 5
    assert DEFAULT_TRANSLATION_PROMPT in client.system_prompts[0]
    assert translated[0].text == "ZH-0"
    assert translated[-1].text == "ZH-54"


def test_translate_segments_retries_batch_when_response_misses_text():
    segments = _segments(3)
    responses = [
        {
            "segments": [
                {"index": 0, "start": 0.0, "end": 0.8, "text": "ZH-0"},
                {"index": 1, "start": 1.0, "end": 1.8, "text": "ZH-1"},
            ]
        },
        {
            "segments": [
                {"index": 0, "start": 0.0, "end": 0.8, "text": "ZH-0"},
                {"index": 1, "start": 1.0, "end": 1.8, "text": "ZH-1"},
                {"index": 2, "start": 2.0, "end": 2.8, "text": "ZH-2"},
            ]
        },
    ]
    client = StubTranslationClient(responses)

    translated = client.translate_segments(segments, "zh")

    assert len(client.calls) == 2
    assert [segment.text for segment in translated] == ["ZH-0", "ZH-1", "ZH-2"]


def test_openai_translation_client_streams_translation_completion():
    create_calls = []

    def create(**kwargs):
        create_calls.append(kwargs)
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content='{"segments": ['))
                    ]
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content='{"index": 0, "start": 0.0, "end": 0.8, "text": "你好"}'
                            )
                        )
                    ]
                ),
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="]}"))]),
            ]
        )

    client = OpenAITranslationClient.__new__(OpenAITranslationClient)
    client.model = "gpt-test"
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )

    content = client._complete_translation_json([{"role": "user", "content": "translate"}])

    assert create_calls[0]["stream"] is True
    assert create_calls[0]["response_format"] == {"type": "json_object"}
    assert content == {"segments": [{"index": 0, "start": 0.0, "end": 0.8, "text": "你好"}]}


def test_openai_translation_client_reads_saved_translation_prompt(db_session, monkeypatch):
    db_session.add(
        AppSetting(
            key="assistant_translation_prompt",
            value="请翻译成完整自然的中文句子。",
            updated_at=utc_now(),
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        "backend.app.runner.llm.get_settings",
        lambda: SimpleNamespace(api2key_base_url="", llm_api_key="sk-env", llm_model="gpt-env"),
    )
    testing_session = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr("backend.app.runner.llm.SessionLocal", testing_session)

    client = OpenAITranslationClient()

    assert client.translation_prompt == "请翻译成完整自然的中文句子。"


def test_openai_translation_client_uses_default_translation_prompt(monkeypatch):
    monkeypatch.setattr("backend.app.runner.llm._assistant_llm_settings", lambda: {})
    monkeypatch.setattr(
        "backend.app.runner.llm.get_settings",
        lambda: SimpleNamespace(api2key_base_url="", llm_api_key="sk-env", llm_model="gpt-env"),
    )

    client = OpenAITranslationClient()

    assert client.translation_prompt == DEFAULT_TRANSLATION_PROMPT


def test_tts_phonetic_rewrite_client_rewrites_english_and_keeps_protected_fragments():
    segments = [
        TranscriptSegment(
            start=0.0,
            end=1.0,
            text="使用 OpenAI API 生成 SRT，访问 https://example.com。",
        ),
        TranscriptSegment(start=1.0, end=2.0, text="运行 `npm run build`。"),
    ]
    client = StubTtsRewriteClient(
        [
            {
                "segments": [
                    {
                        "index": 0,
                        "tts_text": "使用欧喷诶艾诶屁艾生成艾丝阿提，访问 https://example.com。",
                        "replacements": [
                            {"original": "OpenAI", "replacement": "欧喷诶艾"},
                            {"original": "API", "replacement": "诶屁艾"},
                            {"original": "SRT", "replacement": "艾丝阿提"},
                        ],
                    },
                    {
                        "index": 1,
                        "tts_text": "运行 `npm run build`。",
                        "replacements": [],
                    },
                ]
            }
        ]
    )

    result = client.rewrite_segments(segments)

    assert "URL、邮箱地址、反引号包裹的代码片段必须原样保留" in client.system_prompts[0]
    assert client.calls == [
        {
            "segments": [
                {
                    "index": 0,
                    "text": "使用 OpenAI API 生成 SRT，访问 https://example.com。",
                },
                {"index": 1, "text": "运行 `npm run build`。"},
            ]
        }
    ]
    assert [segment.tts_text for segment in result.segments] == [
        "使用欧喷诶艾诶屁艾生成艾丝阿提，访问 https://example.com。",
        "运行 `npm run build`。",
    ]
    assert result.source == "llm_phonetic"
    assert result.detected_count == 5
    assert result.rewritten_count == 3
    assert result.protected_count == 2
    assert result.unresolved_count == 0


def test_tts_phonetic_rewrite_client_allows_residual_english_with_warning():
    segments = [TranscriptSegment(start=0.0, end=1.0, text="打开 Flux。")]
    client = StubTtsRewriteClient(
        [
            {
                "segments": [
                    {
                        "index": 0,
                        "tts_text": "打开 Flux。",
                        "replacements": [],
                    }
                ]
            }
        ]
    )

    result = client.rewrite_segments(segments)

    assert result.segments[0].tts_text == "打开 Flux。"
    assert result.unresolved_count == 1
    assert result.warning_count == 1
    assert result.warnings == ("LLM TTS rewrite left 1 English fragments in segment 0",)
