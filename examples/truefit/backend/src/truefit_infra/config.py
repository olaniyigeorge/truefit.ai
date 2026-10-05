from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.truefit_core.common.utils import logger


class GlobalConfig(BaseSettings):
    ENV: str
    PROJECT_NAME: str
    API_VERSION: str
    LOG_LEVEL: str
    CLIENT_DOMAIN: str
    BACKEND_DOMAIN: str
    CORS_ORIGINS: str
    APP_SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    AUTH_MODE: str
    DATABASE_URL: str
    DB_ECHO: bool
    REDIS_URL: str
    REDIS_PREFIX: str
    GEMINI_API_KEY: str
    GEMINI_MODEL: str
    GEMINI_LIVE_ENABLED: str
    STORAGE_PROVIDER: str
    LOCAL_STORAGE_DIR: str
    GCS_BUCKET: str
    GOOGLE_APPLICATION_CREDENTIALS: str
    REALTIME_ENABLED: bool
    WEBRTC_TOKEN_SECRET: str
    WORKERS_ENABLED: str
    SENTRY_DSN: str
    FIREBASE_PROJECT_ID: str
    GOOGLE_CLIENT_ID: str | None = None  # only needed for provider="google" sign-in
    TURN_SERVER_URL: str = ""  # optional TURN relay; STUN only when empty
    TURN_USERNAME: str = ""
    TURN_CREDENTIAL: str = ""
    LLM_PRIMARY_PROVIDER: str = "gemini"   # "gemini" | "openai" | "composed"
    LLM_FALLBACK_PROVIDER: str = "none"    # "openai" | "gemini" | "composed" | "none"
    OPENAI_API_KEY: str | None = None
    GEMINI_LIVE_MODEL: str | None = None  # default: gemini-2.5-flash-native-audio-preview-12-2025
    OPENAI_REALTIME_MODEL: str | None = None  # default: gpt-realtime-mini-2025-12-15
    VOICE_TURN_DETECTOR: str = "silero"  # "silero" | "energy"
    # The free local pipeline (provider "composed"): any OpenAI-compatible LLM
    # server, faster-whisper and a Piper voice. No API key needed.
    COMPOSED_LLM_BASE_URL: str | None = None  # default: http://localhost:11434/v1 (Ollama)
    COMPOSED_LLM_MODEL: str | None = None     # default: llama3.2
    COMPOSED_STT_MODEL: str | None = None     # default: base.en
    COMPOSED_TTS_VOICE: str | None = None     # path to a Piper voice .onnx (required for composed)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class DevConfig(GlobalConfig):
    pass


class TestConfig(GlobalConfig):
    pass


class ProdConfig(GlobalConfig):
    pass


def get_config():
    env_state = GlobalConfig().ENV.lower()
    configs = {"dev": DevConfig, "prod": ProdConfig, "test": TestConfig}
    if env_state not in configs:
        raise ValueError(
            f"Invalid ENV {env_state!r}. Valid values: {', '.join(configs)}"
        )
    logger.info(f"\nUsing {env_state.capitalize()} config...\n")
    return configs[env_state]()


AppConfig: DevConfig = get_config()
