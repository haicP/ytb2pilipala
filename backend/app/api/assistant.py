from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.repositories import TaskRepository
from backend.app.runner.prompts import DEFAULT_ASSISTANT_PROMPTS
from backend.app.schemas import AssistantSettingsPatchRequest, AssistantSettingsResponse

router = APIRouter(prefix="/assistant", tags=["assistant"])

ASSISTANT_FIELD_TO_SETTING_KEY = {
    "base_url": "assistant_base_url",
    "api_key": "assistant_api_key",
    "model_id": "assistant_model_id",
    "postprocess_prompt": "assistant_postprocess_prompt",
    "translation_prompt": "assistant_translation_prompt",
    "metadata_prompt": "assistant_metadata_prompt",
}

DEFAULT_ASSISTANT_SETTINGS = {
    "assistant_base_url": "",
    "assistant_api_key": "",
    "assistant_model_id": "",
    **DEFAULT_ASSISTANT_PROMPTS,
}


def _assistant_settings_response(repo: TaskRepository) -> AssistantSettingsResponse:
    settings = repo.get_app_settings(tuple(ASSISTANT_FIELD_TO_SETTING_KEY.values()))
    values = {}
    for field_name, setting_key in ASSISTANT_FIELD_TO_SETTING_KEY.items():
        values[field_name] = settings.get(setting_key, DEFAULT_ASSISTANT_SETTINGS[setting_key])

    return AssistantSettingsResponse(
        base_url=values["base_url"],
        api_key=values["api_key"],
        model_id=values["model_id"],
        postprocess_prompt=values["postprocess_prompt"],
        translation_prompt=values["translation_prompt"],
        metadata_prompt=values["metadata_prompt"],
        defaults={
            "postprocess_prompt": DEFAULT_ASSISTANT_PROMPTS["assistant_postprocess_prompt"],
            "translation_prompt": DEFAULT_ASSISTANT_PROMPTS["assistant_translation_prompt"],
            "metadata_prompt": DEFAULT_ASSISTANT_PROMPTS["assistant_metadata_prompt"],
        },
        updated_at=repo.latest_setting_timestamp(tuple(ASSISTANT_FIELD_TO_SETTING_KEY.values())),
    )


@router.get("/settings", response_model=AssistantSettingsResponse)
def get_assistant_settings(db: Session = Depends(get_db_session)) -> AssistantSettingsResponse:
    repo = TaskRepository(db)
    return _assistant_settings_response(repo)


@router.patch("/settings", response_model=AssistantSettingsResponse)
def patch_assistant_settings(
    payload: AssistantSettingsPatchRequest,
    db: Session = Depends(get_db_session),
) -> AssistantSettingsResponse:
    repo = TaskRepository(db)
    updates = {
        "assistant_base_url": payload.base_url,
        "assistant_api_key": payload.api_key,
        "assistant_model_id": payload.model_id,
        "assistant_postprocess_prompt": payload.postprocess_prompt,
        "assistant_translation_prompt": payload.translation_prompt,
        "assistant_metadata_prompt": payload.metadata_prompt,
    }
    repo.update_app_settings(updates)
    return _assistant_settings_response(repo)
