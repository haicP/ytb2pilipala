import base64
import io
import wave

from sqlalchemy.orm import sessionmaker

from backend.app.models import AppSetting, utc_now
from backend.app.runner.tts import (
    MIMO_TTS_CHINESE_SPEECH_PROMPT,
    VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES,
    OpenAISpeechClient,
    XiaomiMiMoSpeechClient,
    build_voice_clone_reference,
    compress_wav_to_duration,
    default_speech_client,
    trim_pcm16_silence,
)


class ChoiceStub:
    def __init__(self, data: str):
        self.message = MessageStub(data)


class MessageStub:
    def __init__(self, data: str):
        self.audio = AudioStub(data)


class AudioStub:
    def __init__(self, data: str):
        self.data = data


class CompletionsStub:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return CompletionStub(wav_base64_from_pcm16(b"\x01\x00\x02\x00\x03\x00\x04\x00"))


class CompletionStub:
    def __init__(self, data: str):
        self.choices = [ChoiceStub(data)]


class ChatStub:
    def __init__(self):
        self.completions = CompletionsStub()


class OpenAIStub:
    def __init__(self):
        self.chat = ChatStub()


class SpeechStub:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return wav_bytes_from_pcm16(b"\x07\x00\x08\x00")


class AudioSpeechStub:
    def __init__(self):
        self.speech = SpeechStub()


class OpenAITtsStub(OpenAIStub):
    def __init__(self):
        super().__init__()
        self.audio = AudioSpeechStub()


def wav_base64_from_pcm16(pcm_bytes: bytes, sample_rate: int = 24000) -> str:
    return base64.b64encode(wav_bytes_from_pcm16(pcm_bytes, sample_rate)).decode("ascii")


def wav_bytes_from_pcm16(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm_bytes)
    return buffer.getvalue()


def test_trim_pcm16_silence_keeps_padding_around_speech():
    leading = b"\x00\x00" * 100
    speech = bytes.fromhex("1027") * 50
    trailing = b"\x00\x00" * 100

    trimmed = trim_pcm16_silence(
        leading + speech + trailing,
        1000,
        threshold=300,
        padding_seconds=0.01,
    )

    assert trimmed == (b"\x00\x00" * 10) + speech + (b"\x00\x00" * 10)


def test_trim_pcm16_silence_keeps_all_silence_audio():
    pcm = b"\x00\x00" * 100

    assert trim_pcm16_silence(pcm, 1000) == pcm


def test_xiaomi_mimo_speech_client_reads_non_streaming_wav_response():
    client = XiaomiMiMoSpeechClient(
        api_key="mimo-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-tts",
        voice="冰糖",
        style_prompt="请自然朗读。",
    )
    openai_stub = OpenAIStub()
    client._client = openai_stub

    audio = client.synthesize_pcm16("第一句。\n第二句。")

    assert audio == b"\x01\x00\x02\x00\x03\x00\x04\x00"
    assert openai_stub.chat.completions.calls == [
        {
            "model": "mimo-v2.5-tts",
            "messages": [
                {"role": "user", "content": f"请自然朗读。\n{MIMO_TTS_CHINESE_SPEECH_PROMPT}"},
                {"role": "assistant", "content": "第一句。\n第二句。"},
            ],
            "audio": {"format": "wav", "voice": "冰糖"},
        }
    ]


def test_xiaomi_mimo_speech_client_configures_openai_timeout(monkeypatch):
    created_clients = []

    class OpenAIFactoryStub:
        def __init__(self, **kwargs):
            created_clients.append(kwargs)
            self.chat = ChatStub()

    monkeypatch.setattr("builtins.__import__", __import__)
    monkeypatch.setattr("backend.app.runner.tts._saved_tts_settings", lambda: {})

    client = XiaomiMiMoSpeechClient(
        api_key="mimo-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-tts",
        voice="冰糖",
        style_prompt="",
        timeout_seconds=12.5,
    )

    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=OpenAIFactoryStub))

    openai_client = client._openai()

    assert openai_client.chat.completions is not None
    assert created_clients == [
        {
            "api_key": "mimo-key",
            "base_url": "https://api.xiaomimimo.com/v1",
            "timeout": 12.5,
        }
    ]


def test_openai_speech_client_calls_standard_audio_speech_endpoint():
    client = OpenAISpeechClient(
        api_key="openai-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini-tts",
        voice="alloy",
        instructions="请自然朗读。",
        speed=1.15,
    )
    openai_stub = OpenAITtsStub()
    client._client = openai_stub

    audio = client.synthesize_pcm16("第一句。")

    assert audio == b"\x07\x00\x08\x00"
    assert openai_stub.audio.speech.calls == [
        {
            "model": "gpt-4o-mini-tts",
            "voice": "alloy",
            "input": "第一句。",
            "instructions": "请自然朗读。",
            "response_format": "wav",
            "speed": 1.15,
        }
    ]


def test_openai_speech_client_omits_blank_instructions():
    client = OpenAISpeechClient(
        api_key="openai-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini-tts",
        voice="alloy",
        instructions="",
        speed=1.0,
    )
    openai_stub = OpenAITtsStub()
    client._client = openai_stub

    client.synthesize_pcm16("第一句。")

    assert "instructions" not in openai_stub.audio.speech.calls[0]


def test_openai_speech_client_prefers_saved_key_and_falls_back_to_openai_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_TTS_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")
    monkeypatch.setattr(
        "backend.app.runner.tts._saved_tts_settings",
        lambda: {
            "openai_tts_base_url": "https://saved-openai.example.com/v1",
            "openai_tts_model": "saved-tts",
            "openai_tts_voice": "verse",
            "openai_tts_instructions": "保存说明",
            "openai_tts_speed": "1.2",
        },
    )

    client = OpenAISpeechClient()

    assert client.api_key == "env-openai-key"
    assert client.base_url == "https://saved-openai.example.com/v1"
    assert client.model == "saved-tts"
    assert client.voice == "verse"
    assert client.instructions == "保存说明"
    assert client.speed == 1.2


def test_default_speech_client_uses_saved_provider(monkeypatch):
    monkeypatch.setattr(
        "backend.app.runner.tts._saved_tts_settings",
        lambda: {"tts_provider": "openai"},
    )
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")

    client = default_speech_client()

    assert isinstance(client, OpenAISpeechClient)


def test_xiaomi_mimo_speech_client_sends_voiceclone_data_uri(tmp_path):
    reference_path = tmp_path / "voice_clone_reference.wav"
    with wave.open(str(reference_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x01\x00" * 160)
    reference = build_voice_clone_reference(reference_path)
    client = XiaomiMiMoSpeechClient(
        api_key="mimo-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-tts-voiceclone",
        voice="冰糖",
        style_prompt="请自然朗读。",
    )
    openai_stub = OpenAIStub()
    client._client = openai_stub

    audio = client.synthesize_pcm16("第一句。", voice_reference=reference)

    assert audio == b"\x01\x00\x02\x00\x03\x00\x04\x00"
    request_audio = openai_stub.chat.completions.calls[0]["audio"]
    assert request_audio["format"] == "wav"
    assert request_audio["voice"].startswith("data:audio/wav;base64,")
    assert request_audio["voice"].split(",", 1)[1] == reference.base64_audio


def test_xiaomi_mimo_speech_client_validates_pure_base64_size_only(monkeypatch):
    client = XiaomiMiMoSpeechClient(
        api_key="mimo-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-tts-voiceclone",
        voice="冰糖",
        style_prompt="",
    )
    openai_stub = OpenAIStub()
    client._client = openai_stub
    base64_audio = "a" * VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES

    client.synthesize_pcm16("第一句。", voice_reference=f"data:audio/wav;base64,{base64_audio}")

    assert openai_stub.chat.completions.calls[0]["audio"]["voice"].endswith(base64_audio)


def test_xiaomi_mimo_speech_client_accepts_audio_data_uri_response():
    client = XiaomiMiMoSpeechClient(
        api_key="mimo-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-tts",
        voice="冰糖",
        style_prompt="",
    )
    openai_stub = OpenAIStub()
    client._client = openai_stub
    data = wav_base64_from_pcm16(b"\x05\x00\x06\x00")
    openai_stub.chat.completions.create = lambda **kwargs: CompletionStub(
        f"data:audio/wav;base64,{data}"
    )

    audio = client.synthesize_pcm16("第一句。")

    assert audio == b"\x05\x00\x06\x00"


def test_xiaomi_mimo_speech_client_rejects_invalid_wav_response():
    client = XiaomiMiMoSpeechClient(
        api_key="mimo-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-tts",
        voice="冰糖",
        style_prompt="",
    )
    openai_stub = OpenAIStub()
    client._client = openai_stub
    openai_stub.chat.completions.create = lambda **kwargs: CompletionStub(
        base64.b64encode(b"not wav").decode("ascii")
    )

    try:
        client.synthesize_pcm16("第一句。")
    except RuntimeError as exc:
        assert "不是合法 WAV 数据" in str(exc)
    else:
        raise AssertionError("expected invalid wav response to fail")


def test_xiaomi_mimo_speech_client_rejects_oversized_voiceclone_reference():
    client = XiaomiMiMoSpeechClient(
        api_key="mimo-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-tts-voiceclone",
        voice="冰糖",
        style_prompt="",
    )
    client._client = OpenAIStub()
    oversized_base64 = "a" * (VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES + 1)

    try:
        client.synthesize_pcm16(
            "第一句。",
            voice_reference=f"data:audio/wav;base64,{oversized_base64}",
        )
    except RuntimeError as exc:
        assert "Base64 字符串过大" in str(exc)
    else:
        raise AssertionError("expected oversized voiceclone reference to fail")


def test_compress_wav_to_duration_uses_ffmpeg_atempo_chain(tmp_path, monkeypatch):
    source_path = tmp_path / "source.wav"
    target_path = tmp_path / "source.compressed.wav"
    with wave.open(str(source_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\x01\x00" * 36_000)

    calls = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)
        target_path.write_bytes(source_path.read_bytes())

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("backend.app.runner.tts.subprocess.run", fake_run)

    result_path = compress_wav_to_duration(source_path, target_duration_seconds=1.0)

    assert result_path == target_path
    assert calls == [
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-filter:a",
            "atempo=1.500000",
            str(target_path),
        ]
    ]


def test_xiaomi_mimo_speech_client_prefers_saved_settings_over_env(db_session, monkeypatch):
    monkeypatch.setenv("MIMO_BASE_URL", "https://env-tts.example.com/v1")
    monkeypatch.setenv("MIMO_API_KEY", "env-tts-key")
    monkeypatch.setenv("MIMO_TTS_MODEL", "env-model")
    monkeypatch.setenv("MIMO_TTS_VOICE", "环境音色")
    monkeypatch.setenv("MIMO_TTS_STYLE_PROMPT", "环境风格")

    db_session.add_all(
        [
            AppSetting(
                key="mimo_base_url",
                value="https://saved-tts.example.com/v1",
                updated_at=utc_now(),
            ),
            AppSetting(key="mimo_api_key", value="saved-tts-key", updated_at=utc_now()),
            AppSetting(key="mimo_tts_model", value="saved-model", updated_at=utc_now()),
            AppSetting(key="mimo_tts_voice", value="保存音色", updated_at=utc_now()),
            AppSetting(key="mimo_tts_style_prompt", value="保存风格", updated_at=utc_now()),
        ]
    )
    db_session.commit()
    testing_session = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr("backend.app.runner.tts.SessionLocal", testing_session)

    client = XiaomiMiMoSpeechClient()

    assert client.base_url == "https://saved-tts.example.com/v1"
    assert client.api_key == "saved-tts-key"
    assert client.model == "saved-model"
    assert client.voice == "保存音色"
    assert client.style_prompt == "保存风格"


def test_xiaomi_mimo_speech_client_falls_back_to_env_when_no_saved_settings(monkeypatch):
    monkeypatch.setattr("backend.app.runner.tts._saved_tts_settings", lambda: {})
    monkeypatch.setenv("MIMO_BASE_URL", "https://env-tts.example.com/v1")
    monkeypatch.setenv("MIMO_API_KEY", "env-tts-key")
    monkeypatch.setenv("MIMO_TTS_MODEL", "env-model")
    monkeypatch.setenv("MIMO_TTS_VOICE", "环境音色")
    monkeypatch.setenv("MIMO_TTS_STYLE_PROMPT", "环境风格")

    client = XiaomiMiMoSpeechClient()

    assert client.base_url == "https://env-tts.example.com/v1"
    assert client.api_key == "env-tts-key"
    assert client.model == "env-model"
    assert client.voice == "环境音色"
    assert client.style_prompt == "环境风格"
