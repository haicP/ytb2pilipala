import base64
import binascii
import io
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.repositories import TaskRepository

TTS_PROVIDER_MIMO = "mimo_v2_5_tts"
TTS_PROVIDER_OPENAI = "openai"
TTS_PROVIDER_DEFAULT = TTS_PROVIDER_MIMO
TTS_PROVIDERS = {TTS_PROVIDER_MIMO, TTS_PROVIDER_OPENAI}
VOICE_CLONE_MODEL = "mimo-v2.5-tts-voiceclone"
VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES = int(9.5 * 1024 * 1024)
VOICE_CLONE_REFERENCE_MIME_TYPE = "audio/wav"
MIMO_TTS_CHINESE_SPEECH_PROMPT = (
    "请按中文视频解说口播，遇到英文术语按中文释义或中文读法自然朗读，"
    "不要逐字母异常拖读。"
)


@dataclass(frozen=True)
class VoiceCloneReference:
    path: Path
    mime_type: str
    base64_audio: str
    file_size_bytes: int
    base64_size_bytes: int
    duration_seconds: float
    truncated: bool

    @property
    def data_uri(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64_audio}"


class SpeechSynthesisClient(Protocol):
    sample_rate: int
    tts_provider: str

    def synthesize_pcm16(
        self,
        text: str,
        voice_reference: VoiceCloneReference | str | None = None,
    ) -> bytes:
        raise NotImplementedError


class XiaomiMiMoSpeechClient:
    sample_rate = 24000
    tts_provider = TTS_PROVIDER_MIMO

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        style_prompt: str | None = None,
        timeout_seconds: float | None = None,
    ):
        settings = get_settings()
        saved_settings = _saved_tts_settings()
        self.api_key = (
            api_key
            if api_key is not None
            else saved_settings.get("mimo_api_key", "") or settings.mimo_api_key
        )
        self.base_url = (
            base_url
            if base_url is not None
            else saved_settings.get("mimo_base_url", "") or settings.mimo_base_url
        )
        self.model = (
            model
            if model is not None
            else saved_settings.get("mimo_tts_model", "") or settings.mimo_tts_model
        )
        self.voice = (
            voice
            if voice is not None
            else saved_settings.get("mimo_tts_voice", "") or settings.mimo_tts_voice
        )
        self.style_prompt = (
            style_prompt
            if style_prompt is not None
            else saved_settings.get("mimo_tts_style_prompt", "") or settings.mimo_tts_style_prompt
        )
        saved_timeout = saved_settings.get("mimo_tts_timeout_seconds", "")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else _parse_timeout_seconds(saved_timeout, settings.mimo_tts_timeout_seconds)
        )
        self._client = None
        self._client_lock = Lock()

    @property
    def is_voice_clone_model(self) -> bool:
        return self.model.strip().lower() == VOICE_CLONE_MODEL

    def synthesize_pcm16(
        self,
        text: str,
        voice_reference: VoiceCloneReference | str | None = None,
    ) -> bytes:
        cleaned_text = text.strip()
        if not cleaned_text:
            raise RuntimeError("TTS 文本为空，无法合成配音")
        audio_payload = {
            "format": "wav",
            "voice": self._request_voice(voice_reference),
        }
        response = self._openai().chat.completions.create(
            model=self.model,
            messages=self._messages(cleaned_text),
            audio=audio_payload,
        )
        return _decode_wav_audio_data_to_pcm16(_completion_audio_data(response), self.sample_rate)

    def _request_voice(self, voice_reference: VoiceCloneReference | str | None) -> str:
        if not self.is_voice_clone_model:
            return self.voice

        if voice_reference is None:
            raise RuntimeError("mimo-v2.5-tts-voiceclone 需要声音样本，无法使用内置音色。")
        if isinstance(voice_reference, VoiceCloneReference):
            _validate_voice_clone_base64_size(voice_reference.base64_audio)
            return voice_reference.data_uri
        if isinstance(voice_reference, str):
            base64_audio = _pure_base64_audio(voice_reference)
            _validate_voice_clone_base64_size(base64_audio)
            if voice_reference.startswith("data:"):
                return voice_reference
            return f"data:{VOICE_CLONE_REFERENCE_MIME_TYPE};base64,{voice_reference}"
        raise RuntimeError("声音样本格式无效，无法执行小米 voiceclone 配音。")

    def _messages(self, text: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        prompt = _style_prompt_with_chinese_speech_hint(self.style_prompt)
        if prompt:
            messages.append({"role": "user", "content": prompt})
        messages.append({"role": "assistant", "content": text})
        return messages

    def _openai(self):
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    if not self.api_key:
                        raise RuntimeError("MIMO_API_KEY 未配置，无法执行小米 TTS 配音")
                    try:
                        from openai import OpenAI
                    except ImportError as exc:
                        raise RuntimeError(
                            "openai package is required for Xiaomi MiMo TTS calls"
                        ) from exc
                    self._client = OpenAI(
                        api_key=self.api_key,
                        base_url=self.base_url,
                        timeout=self.timeout_seconds,
                    )
        return self._client


class OpenAISpeechClient:
    sample_rate = 24000
    tts_provider = TTS_PROVIDER_OPENAI
    is_voice_clone_model = False

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
        speed: float | None = None,
        timeout_seconds: float | None = None,
    ):
        settings = get_settings()
        saved_settings = _saved_tts_settings()
        self.api_key = (
            api_key
            if api_key is not None
            else saved_settings.get("openai_tts_api_key", "")
            or settings.openai_tts_api_key
            or settings.openai_api_key
        )
        self.base_url = (
            base_url
            if base_url is not None
            else saved_settings.get("openai_tts_base_url", "") or settings.openai_tts_base_url
        )
        self.model = (
            model
            if model is not None
            else saved_settings.get("openai_tts_model", "") or settings.openai_tts_model
        )
        self.voice = (
            voice
            if voice is not None
            else saved_settings.get("openai_tts_voice", "") or settings.openai_tts_voice
        )
        self.instructions = (
            instructions
            if instructions is not None
            else saved_settings.get("openai_tts_instructions", "")
            or settings.openai_tts_instructions
        )
        saved_speed = saved_settings.get("openai_tts_speed", "")
        self.speed = (
            speed if speed is not None else _parse_speed(saved_speed, settings.openai_tts_speed)
        )
        saved_timeout = saved_settings.get("openai_tts_timeout_seconds", "")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else _parse_timeout_seconds(saved_timeout, settings.openai_tts_timeout_seconds)
        )
        self._client = None
        self._client_lock = Lock()

    def synthesize_pcm16(
        self,
        text: str,
        voice_reference: VoiceCloneReference | str | None = None,
    ) -> bytes:
        cleaned_text = text.strip()
        if not cleaned_text:
            raise RuntimeError("TTS 文本为空，无法合成配音")
        request = {
            "model": self.model,
            "voice": self.voice,
            "input": cleaned_text,
            "response_format": "wav",
            "speed": self.speed,
        }
        if self.instructions.strip():
            request["instructions"] = self.instructions
        response = self._openai().audio.speech.create(**request)
        return _decode_wav_bytes_to_pcm16(
            _speech_response_bytes(response),
            self.sample_rate,
            "OpenAI TTS",
        )

    def _openai(self):
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    if not self.api_key:
                        raise RuntimeError(
                            "OPENAI_TTS_API_KEY 或 OPENAI_API_KEY 未配置，无法执行 OpenAI TTS 配音"
                        )
                    try:
                        from openai import OpenAI
                    except ImportError as exc:
                        raise RuntimeError(
                            "openai package is required for OpenAI TTS calls"
                        ) from exc
                    self._client = OpenAI(
                        api_key=self.api_key,
                        base_url=self.base_url,
                        timeout=self.timeout_seconds,
                    )
        return self._client


def default_speech_client() -> SpeechSynthesisClient:
    settings = get_settings()
    saved_settings = _saved_tts_settings()
    provider = _normalize_tts_provider(
        saved_settings.get("tts_provider", "") or settings.tts_provider
    )
    if provider == TTS_PROVIDER_OPENAI:
        return OpenAISpeechClient()
    return XiaomiMiMoSpeechClient()


def _saved_tts_settings() -> dict[str, str]:
    session = SessionLocal()
    try:
        repo = TaskRepository(session)
        return repo.get_app_settings(
            (
                "tts_provider",
                "mimo_base_url",
                "mimo_api_key",
                "mimo_tts_model",
                "mimo_tts_voice",
                "mimo_tts_style_prompt",
                "mimo_tts_timeout_seconds",
                "openai_tts_base_url",
                "openai_tts_api_key",
                "openai_tts_model",
                "openai_tts_voice",
                "openai_tts_instructions",
                "openai_tts_speed",
                "openai_tts_timeout_seconds",
            )
        )
    finally:
        session.close()


def _normalize_tts_provider(value: str) -> str:
    return value if value in TTS_PROVIDERS else TTS_PROVIDER_DEFAULT


def _parse_timeout_seconds(value: str, default: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = default
    if timeout <= 0:
        timeout = default
    return timeout


def _parse_speed(value: str, default: float) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        speed = default
    if speed < 0.25 or speed > 4.0:
        speed = default
    return speed


def _style_prompt_with_chinese_speech_hint(style_prompt: str) -> str:
    prompt = style_prompt.strip()
    if MIMO_TTS_CHINESE_SPEECH_PROMPT in prompt:
        return prompt
    if prompt:
        return f"{prompt}\n{MIMO_TTS_CHINESE_SPEECH_PROMPT}"
    return MIMO_TTS_CHINESE_SPEECH_PROMPT


def _completion_audio_data(response) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        raise RuntimeError("小米 TTS 返回的音频数据为空")
    message = _field(choices[0], "message")
    audio = _field(message, "audio")
    data = _field(audio, "data")
    if not isinstance(data, str) or not data:
        raise RuntimeError("小米 TTS 返回的音频数据为空")
    return data


def _field(value, name: str):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _decode_wav_audio_data_to_pcm16(audio_data: str, expected_sample_rate: int) -> bytes:
    if audio_data.startswith("data:"):
        if "," not in audio_data:
            raise RuntimeError("小米 TTS 返回的音频 Data URI 缺少 Base64 内容")
        audio_data = audio_data.split(",", 1)[1]
    try:
        wav_bytes = base64.b64decode(audio_data, validate=True)
    except binascii.Error as exc:
        raise RuntimeError("小米 TTS 返回的音频数据不是合法 Base64") from exc

    return _decode_wav_bytes_to_pcm16(wav_bytes, expected_sample_rate, "小米 TTS")


def _speech_response_bytes(response) -> bytes:
    if isinstance(response, bytes):
        return response
    if hasattr(response, "read"):
        data = response.read()
        if isinstance(data, bytes):
            return data
    if hasattr(response, "content"):
        data = response.content
        if isinstance(data, bytes):
            return data
    if hasattr(response, "iter_bytes"):
        return b"".join(response.iter_bytes())
    raise RuntimeError("OpenAI TTS 返回的音频响应无法解析")


def _decode_wav_bytes_to_pcm16(
    wav_bytes: bytes,
    expected_sample_rate: int,
    provider_label: str,
) -> bytes:
    try:
        import wave

        with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            if channels != 1:
                raise RuntimeError(
                    f"{provider_label} 返回的 WAV 声道数异常：期望 1，实际 {channels}"
                )
            if sample_width != 2:
                raise RuntimeError(
                    f"{provider_label} 返回的 WAV 采样宽度异常："
                    f"期望 16-bit，实际 {sample_width * 8}-bit"
                )
            if sample_rate != expected_sample_rate:
                raise RuntimeError(
                    f"{provider_label} 返回的 WAV 采样率异常："
                    f"期望 {expected_sample_rate}，实际 {sample_rate}"
                )
            pcm_bytes = handle.readframes(handle.getnframes())
    except (EOFError, wave.Error) as exc:
        raise RuntimeError(f"{provider_label} 返回的音频不是合法 WAV 数据") from exc

    if not pcm_bytes:
        raise RuntimeError(f"{provider_label} 返回的音频数据为空")
    return pcm_bytes


def write_pcm16_wav(path: Path, pcm_bytes: bytes, sample_rate: int = 24000) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm_bytes)


def build_voice_clone_reference(
    path: Path,
    *,
    truncated: bool = False,
    mime_type: str = VOICE_CLONE_REFERENCE_MIME_TYPE,
) -> VoiceCloneReference:
    base64_audio = base64.b64encode(path.read_bytes()).decode("ascii")
    return VoiceCloneReference(
        path=path,
        mime_type=mime_type,
        base64_audio=base64_audio,
        file_size_bytes=path.stat().st_size,
        base64_size_bytes=len(base64_audio.encode("ascii")),
        duration_seconds=wav_duration_seconds(path),
        truncated=truncated,
    )


def _pure_base64_audio(voice_reference: str) -> str:
    if voice_reference.startswith("data:"):
        if "," not in voice_reference:
            raise RuntimeError("声音样本 Data URI 缺少 Base64 内容。")
        return voice_reference.split(",", 1)[1]
    return voice_reference


def _validate_voice_clone_base64_size(base64_audio: str) -> None:
    base64_size = len(base64_audio.encode("ascii"))
    if base64_size > VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES:
        raise RuntimeError(
            "声音样本 Base64 字符串过大："
            f"{base64_size} bytes，限制为 {VOICE_CLONE_REFERENCE_BASE64_LIMIT_BYTES} bytes。"
        )


def pcm16_duration_seconds(pcm_bytes: bytes, sample_rate: int) -> float:
    frame_count = len(pcm_bytes) // 2
    return frame_count / sample_rate


def silence_pcm16(duration_seconds: float, sample_rate: int) -> bytes:
    frame_count = max(0, round(duration_seconds * sample_rate))
    return b"\x00\x00" * frame_count


def trim_pcm16(pcm_bytes: bytes, max_duration_seconds: float, sample_rate: int) -> bytes:
    max_frames = max(0, round(max_duration_seconds * sample_rate))
    return pcm_bytes[: max_frames * 2]


def trim_pcm16_silence(
    pcm_bytes: bytes,
    sample_rate: int,
    *,
    threshold: int = 300,
    padding_seconds: float = 0.08,
) -> bytes:
    if not pcm_bytes:
        return pcm_bytes

    sample_count = len(pcm_bytes) // 2
    if sample_count <= 0:
        return b""

    start = 0
    end = sample_count - 1
    while start <= end and _pcm16_abs_sample(pcm_bytes, start) <= threshold:
        start += 1
    while end >= start and _pcm16_abs_sample(pcm_bytes, end) <= threshold:
        end -= 1
    if start > end:
        return pcm_bytes

    padding_frames = max(0, round(padding_seconds * sample_rate))
    start = max(0, start - padding_frames)
    end = min(sample_count - 1, end + padding_frames)
    if start == 0 and end == sample_count - 1:
        return pcm_bytes
    return pcm_bytes[start * 2 : (end + 1) * 2]


def _pcm16_abs_sample(pcm_bytes: bytes, frame_index: int) -> int:
    offset = frame_index * 2
    return abs(int.from_bytes(pcm_bytes[offset : offset + 2], byteorder="little", signed=True))


def compress_wav_to_duration(source_path: Path, target_duration_seconds: float) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg 不可用，无法压缩超长配音片段。")
    if target_duration_seconds <= 0:
        raise RuntimeError("目标时长必须大于 0 秒。")

    source_duration = wav_duration_seconds(source_path)
    if source_duration <= 0:
        raise RuntimeError("源音频时长无效，无法压缩。")

    speed_ratio = source_duration / target_duration_seconds
    filter_value = _atempo_filter_chain(speed_ratio)
    target_path = source_path.with_name(f"{source_path.stem}.compressed.wav")
    process = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-filter:a",
            filter_value,
            str(target_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or "ffmpeg 压缩配音片段失败"
        raise RuntimeError(detail[-1000:])
    return target_path


def wav_duration_seconds(path: Path) -> float:
    import wave

    with wave.open(str(path), "rb") as handle:
        frame_rate = handle.getframerate()
        if frame_rate <= 0:
            return 0.0
        return handle.getnframes() / frame_rate


def read_wav_pcm16(path: Path) -> tuple[bytes, int]:
    import wave

    with wave.open(str(path), "rb") as handle:
        return handle.readframes(handle.getnframes()), handle.getframerate()


def _atempo_filter_chain(speed_ratio: float) -> str:
    if speed_ratio <= 0:
        raise RuntimeError("atempo 倍率必须大于 0。")
    factors: list[float] = []
    remaining = speed_ratio
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={factor:.6f}" for factor in factors)
