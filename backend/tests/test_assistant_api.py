from sqlalchemy.orm import sessionmaker

from backend.app.repositories import TaskRepository
from backend.app.runner.prompts import (
    DEFAULT_METADATA_PROMPT,
    DEFAULT_POSTPROCESS_PROMPT,
    DEFAULT_TRANSLATION_PROMPT,
)


def test_get_assistant_settings_returns_defaults_when_database_is_empty(client):
    response = client.get("/api/assistant/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_url"] == ""
    assert payload["api_key"] == ""
    assert payload["model_id"] == ""
    assert payload["postprocess_prompt"] == DEFAULT_POSTPROCESS_PROMPT
    assert payload["translation_prompt"] == DEFAULT_TRANSLATION_PROMPT
    assert payload["metadata_prompt"] == DEFAULT_METADATA_PROMPT
    assert payload["defaults"] == {
        "postprocess_prompt": DEFAULT_POSTPROCESS_PROMPT,
        "translation_prompt": DEFAULT_TRANSLATION_PROMPT,
        "metadata_prompt": DEFAULT_METADATA_PROMPT,
    }
    assert payload["updated_at"] is None


ASSISTANT_SETTING_KEYS = (
    "assistant_base_url",
    "assistant_api_key",
    "assistant_model_id",
    "assistant_postprocess_prompt",
    "assistant_translation_prompt",
    "assistant_metadata_prompt",
)


def test_patch_assistant_settings_persists_prompt_templates(client, db_session):
    update_payload = {
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-key",
        "model_id": "gpt-custom-1",
        "postprocess_prompt": "请清理字幕断句并保留技术术语。",
        "translation_prompt": "请将字幕翻译成自然中文。",
        "metadata_prompt": "请生成适合 B 站投稿的标题、简介和标签。",
    }

    patch_response = client.patch("/api/assistant/settings", json=update_payload)

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["base_url"] == update_payload["base_url"]
    assert patched["api_key"] == update_payload["api_key"]
    assert patched["model_id"] == update_payload["model_id"]
    assert patched["postprocess_prompt"] == update_payload["postprocess_prompt"]
    assert patched["translation_prompt"] == update_payload["translation_prompt"]
    assert patched["metadata_prompt"] == update_payload["metadata_prompt"]
    assert patched["defaults"] == {
        "postprocess_prompt": DEFAULT_POSTPROCESS_PROMPT,
        "translation_prompt": DEFAULT_TRANSLATION_PROMPT,
        "metadata_prompt": DEFAULT_METADATA_PROMPT,
    }
    assert patched["updated_at"] is not None

    testing_session = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    with testing_session() as fresh_session:
        saved_settings = TaskRepository(fresh_session).get_app_settings(ASSISTANT_SETTING_KEYS)

    assert saved_settings == {
        "assistant_base_url": update_payload["base_url"],
        "assistant_api_key": update_payload["api_key"],
        "assistant_model_id": update_payload["model_id"],
        "assistant_postprocess_prompt": update_payload["postprocess_prompt"],
        "assistant_translation_prompt": update_payload["translation_prompt"],
        "assistant_metadata_prompt": update_payload["metadata_prompt"],
    }


def test_patch_assistant_settings_requires_all_prompt_templates(client):
    response = client.patch(
        "/api/assistant/settings",
        json={
            "postprocess_prompt": "请清理字幕。",
            "translation_prompt": "请翻译字幕。",
        },
    )

    assert response.status_code == 422


def test_patch_assistant_settings_rejects_null_prompt_templates(client):
    response = client.patch(
        "/api/assistant/settings",
        json={
            "postprocess_prompt": "请清理字幕。",
            "translation_prompt": None,
            "metadata_prompt": "请生成投稿信息。",
        },
    )

    assert response.status_code == 422


def test_patch_assistant_settings_rejects_overlong_prompt_templates(client):
    response = client.patch(
        "/api/assistant/settings",
        json={
            "postprocess_prompt": "请清理字幕。",
            "translation_prompt": "请翻译字幕。",
            "metadata_prompt": "稿" * 10_001,
        },
    )

    assert response.status_code == 422
