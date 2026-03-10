from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "X Ads Automation"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    DATABASE_URL: str = "sqlite:///./data/x_ads_automation.db"

    # Fernet encryption key for API credentials
    ENCRYPTION_KEY: str = ""

    # Session signing secret
    SECRET_KEY: str = "change-me-in-production"

    # Admin usernames (comma-separated)
    ADMIN_USERNAMES: str = ""

    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
