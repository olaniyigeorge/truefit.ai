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
    TURN_SERVER_URL: str
    TURN_USERNAME: str
    TURN_CREDENTIAL: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class DevConfig(GlobalConfig):

    pass


class TestConfig(GlobalConfig):

    pass


class ProdConfig(GlobalConfig):
    pass


def get_config():
    env_state = GlobalConfig().ENV.lower()  # Load from `.env` automatically
    configs = {"dev": DevConfig, "prod": ProdConfig, "test": TestConfig}
    if env_state not in configs:
        raise ValueError(f"Invalid ENVT_STATE: {env_state}")
    logger.info(f"\nUsing {env_state.capitalize()} config...\n")
    return configs[env_state]()


AppConfig: DevConfig = get_config()
