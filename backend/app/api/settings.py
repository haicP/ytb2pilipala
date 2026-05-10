import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db_session
from backend.app.models import AppSetting, utc_now
from backend.app.repositories import TaskRepository
from backend.app.schemas import (
    TTS_PROVIDER_MIMO,
    TTS_PROVIDER_OPENAI,
    TTS_PROVIDERS,
    SettingsPatchRequest,
    SettingsResponse,
)
from backend.app.youtube_cookies import is_valid_youtube_cookies_file

router = APIRouter(prefix="/settings", tags=["settings"])

ALLOWED_SETTINGS_KEYS = (
    "default_category",
    "dry_run_step_delay_ms",
    "assistant_base_url",
    "assistant_api_key",
    "assistant_model_id",
    "image_model_id",
    "tts_provider",
    "mimo_base_url",
    "mimo_api_key",
    "mimo_tts_model",
    "mimo_tts_voice",
    "mimo_tts_style_prompt",
    "mimo_tts_timeout_seconds",
    "mimo_tts_concurrency",
    "tts_concurrency",
    "openai_tts_base_url",
    "openai_tts_api_key",
    "openai_tts_model",
    "openai_tts_voice",
    "openai_tts_instructions",
    "openai_tts_speed",
)
ASSISTANT_LLM_SETTING_KEYS = (
    "assistant_base_url",
    "assistant_api_key",
    "assistant_model_id",
    "image_model_id",
)
TTS_SETTING_KEYS = (
    "tts_provider",
    "mimo_base_url",
    "mimo_api_key",
    "mimo_tts_model",
    "mimo_tts_voice",
    "mimo_tts_style_prompt",
    "mimo_tts_timeout_seconds",
    "mimo_tts_concurrency",
    "tts_concurrency",
    "openai_tts_base_url",
    "openai_tts_api_key",
    "openai_tts_model",
    "openai_tts_voice",
    "openai_tts_instructions",
    "openai_tts_speed",
)


def _load_saved_settings(db: Session) -> dict[str, str]:
    statement = select(AppSetting).where(AppSetting.key.in_(ALLOWED_SETTINGS_KEYS))
    rows = db.execute(statement).scalars().all()
    return {row.key: row.value for row in rows}


def _current_tts_provider(settings, tts_settings: dict[str, str]) -> str:
    provider = tts_settings.get("tts_provider", "") or settings.tts_provider
    return provider if provider in TTS_PROVIDERS else TTS_PROVIDER_MIMO


def _tts_base_url_configured(settings, tts_settings: dict[str, str], provider: str) -> bool:
    if provider == TTS_PROVIDER_OPENAI:
        return bool(tts_settings.get("openai_tts_base_url", "") or settings.openai_tts_base_url)
    return bool(tts_settings.get("mimo_base_url", "") or settings.mimo_base_url)


def _tts_api_key_configured(settings, tts_settings: dict[str, str], provider: str) -> bool:
    if provider == TTS_PROVIDER_OPENAI:
        return bool(
            tts_settings.get("openai_tts_api_key", "")
            or settings.openai_tts_api_key
            or settings.openai_api_key
        )
    return bool(tts_settings.get("mimo_api_key", "") or settings.mimo_api_key)


@router.get("", response_model=SettingsResponse)
def get_settings_summary(db: Session = Depends(get_db_session)) -> SettingsResponse:
    settings = get_settings()
    saved_settings = _load_saved_settings(db)
    assistant_settings = TaskRepository(db).get_app_settings(ASSISTANT_LLM_SETTING_KEYS)
    tts_settings = TaskRepository(db).get_app_settings(TTS_SETTING_KEYS)
    tts_provider = _current_tts_provider(settings, tts_settings)
    return SettingsResponse(
        dependencies={
            "yt_dlp": shutil.which("yt-dlp") is not None,
            "ffmpeg": shutil.which("ffmpeg") is not None,
        },
        config={
            "api2key_base_url": bool(
                settings.api2key_base_url or assistant_settings.get("assistant_base_url", "")
            ),
            "llm_key": bool(
                settings.llm_api_key or assistant_settings.get("assistant_api_key", "")
            ),
            "tts_base_url": _tts_base_url_configured(settings, tts_settings, tts_provider),
            "tts_api_key": _tts_api_key_configured(settings, tts_settings, tts_provider),
            "bilibili_credential_source": bool(settings.bilibili_credential_source),
            "youtube_cookies_file": is_valid_youtube_cookies_file(settings.youtube_cookies_path),
        },
        settings=saved_settings,
    )


@router.patch("", response_model=SettingsResponse)
def patch_settings(
    payload: SettingsPatchRequest, db: Session = Depends(get_db_session)
) -> SettingsResponse:
    updates = payload.model_dump(exclude_none=True)
    if updates:
        for key, value in updates.items():
            setting = db.get(AppSetting, key)
            if setting is None:
                setting = AppSetting(key=key, value=str(value), updated_at=utc_now())
                db.add(setting)
            else:
                setting.value = str(value)
                setting.updated_at = utc_now()
        db.commit()

    return get_settings_summary(db)
