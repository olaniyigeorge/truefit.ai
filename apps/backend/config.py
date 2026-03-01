from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.truefit_core.common.utils import logger


class GlobalConfig(BaseSettings):
    ENV: str
    PROJECT_NAME: str
    CLIENT_DOMAIN: str
    INVITE_CODE_PREFIX: str
    DOMAIN: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int
    DATABASE_URL: str
    ALGORITHM: str
    APP_SECRET_KEY: str
    PAYSTACK_SECRET_KEY: str
    PAYSTACK_PUBLIC_KEY: str
    REDIS_URL: str
    GEMINI_API_KEY: str
    MAIL_USERNAME:str
    MAIL_PASSWORD:str
    MAIL_FROM:str
    MAIL_FROM_NAME:str
    MAIL_PORT:int
    MAIL_SERVER:str
    MAIL_STARTTLS:bool
    MAIL_SSL_TLS:bool
    USE_CREDENTIALS:bool
    GOOGLE_CLIENT_ID: str
    SENDGRID_API_KEY: str
    SEND_MAIL_TOKEN: str
    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str

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
