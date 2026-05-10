from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./data/app.db"
    api2key_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    image_model_id: str = "gpt-image-2"
    whisper_model_size: str = "medium"
    whisper_compute_type: str = "int8"
    hf_home: str = ""
    hf_hub_cache: str = ""
    hf_hub_disable_xet: str = "1"
    hf_endpoint: str = "https://huggingface.co"
    bilibili_credential_source: str = ""
    youtube_cookies_path: str = "./data/cookies.txt"
    tts_provider: str = "mimo_v2_5_tts"
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    mimo_api_key: str = ""
    mimo_tts_model: str = "mimo-v2.5-tts-voiceclone"
    mimo_tts_voice: str = "冰糖"
    mimo_tts_style_prompt: str = "请用自然、清晰、适合中文视频解说的语气朗读。"
    mimo_tts_timeout_seconds: float = 600.0
    mimo_tts_concurrency: int = 10
    tts_concurrency: int = 10
    openai_tts_base_url: str = "https://api.openai.com/v1"
    openai_tts_api_key: str = ""
    openai_api_key: str = ""
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    openai_tts_instructions: str = ""
    openai_tts_speed: float = 1.0
    openai_tts_timeout_seconds: float = 600.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


def get_settings() -> Settings:
    return Settings()
