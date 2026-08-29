from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    aws_region: str = "us-east-1"
    dynamodb_table: str = "url-shortener"
    app_env: str = "development"
    debug: bool = True
    base_url: str = "http://localhost:8000"
    short_code_length: int = 7
    default_ttl_days: int = 30
    max_ttl_days: int = 365
    max_url_length: int = 2048
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
